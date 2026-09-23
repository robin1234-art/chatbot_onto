"""Index flou des individus de l'ontologie.

L'utilisateur désigne souvent une entité avec une orthographe approximative
("docteur Bornard" pour "Dr Bernard", "hopital saint louis" pour
"Hôpital Saint-Louis"). Ce module indexe les littéraux portés par chaque
individu (`rdfs:label`, `ex:name`) et classe les individus par proximité
lexicale avec un terme, éventuellement restreint à une classe.

La comparaison se fait sur des chaînes normalisées (minuscules, sans accents
ni ponctuation), une seconde fois sans le préfixe usuel de la classe ("Dr",
"Hôpital"...) pour que "Bernard" retrouve "Dr Bernard".
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS
from rapidfuzz import fuzz


def normalize(text: str) -> str:
    """Minuscules, sans accents, ponctuation remplacée par des espaces."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s]", " ", text.lower())
    return " ".join(text.split())


# Articles pouvant précéder un préfixe dans un terme ("l'hôpital Saint-Louis").
_LEADING_ARTICLES = {"l", "le", "la", "les"}


def strip_prefix(norm: str, prefixes: tuple[str, ...]) -> str:
    """Retire d'un texte normalisé un article puis un préfixe de classe en tête.

    Les préfixes doivent être normalisés ; seul un mot entier est retiré.
    """
    words = norm.split()
    if words and words[0] in _LEADING_ARTICLES:
        words = words[1:]
    text = " ".join(words)
    for prefix in prefixes:
        if text.startswith(prefix + " "):
            return text[len(prefix) + 1:]
    return text


def local_name(uri: URIRef) -> str:
    return re.split(r"[#/]", str(uri))[-1]


@dataclass(frozen=True)
class Match:
    uri: URIRef
    label: str  # label canonique de l'individu, à réinjecter dans la question
    score: float


@dataclass(frozen=True)
class _Entry:
    uri: URIRef
    cls: URIRef
    label: str
    norm: str
    prefixes: tuple[str, ...]  # préfixes normalisés de la classe de l'individu
    stripped: str | None  # `norm` sans préfixe, None si aucun préfixe retiré

    def score(self, norm_term: str) -> float:
        """Meilleur score entre texte complet et texte sans préfixe."""
        score = fuzz.ratio(norm_term, self.norm)
        if self.stripped is not None:
            stripped_term = strip_prefix(norm_term, self.prefixes)
            score = max(score, fuzz.ratio(stripped_term, self.stripped))
        return score


class InstanceIndex:
    """Individus des classes OWL du graphe, indexés par leurs littéraux."""

    def __init__(self, entries: list[_Entry], classes: dict[URIRef, str]):
        self._entries = entries
        self.classes = classes  # URI de classe -> label

    @classmethod
    def from_graph(
        cls,
        graph: Graph,
        name_prefixes: dict[URIRef, tuple[str, ...]] | None = None,
    ) -> "InstanceIndex":
        """Indexe les individus de chaque classe OWL du graphe.

        `name_prefixes` associe à une classe les préfixes usuels des noms de
        ses individus ("Dr", "Hôpital"...), ignorés lors d'une 2e comparaison.
        """
        name_prefixes = name_prefixes or {}
        entries: dict[tuple[URIRef, str], _Entry] = {}
        classes: dict[URIRef, str] = {}
        for cls_uri in graph.subjects(RDF.type, OWL.Class):
            classes[cls_uri] = str(graph.value(cls_uri, RDFS.label) or local_name(cls_uri))
            prefixes = tuple(normalize(p) for p in name_prefixes.get(cls_uri, ()))
            for individual in graph.subjects(RDF.type, cls_uri):
                label = graph.value(individual, RDFS.label)
                label = str(label) if label is not None else local_name(individual)
                for obj in graph.objects(individual):
                    if not (isinstance(obj, Literal) and isinstance(obj.value, str)):
                        continue
                    norm = normalize(str(obj))
                    stripped = strip_prefix(norm, prefixes) if prefixes else norm
                    entries[(individual, norm)] = _Entry(
                        individual, cls_uri, label, norm, prefixes,
                        stripped if stripped != norm and stripped else None,
                    )
        return cls(list(entries.values()), classes)

    def search(self, term: str, cls: URIRef | None = None) -> list[Match]:
        """Individus classés par score décroissant, un seul match par individu.

        `cls` restreint la recherche aux individus de cette classe.
        """
        norm_term = normalize(term)
        best: dict[URIRef, Match] = {}
        for entry in self._entries:
            if cls is not None and entry.cls != cls:
                continue
            score = entry.score(norm_term)
            if entry.uri not in best or score > best[entry.uri].score:
                best[entry.uri] = Match(entry.uri, entry.label, score)
        return sorted(best.values(), key=lambda m: (-m.score, m.label))
