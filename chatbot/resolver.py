"""Résolution des entités nommées d'une question, en amont de GraphSparqlQAChain.

Déroulé pour une question :

1. le LLM repère les mentions d'individus ("docteur Bornard") et devine
   leur classe (`Doctor`), sans rien corriger ;
2. chaque mention est cherchée dans l'index flou, restreint à la classe
   devinée (élargi à toute l'ontologie si la classe ne donne rien) :
   - correspondance exacte après normalisation -> corrigée d'office ;
   - un candidat proche -> proposé à l'utilisateur ;
   - plusieurs candidats proches -> liste proposée à l'utilisateur ;
   - aucun candidat -> liste des individus de la classe proposée ;
3. la question est réécrite avec le label canonique retenu, entre
   guillemets, pour que le LLM SPARQL recopie la bonne chaîne. Si
   l'utilisateur garde sa formulation, la mention est laissée telle quelle.

Aucune entrée/sortie ici : le choix de l'utilisateur est délégué à un
callback (`Chooser`), fourni par l'interface (voir cli.py).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from rdflib import Graph, URIRef

from ontology.schema import NAME_PREFIXES

from .entity_matcher import InstanceIndex, Match, local_name

logger = logging.getLogger(__name__)

# Écart minimal entre les deux meilleurs candidats pour n'en proposer qu'un.
AMBIGUITY_MARGIN = 5.0
# Nombre maximal de candidats listés à l'utilisateur.
MAX_CANDIDATES = 5


class Status(Enum):
    EXACT = "exact"  # corrigé d'office
    SUGGESTION = "suggestion"  # un candidat à confirmer
    AMBIGUOUS = "ambiguous"  # plusieurs candidats proches
    NOT_FOUND = "not_found"  # aucun candidat proche ; individus de la classe


@dataclass(frozen=True)
class Mention:
    text: str  # extrait tel qu'écrit dans la question
    cls: URIRef | None  # classe devinée par le LLM


@dataclass(frozen=True)
class Resolution:
    mention: Mention
    status: Status
    candidates: tuple[Match, ...]


# Reçoit une résolution à arbitrer, renvoie le label retenu ou None pour
# garder la formulation d'origine.
Chooser = Callable[[Resolution], "str | None"]


_EXTRACTION_PROMPT = """Tu analyses une question posée à un chatbot qui interroge une ontologie.

Repère les mentions d'individus précis, désignés par leur nom propre (une
personne, un établissement, une maladie...). N'extrais pas les noms de classes
employés de façon générique ("les médecins", "un patient").

Classes de l'ontologie :
{classes}

Pour chaque mention, recopie le texte EXACTEMENT tel qu'il apparaît dans la
question, titre ou préfixe compris ("docteur Bornard"), sans corriger
l'orthographe, et indique la classe la plus probable (nom de classe ci-dessus,
ou null si aucune ne convient).

Réponds uniquement avec un objet JSON, sans texte autour :
{{"mentions": [{{"text": "...", "class": "..."}}]}}

Question : {question}"""

_CODE_FENCE_RE = re.compile(r"^```[a-zA-Z]*\n?|\n?```$", re.MULTILINE)


def extract_mentions(question: str, llm, classes: dict[URIRef, str]) -> list[Mention]:
    """Demande au LLM les mentions d'individus de la question.

    Une réponse illisible, ou une mention absente de la question, est ignorée :
    la question part alors telle quelle vers la chaîne SPARQL.
    """
    by_name = {local_name(uri): uri for uri in classes}
    prompt = _EXTRACTION_PROMPT.format(
        classes="\n".join(f"- {local_name(uri)} : {label}" for uri, label in classes.items()),
        question=question,
    )
    raw = llm.invoke(prompt).content
    try:
        items = json.loads(_CODE_FENCE_RE.sub("", raw).strip())["mentions"]
    except (json.JSONDecodeError, KeyError, TypeError):
        logger.warning("[résolution] réponse d'extraction illisible : %r", raw)
        return []

    mentions = []
    for item in items:
        text = str(item.get("text") or "").strip() if isinstance(item, dict) else ""
        if not text:
            continue
        if text.lower() not in question.lower():
            logger.info('[résolution] mention "%s" absente de la question : ignorée', text)
            continue
        mentions.append(Mention(text, by_name.get(item.get("class"))))
    return mentions


def resolve(mention: Mention, index: InstanceIndex, threshold: float) -> Resolution:
    """Classe les individus proches d'une mention (voir docstring du module)."""
    in_class = index.search(mention.text, mention.cls)
    ranked = in_class
    if mention.cls is not None and not (in_class and in_class[0].score >= threshold):
        # La classe devinée par le LLM peut être fausse : on élargit.
        everywhere = index.search(mention.text)
        if everywhere and everywhere[0].score >= threshold:
            ranked = everywhere

    above = [m for m in ranked if m.score >= threshold]
    if not above:
        # Rien de proche : on liste les individus de la classe, s'il y en a une.
        fallback = in_class[:MAX_CANDIDATES] if mention.cls is not None else []
        return Resolution(mention, Status.NOT_FOUND, tuple(fallback))

    close = [m for m in above if above[0].score - m.score < AMBIGUITY_MARGIN]
    if len(close) > 1:
        return Resolution(mention, Status.AMBIGUOUS, tuple(close[:MAX_CANDIDATES]))
    status = Status.EXACT if above[0].score == 100 else Status.SUGGESTION
    return Resolution(mention, status, (above[0],))


def rewrite(question: str, choices: list[tuple[Mention, str]]) -> str:
    """Remplace chaque mention par son label retenu, entre guillemets."""
    for mention, label in choices:
        pattern = re.compile(rf'"?{re.escape(mention.text)}"?', re.IGNORECASE)
        question = pattern.sub(lambda _: f'"{label}"', question, count=1)
    return question


class QuestionResolver:
    """Reformule une question en y fixant les noms d'individus de l'ontologie."""

    def __init__(self, llm, index: InstanceIndex, threshold: float):
        self.llm = llm
        self.index = index
        self.threshold = threshold

    @classmethod
    def from_graph(cls, graph: Graph, llm, threshold: float) -> "QuestionResolver":
        return cls(llm, InstanceIndex.from_graph(graph, NAME_PREFIXES), threshold)

    def reformulate(self, question: str, choose: Chooser) -> str:
        choices = []
        for mention in extract_mentions(question, self.llm, self.index.classes):
            resolution = resolve(mention, self.index, self.threshold)
            if resolution.status is Status.EXACT:
                label = resolution.candidates[0].label
                logger.info('[résolution] "%s" -> "%s"', mention.text, label)
            elif resolution.candidates:
                label = choose(resolution)
            else:
                logger.info('[résolution] aucune entité proche de "%s"', mention.text)
                label = None
            if label is not None:
                choices.append((mention, label))
        return rewrite(question, choices)
