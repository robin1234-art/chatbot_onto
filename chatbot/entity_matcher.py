"""Correction floue des littéraux d'instance dans les requêtes SPARQL générées.

Le LLM recopie souvent le nom d'une entité avec une orthographe approximative
("Hopital Saint Louis" au lieu de "Hôpital Saint-Louis") ou avec un tag de
langue qui ne correspond pas au prédicat (`rdfs:label` est tagué `@fr`,
`ex:name` ne l'est pas). Dans les deux cas rdflib ne trouve rien et la chaîne
répond "je ne sais pas" sans explication.

Ce module indexe les littéraux portés par les individus de l'ontologie et
remplace, avant exécution, un littéral de la requête par sa forme canonique
quand le fuzzy match dépasse un seuil élevé. Seules les positions d'égalité
sont corrigées :

    ?h ex:name "Hopital Saint Louis" .          # objet d'un triplet
    FILTER(?nom = "Hopital Saint Louis")        # comparaison d'égalité
    FILTER(STR(?nom) = "Hopital Saint Louis")   # idem, forme sans tag

Les littéraux passés à CONTAINS/REGEX/STRSTARTS... ne sont pas modifiés :
les remplacer par un label complet changerait la sémantique de la requête.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

# Écart minimal entre les deux meilleurs candidats pour oser corriger.
AMBIGUITY_MARGIN = 5.0

_LITERAL_RE = re.compile(r'"((?:[^"\\]|\\.)*)"(@[A-Za-z]+(?:-[A-Za-z0-9]+)*|\^\^\S+)?')
_PREFIX_RE = re.compile(r"PREFIX\s+([\w-]*):\s*<([^>]*)>", re.IGNORECASE)
_PREDICATE = r"(?:[\w-]*:[\w-]+|<[^>\s]+>)"
# Littéral en position d'objet : précédé directement d'un prédicat.
_TRIPLE_OBJECT_RE = re.compile(rf"({_PREDICATE})\s+$")
# Littéral à droite d'une égalité : `?v = "…"` ou `STR(?v) = "…"`. Toute
# autre fonction (`LCASE(?v) = "…"`) est exclue : le littéral y est
# volontairement transformé et le canoniser casserait la comparaison.
_EQ_BEFORE_RE = re.compile(
    r"(?:\b(STR)\s*\(\s*\?(\w+)\s*\)|\?(\w+))\s*=\s*$", re.IGNORECASE
)
# Littéral à gauche d'une égalité : `"…" = ?v` ou `"…" = STR(?v)`.
_EQ_AFTER_RE = re.compile(
    r"^\s*=\s*(?:\b(STR)\s*\(\s*\?(\w+)\s*\)|\?(\w+)\b(?!\s*\())", re.IGNORECASE
)


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


@dataclass(frozen=True)
class Match:
    literal: Literal
    score: float


@dataclass(frozen=True)
class _Candidate:
    literal: Literal
    norm: str
    prefixes: tuple[str, ...]  # préfixes normalisés de la classe de l'individu
    stripped: str | None  # `norm` sans préfixe, None si aucun préfixe retiré

    def full_score(self, norm_term: str) -> float:
        return fuzz.ratio(norm_term, self.norm)

    def score(self, norm_term: str) -> float:
        """Meilleur score entre label complet et label sans préfixe."""
        score = self.full_score(norm_term)
        if self.stripped is not None:
            stripped_term = strip_prefix(norm_term, self.prefixes)
            score = max(score, fuzz.ratio(stripped_term, self.stripped))
        return score


class InstanceIndex:
    """Littéraux chaînes des individus, groupés par prédicat."""

    def __init__(self, candidates_by_predicate: dict[URIRef, list[_Candidate]]):
        self._candidates = candidates_by_predicate

    @classmethod
    def from_graph(
        cls,
        graph: Graph,
        name_prefixes: dict[URIRef, tuple[str, ...]] | None = None,
    ) -> "InstanceIndex":
        """Indexe les littéraux des individus de chaque classe OWL du graphe.

        `name_prefixes` associe à une classe les préfixes usuels des noms de
        ses individus ("Dr", "Hôpital"...), ignorés lors d'une 2e comparaison.
        """
        name_prefixes = name_prefixes or {}
        by_pred: dict[URIRef, dict[tuple[Literal, tuple[str, ...]], _Candidate]] = {}
        for cls_uri in graph.subjects(RDF.type, OWL.Class):
            prefixes = tuple(normalize(p) for p in name_prefixes.get(cls_uri, ()))
            for individual in graph.subjects(RDF.type, cls_uri):
                for pred, obj in graph.predicate_objects(individual):
                    if not (isinstance(obj, Literal) and isinstance(obj.value, str)):
                        continue
                    norm = normalize(str(obj))
                    stripped = strip_prefix(norm, prefixes) if prefixes else norm
                    candidate = _Candidate(
                        obj, norm, prefixes, stripped if stripped != norm and stripped else None
                    )
                    by_pred.setdefault(pred, {})[(obj, prefixes)] = candidate
        return cls({pred: list(cands.values()) for pred, cands in by_pred.items()})

    @property
    def predicates(self) -> set[URIRef]:
        return set(self._candidates)

    def match(self, term: str, predicate: URIRef | None, threshold: float) -> Match | None:
        """Meilleur candidat au-dessus du seuil, ou None si absent/ambigu.

        `predicate=None` cherche parmi tous les prédicats indexés. Le label
        complet est prioritaire : la comparaison sans préfixe n'intervient que
        si elle ne donne rien de concluant ("CHU Saint-Louis" doit désigner le
        CHU même si "Hôpital Saint-Louis" existe aussi).
        """
        if predicate is None:
            pool = [c for cands in self._candidates.values() for c in cands]
        else:
            pool = self._candidates.get(predicate, [])

        norm_term = normalize(term)
        full = self._best(pool, lambda c: c.full_score(norm_term), threshold)
        if isinstance(full, Match):
            return full
        best = self._best(pool, lambda c: c.score(norm_term), threshold)
        if isinstance(best, Match):
            return best
        if best is not None:
            logger.info(
                '[fuzzy] "%s" ambigu entre %s et %s : non corrigé',
                term, best[0].literal.n3(), best[1].literal.n3(),
            )
        return None

    @staticmethod
    def _best(pool, scorer, threshold: float) -> Match | tuple[Match, Match] | None:
        """Meilleur match au-dessus du seuil, les 2 premiers si ambigu, sinon None."""
        # Plusieurs individus/prédicats peuvent porter le même texte : on
        # garde le meilleur score par forme normalisée pour juger l'ambiguïté.
        best_by_norm: dict[str, Match] = {}
        for candidate in pool:
            score = scorer(candidate)
            best = best_by_norm.get(candidate.norm)
            if best is None or score > best.score:
                best_by_norm[candidate.norm] = Match(candidate.literal, score)

        ranked = sorted(best_by_norm.values(), key=lambda m: m.score, reverse=True)
        if not ranked or ranked[0].score < threshold:
            return None
        if len(ranked) > 1 and ranked[0].score - ranked[1].score < AMBIGUITY_MARGIN:
            return ranked[0], ranked[1]
        return ranked[0]


def _resolve(token: str, prefixes: dict[str, str]) -> URIRef | None:
    if token.startswith("<"):
        return URIRef(token[1:-1])
    prefix, _, local = token.partition(":")
    if prefix in prefixes:
        return URIRef(prefixes[prefix] + local)
    return None


def _predicate_of_variable(query: str, var: str, prefixes: dict[str, str]) -> URIRef | None:
    """Prédicat qui lie `?var` en position d'objet (`?s <pred> ?var`)."""
    m = re.search(rf"({_PREDICATE})\s+\?{re.escape(var)}\b", query)
    return _resolve(m.group(1), prefixes) if m else None


def correct_instance_literals(query: str, index: InstanceIndex, threshold: float) -> str:
    """Remplace les littéraux d'instance mal orthographiés par leur forme canonique."""
    prefixes = {p: ns for p, ns in _PREFIX_RE.findall(query)}

    def replace(m: re.Match) -> str:
        original = m.group(0)
        term = m.group(1)
        before = query[: m.start()]
        after = query[m.end():]

        plain = False  # True : comparer sur la forme lexicale (sans tag)
        triple = _TRIPLE_OBJECT_RE.search(before)
        eq = _EQ_BEFORE_RE.search(before) or _EQ_AFTER_RE.search(after)
        if triple:
            predicate = _resolve(triple.group(1), prefixes)
            if predicate not in index.predicates:
                return original
        elif eq:
            plain = bool(eq.group(1))
            var = eq.group(2) or eq.group(3)
            predicate = _predicate_of_variable(query, var, prefixes)
            if predicate not in index.predicates:
                predicate = None
        else:
            return original

        match = index.match(term, predicate, threshold)
        if match is None:
            return original
        canonical = Literal(str(match.literal)) if plain else match.literal
        replacement = canonical.n3()
        if replacement != original:
            logger.info(
                "[fuzzy] %s -> %s (score %.0f)", original, replacement, match.score
            )
        return replacement

    return _LITERAL_RE.sub(replace, query)
