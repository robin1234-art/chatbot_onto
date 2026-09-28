"""Index flou des individus de l'ontologie.

L'utilisateur désigne souvent une entité avec une orthographe approximative
("docteur Bornard" pour "Dr Bernard", "hopital saint louis" pour
"Hôpital Saint-Louis"). Ce module indexe les littéraux portés par chaque
individu (`rdfs:label`, `ex:name`) et classe les individus par proximité
lexicale avec un terme, éventuellement restreint à une classe.

Seuls les littéraux de nom sont indexés : `rdfs:label`, `skos:altLabel` et
leurs sous-propriétés (`ex:name`...). Un littéral descriptif ("femme", une
motivation) ferait sinon d'un mot courant l'alias de nombreux individus.

La comparaison se fait sur des chaînes normalisées (minuscules, sans accents
ni ponctuation), une seconde fois sans le préfixe usuel de la classe ("Dr",
"Hôpital"...) pour que "Bernard" retrouve "Dr Bernard". Ces préfixes sont
lus dans l'ontologie (annotation `chatbot:namePrefix` de la classe).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS

from ontology.namespace import CHATBOT

# Individus représentatifs retenus par classe (voir `examples`) : tous
# jusqu'à MAX_LISTED_INDIVIDUALS, sinon les EXAMPLES_PER_CLASS plus cités.
EXAMPLES_PER_CLASS = 3
MAX_LISTED_INDIVIDUALS = 8


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
            return text[len(prefix) + 1 :]
    return text


def local_name(uri: URIRef) -> str:
    return re.split(r"[#/]", str(uri))[-1]


@dataclass(frozen=True)
class Match:
    uri: URIRef
    label: str  # label canonique de l'individu, à réinjecter dans la question
    score: float
    # Classe et description de l'individu, pour distinguer des homonymes.
    description: str = ""


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

    def __init__(
        self,
        entries: list[_Entry],
        classes: dict[URIRef, str],
        examples: dict[URIRef, tuple[str, ...]] | None = None,
        descriptions: dict[URIRef, str] | None = None,
    ):
        self._entries = entries
        self.classes = classes  # URI de classe -> label
        # URI de classe -> labels d'individus représentatifs, pour montrer aux
        # LLM à quoi ressemble un individu de chaque classe.
        self.examples = examples or {}
        self._descriptions = descriptions or {}  # URI d'individu -> rdfs:comment

    @classmethod
    def from_graph(cls, graph: Graph) -> InstanceIndex:
        """Indexe les individus de chaque classe OWL du graphe par leurs noms."""
        name_props = {
            prop
            for root in (RDFS.label, SKOS.altLabel)
            for prop in graph.transitive_subjects(RDFS.subPropertyOf, root)
        }
        entries: dict[tuple[URIRef, str], _Entry] = {}
        classes: dict[URIRef, str] = {}
        examples: dict[URIRef, tuple[str, ...]] = {}
        descriptions: dict[URIRef, str] = {}
        for cls_uri in graph.subjects(RDF.type, OWL.Class):
            classes[cls_uri] = str(graph.value(cls_uri, RDFS.label) or local_name(cls_uri))
            # Plus long d'abord : "université de" avant "université".
            prefixes = tuple(
                sorted(
                    {normalize(str(p)) for p in graph.objects(cls_uri, CHATBOT.namePrefix)},
                    key=len,
                    reverse=True,
                )
            )
            labelled = []
            for individual in graph.subjects(RDF.type, cls_uri):
                label = graph.value(individual, RDFS.label)
                if label is not None:
                    # Les plus cités d'abord : "Marie Curie" plutôt qu'un inconnu.
                    labelled.append((-len(set(graph.subjects(None, individual))), str(label)))
                label = str(label) if label is not None else local_name(individual)
                comment = graph.value(individual, RDFS.comment)
                if comment is not None:
                    descriptions[individual] = str(comment)
                for prop, obj in graph.predicate_objects(individual):
                    if prop not in name_props or not isinstance(obj, Literal):
                        continue
                    norm = normalize(str(obj))
                    stripped = strip_prefix(norm, prefixes) if prefixes else norm
                    entries[(individual, norm)] = _Entry(
                        individual,
                        cls_uri,
                        label,
                        norm,
                        prefixes,
                        stripped if stripped != norm and stripped else None,
                    )
            if len(labelled) > MAX_LISTED_INDIVIDUALS:
                labelled = sorted(labelled)[:EXAMPLES_PER_CLASS]
            examples[cls_uri] = tuple(label for _, label in sorted(labelled))
        return cls(list(entries.values()), classes, examples, descriptions)

    def _describe(self, entry: _Entry) -> str:
        """ "Lieu, ville du Massachusetts" : classe puis description éventuelle."""
        parts = [self.classes[entry.cls], self._descriptions.get(entry.uri)]
        return ", ".join(p for p in parts if p)

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
                best[entry.uri] = Match(entry.uri, entry.label, score, self._describe(entry))
        return sorted(best.values(), key=lambda m: (-m.score, m.label))
