"""Résolution des entités nommées d'une question, en amont de GraphSparqlQAChain.

Déroulé pour une question :

1. le LLM repère les mentions d'individus ("docteur Bornard") et devine
   leur classe (`Doctor`), sans rien corriger ;
2. chaque mention est cherchée dans l'index flou, restreint à la classe
   devinée (élargi à toute l'ontologie si la classe ne donne rien ; les
   correspondances exactes des autres classes sont toujours ajoutées) :
   - correspondance exacte après normalisation -> corrigée d'office ;
   - un candidat proche -> proposé à l'utilisateur ;
   - plusieurs candidats proches -> liste proposée à l'utilisateur ;
   - aucun candidat -> liste des individus de la classe proposée ;
3. chaque mention est suivie, entre parenthèses, du label canonique retenu
   et de l'IRI de l'individu ("Français" -> `Français ("France" <...Q142>)`,
   la phrase reste grammaticale) : le LLM SPARQL utilise l'IRI
   directement, sans jointure sur le nom, qui ne distingue pas les homonymes
   ("Cambridge", ville d'Angleterre ou du Massachusetts). Si l'utilisateur
   garde sa formulation, la mention est laissée telle quelle.

Aucune entrée/sortie ici : le choix de l'utilisateur est délégué à un
callback (`Chooser`), fourni par l'interface (voir cli.py).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from rdflib import Graph, URIRef

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


# Reçoit une résolution à arbitrer, renvoie l'individu retenu ou None pour
# garder la formulation d'origine.
Chooser = Callable[[Resolution], Match | None]


_EXTRACTION_PROMPT = """Tu analyses une question posée à un chatbot qui interroge une ontologie.

Repère toutes les mentions d'individus précis de l'ontologie :
- les noms propres (une personne, un établissement, une ville...) ;
- les noms communs qui sont le nom d'un individu, comme les exemples donnés
  ci-dessous : ils se repèrent même abrégés ;
- les adjectifs qui renvoient à un individu ("français" -> un pays).
N'extrais pas les noms de classes employés de façon générique ("les
médecins", "un lauréat", "une université").

Classes de l'ontologie, avec des exemples d'individus :
{classes}

Pour chaque mention, recopie le texte EXACTEMENT tel qu'il apparaît dans la
question, titre ou préfixe compris ("docteur Bornard"), sans corriger
l'orthographe, et indique la classe la plus probable (nom de classe ci-dessus,
ou null si aucune ne convient).

Réponds uniquement avec un objet JSON, sans texte autour :
{{"mentions": [{{"text": "...", "class": "..."}}]}}

Question : {question}"""

_CODE_FENCE_RE = re.compile(r"^```[a-zA-Z]*\n?|\n?```$", re.MULTILINE)


def extract_mentions(question: str, llm, index: InstanceIndex) -> list[Mention]:
    """Demande au LLM les mentions d'individus de la question.

    Une réponse illisible, ou une mention absente de la question, est ignorée :
    la question part alors telle quelle vers la chaîne SPARQL.
    """
    by_name = {local_name(uri): uri for uri in index.classes}
    lines = []
    for uri, label in index.classes.items():
        examples = index.examples.get(uri)
        suffix = f" (ex. : {', '.join(examples)})" if examples else ""
        lines.append(f"- {local_name(uri)} : {label}{suffix}")
    prompt = _EXTRACTION_PROMPT.format(classes="\n".join(lines), question=question)
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
    if mention.cls is not None:
        # La classe devinée par le LLM peut être fausse : on élargit si elle ne
        # donne rien, et on ajoute toujours les homonymes exacts des autres
        # classes ("Cambridge" : la ville, mais aussi l'université).
        everywhere = index.search(mention.text)
        if not (in_class and in_class[0].score >= threshold):
            if everywhere and everywhere[0].score >= threshold:
                ranked = everywhere
        else:
            seen = {m.uri for m in in_class}
            exact_elsewhere = [m for m in everywhere if m.score == 100 and m.uri not in seen]
            ranked = sorted([*in_class, *exact_elsewhere], key=lambda m: (-m.score, m.label))

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


def rewrite(question: str, choices: list[tuple[Mention, Match]]) -> str:
    """Fait suivre chaque mention du label retenu entre guillemets et de son IRI."""
    for mention, match in choices:
        pattern = re.compile(re.escape(mention.text), re.IGNORECASE)
        annotation = f' ("{match.label}" <{match.uri}>)'
        question = pattern.sub(lambda m, a=annotation: m.group(0) + a, question, count=1)
    return question


class QuestionResolver:
    """Reformule une question en y fixant les noms d'individus de l'ontologie."""

    def __init__(self, llm, index: InstanceIndex, threshold: float):
        self.llm = llm
        self.index = index
        self.threshold = threshold

    @classmethod
    def from_graph(cls, graph: Graph, llm, threshold: float) -> QuestionResolver:
        return cls(llm, InstanceIndex.from_graph(graph), threshold)

    def reformulate(self, question: str, choose: Chooser) -> str:
        choices = []
        for mention in extract_mentions(question, self.llm, self.index):
            resolution = resolve(mention, self.index, self.threshold)
            if resolution.status is Status.EXACT:
                match = resolution.candidates[0]
                if match.label != mention.text:
                    logger.info('[résolution] "%s" -> "%s"', mention.text, match.label)
            elif resolution.candidates:
                match = choose(resolution)
            else:
                logger.info('[résolution] aucune entité proche de "%s"', mention.text)
                match = None
            if match is not None:
                choices.append((mention, match))
        return rewrite(question, choices)
