"""Remplacement des individus mal désignés dans une requête SPARQL générée.

Même quand la question fournit l'IRI d'un individu (voir resolver.py), le LLM
désigne parfois l'individu autrement comme objet d'une propriété d'objet :

- par son nom : `?a nobel:category "prix Nobel de la paix"` ;
- par une IRI inventée : `?a nobel:category nobel:physics`.

La requête ne renvoie alors rien. L'objet d'une propriété d'objet est un
individu de la classe de sa portée ; il est remplacé :

- un littéral, par l'individu de cette classe qui porte exactement ce nom
  (après normalisation : casse, accents, préfixe de classe) ;
- une IRI absente du graphe, par l'IRI de cette classe citée dans la
  question.

Sans candidat unique, l'objet est laissé tel quel : le résolveur de la
question est l'endroit où l'on corrige les noms approximatifs, avec
confirmation de l'utilisateur.
"""

from __future__ import annotations

from collections.abc import Iterable

from rdflib import RDF, Graph, Literal, URIRef
from rdflib.plugins.sparql.algebra import traverse
from rdflib.plugins.sparql.parserutils import CompValue
from rdflib.plugins.sparql.sparql import Query

from .entity_matcher import InstanceIndex
from .triple_direction import Signatures


def resolve_individuals(
    query: Query,
    graph: Graph,
    signatures: Signatures,
    index: InstanceIndex,
    mentioned: Iterable[URIRef] = (),
) -> int:
    """Remplace en place les individus mal désignés ; renvoie leur nombre.

    `mentioned` : IRI d'individus citées dans la question.
    """
    mentioned = list(mentioned)
    fixes = 0

    def replacement(obj, cls: URIRef) -> URIRef | None:
        if isinstance(obj, Literal):
            exact = [m.uri for m in index.search(str(obj), cls) if m.score == 100]
        elif isinstance(obj, URIRef) and (obj, None, None) not in graph:
            exact = [uri for uri in mentioned if (uri, RDF.type, cls) in graph]
        else:
            return None
        return exact[0] if len(set(exact)) == 1 else None

    def fix_triples(node):
        nonlocal fixes
        if not (isinstance(node, CompValue) and node.name == "BGP"):
            return
        triples = []
        for s, p, o in node.triples:
            range_ = signatures.get(p, (None, None))[1]
            if range_ is not None and (uri := replacement(o, range_)) is not None:
                o, fixes = uri, fixes + 1
            triples.append((s, p, o))
        node["triples"] = triples

    traverse(query.algebra, visitPost=fix_triples)
    return fixes
