"""RdfGraph qui nettoie les requêtes SPARQL générées par le LLM.

`GraphSparqlQAChain` transmet le texte généré par le LLM tel quel à
`RdfGraph.query`/`update`. Or beaucoup de modèles de chat entourent leur
réponse de balises ```sparql ... ``` malgré la consigne du prompt de ne
renvoyer que la requête, ce qui fait échouer le parseur SPARQL de rdflib sur
le backtick.

Le LLM déclare aussi parfois deux préfixes pour le même espace de noms
(`PREFIX ex:` et `PREFIX nobel:`). C'est du SPARQL valide, mais rdflib n'en
retient qu'un et rejette l'autre ("Unknown namespace prefix : ex") : les
doublons sont ramenés au premier préfixe déclaré.

Les triplets écrits à l'envers (`?attribution nobel:received ?laureat`) sont
remis dans le sens du schéma (voir triple_direction.py), et un individu
désigné par son nom ou par une IRI inventée (`nobel:category "prix Nobel de
la paix"`, `nobel:category nobel:physics`) est remplacé par son IRI (voir
individuals.py). `mentioned` reçoit pour cela les IRI citées dans la question.

Les nombres et dates écrits entre guillemets sont convertis vers le type
déclaré dans le schéma avant exécution (voir typed_literals.py).

Le schéma exposé au LLM est complété par des noms d'individus de chaque
classe : sans eux, le LLM ignore que "prix Nobel de physique" est un individu
désigné par son nom, et invente une IRI (nobel:Physics).

Les noms d'entités mal orthographiés sont corrigés en amont, sur la
question elle-même (voir resolver.py).
"""

import logging
import re

from langchain_community.graphs import RdfGraph
from rdflib import URIRef
from rdflib.plugins.sparql.algebra import translateQuery
from rdflib.plugins.sparql.parser import parseQuery
from rdflib.query import ResultRow

from .entity_matcher import InstanceIndex, local_name
from .individuals import resolve_individuals
from .triple_direction import fix_directions, property_signatures
from .typed_literals import coerce_literals, datatype_ranges

logger = logging.getLogger(__name__)

_CODE_FENCE_RE = re.compile(r"^```[a-zA-Z]*\n?|\n?```$", re.MULTILINE)


_PREFIX_DECL_RE = re.compile(
    r"^\s*PREFIX\s+([\w-]*):\s*<([^>]*)>\s*\n?", re.IGNORECASE | re.MULTILINE
)


def _strip_code_fence(query: str) -> str:
    return _CODE_FENCE_RE.sub("", query).strip()


def _merge_duplicate_prefixes(query: str) -> str:
    """Ramène les préfixes déclarant une même IRI au premier d'entre eux."""
    first_by_iri: dict[str, str] = {}
    aliases: dict[str, str] = {}  # préfixe en double -> préfixe conservé
    for prefix, iri in _PREFIX_DECL_RE.findall(query):
        kept = first_by_iri.setdefault(iri, prefix)
        if kept != prefix:
            aliases[prefix] = kept
    if not aliases:
        return query

    def drop_duplicate_decl(match: re.Match) -> str:
        return "" if match.group(1) in aliases else match.group(0)

    query = _PREFIX_DECL_RE.sub(drop_duplicate_decl, query)
    for alias, kept in aliases.items():
        # Nom préfixé `ex:name`, hors IRI entre chevrons et hors autre nom.
        query = re.sub(rf"(?<![\w<:/.-]){re.escape(alias)}:(?=\w)", f"{kept}:", query)
    return query


def _clean(query: str) -> str:
    return _merge_duplicate_prefixes(_strip_code_fence(query))


class CleanRdfGraph(RdfGraph):
    """RdfGraph qui nettoie la requête générée (balises, préfixes, sens, individus, types)."""

    # IRI d'individus citées dans la question en cours (voir resolver.py).
    mentioned: list[URIRef] = []

    def load_schema(self) -> None:
        # Avant super().load_schema(), qui passe déjà par self.query.
        self._ranges = datatype_ranges(self.graph)
        self._signatures = property_signatures(self.graph)
        self._index = InstanceIndex.from_graph(self.graph)
        super().load_schema()
        lines = [
            f"{local_name(cls)} : " + ", ".join(f'"{label}"' for label in labels)
            for cls, labels in self._index.examples.items()
            if labels
        ]
        self.schema += (
            "Exemples de noms d'individus, par classe (valeurs de la propriété de nom) :\n"
            + "\n".join(lines)
            + "\n"
        )

    def query(self, query: str) -> list[ResultRow]:
        # Comme Graph.query, qui n'est plus appelé sur le texte : les préfixes
        # du graphe (nobel:, wd:...) restent utilisables sans PREFIX déclaré.
        parsed = translateQuery(parseQuery(_clean(query)), initNs=dict(self.graph.namespaces()))
        # Le sens d'abord : les types des variables en dépendent.
        swaps = fix_directions(parsed, self.graph, self._signatures)
        if swaps:
            logger.info("[sens] %d triplet(s) remis dans le sens du schéma", swaps)
        named = resolve_individuals(
            parsed, self.graph, self._signatures, self._index, self.mentioned
        )
        if named:
            logger.info("[individus] %d individu(s) remplacé(s) par l'IRI attendue", named)
        fixes = coerce_literals(parsed, self._ranges)
        if fixes:
            logger.info("[types] %d littéral(aux) converti(s) vers le type du schéma", fixes)
        return [row for row in self.graph.query(parsed) if isinstance(row, ResultRow)]

    def update(self, query: str) -> None:
        return super().update(_clean(query))
