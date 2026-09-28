"""Correction du sens des triplets d'une requête SPARQL générée.

Le LLM inverse parfois sujet et objet d'une propriété d'objet, malgré la
description « A -> B » du schéma : `?attribution nobel:received ?laureat`
au lieu de `?laureat nobel:received ?attribution`. La requête s'exécute sans
erreur et ne renvoie rien.

La requête est corrigée de façon déterministe, d'après le schéma : le domaine
(`rdfs:domain`) et la portée (`rdfs:range`) de chaque propriété d'objet disent
quelle classe attendre de chaque côté du triplet. Les classes des termes de la
requête sont déduites :

- des typages explicites (`?a a nobel:NobelAward`) ;
- du domaine et de la portée des autres triplets où le terme apparaît
  (`?a nobel:category ?c` : ?a est une attribution) ;
- du graphe, pour les IRI d'individus (`wd:Q35637` est un prix Nobel).

Un triplet est inversé quand ses termes sont plus souvent à la place l'un de
l'autre qu'à la leur : sujet de la classe de la portée, objet de la classe du
domaine. Chaque triplet est jugé sans tenir compte de lui-même, sinon il se
justifierait tout seul ; une propriété dont domaine et portée coïncident
(`nobel:doctoralAdvisor`) n'est jamais inversée.
"""

from __future__ import annotations

from collections import defaultdict

from rdflib import OWL, RDF, RDFS, Graph, URIRef
from rdflib.plugins.sparql.algebra import traverse
from rdflib.plugins.sparql.parserutils import CompValue
from rdflib.plugins.sparql.sparql import Query

# Propriété -> (domaine, portée), None si non déclaré.
Signatures = dict[URIRef, tuple[URIRef | None, URIRef | None]]


def _single(graph: Graph, prop: URIRef, pred: URIRef) -> URIRef | None:
    value = graph.value(prop, pred)
    return value if isinstance(value, URIRef) else None


def property_signatures(graph: Graph) -> Signatures:
    """Domaine et portée des propriétés du schéma (hors types XSD)."""
    signatures = {}
    for kind in (OWL.ObjectProperty, OWL.DatatypeProperty):
        for prop in graph.subjects(RDF.type, kind):
            if isinstance(prop, URIRef):
                range_ = _single(graph, prop, RDFS.range) if kind == OWL.ObjectProperty else None
                signatures[prop] = (_single(graph, prop, RDFS.domain), range_)
    return signatures


def fix_directions(query: Query, graph: Graph, signatures: Signatures) -> int:
    """Inverse en place les triplets écrits à l'envers ; renvoie leur nombre."""
    bgps: list[CompValue] = []

    def collect(node):
        if isinstance(node, CompValue) and node.name == "BGP":
            bgps.append(node)

    traverse(query.algebra, visitPost=collect)
    triples = [(bgp, i, t) for bgp in bgps for i, t in enumerate(bgp.triples)]

    # Terme -> classes attestées, avec l'identifiant du triplet qui l'atteste
    # (None pour le graphe) : un triplet ne compte pas pour lui-même.
    evidence: dict[object, list[tuple[int | None, URIRef]]] = defaultdict(list)
    for n, (_, _, (s, p, o)) in enumerate(triples):
        if p == RDF.type and isinstance(o, URIRef):
            evidence[s].append((n, o))
        elif p in signatures:
            domain, range_ = signatures[p]
            if domain is not None:
                evidence[s].append((n, domain))
            if range_ is not None:
                evidence[o].append((n, range_))

    def classes(term, excluded: int) -> set[URIRef]:
        found = {cls for n, cls in evidence.get(term, ()) if n != excluded}
        if isinstance(term, URIRef):
            found.update(c for c in graph.objects(term, RDF.type) if isinstance(c, URIRef))
        return found

    fixes = 0
    for n, (bgp, i, (s, p, o)) in enumerate(triples):
        domain, range_ = signatures.get(p, (None, None))
        if range_ is None or domain == range_:
            continue
        subject_classes, object_classes = classes(s, n), classes(o, n)
        in_place = (domain in subject_classes) + (range_ in object_classes)
        swapped = (range_ in subject_classes) + (domain is not None and domain in object_classes)
        if swapped > in_place:
            bgp.triples[i] = (o, p, s)
            fixes += 1
    return fixes
