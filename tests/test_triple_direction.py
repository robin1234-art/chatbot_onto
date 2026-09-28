"""Tests de la correction du sens des triplets SPARQL (sans appel au LLM)."""

import pytest
from rdflib import RDF, XSD, Literal
from rdflib.plugins.sparql.algebra import translateQuery
from rdflib.plugins.sparql.parser import parseQuery

from chatbot.entity_matcher import InstanceIndex
from chatbot.individuals import resolve_individuals
from chatbot.triple_direction import fix_directions, property_signatures
from ontology.namespace import NOBEL, WD
from ontology.nobel.schema import build_schema

PREFIX = (
    "PREFIX nobel: <http://example.org/onto-nobel#>\nPREFIX wd: <http://www.wikidata.org/entity/>\n"
)
PEACE = WD.Q35637


@pytest.fixture(scope="module")
def graph():
    g = build_schema()
    g.add((PEACE, RDF.type, NOBEL.NobelPrize))
    for qid, name, year, advisor in [
        ("Q1", "Nihon Hidankyō", 2024, None),
        ("Q2", "Niels Bohr", 1922, "Q3"),
        ("Q3", "J. J. Thomson", 1906, None),
    ]:
        award = NOBEL[f"award_{qid}"]
        g.add((WD[qid], NOBEL.name, Literal(name)))
        g.add((WD[qid], NOBEL.received, award))
        g.add((award, RDF.type, NOBEL.NobelAward))
        g.add((award, NOBEL.category, PEACE))
        g.add((award, NOBEL.year, Literal(year, datatype=XSD.integer)))
        if advisor:
            g.add((WD[qid], NOBEL.doctoralAdvisor, WD[advisor]))
    return g


def run(graph, body):
    query = translateQuery(parseQuery(PREFIX + body))
    fixes = fix_directions(query, graph, property_signatures(graph))
    return sorted(str(row[0]) for row in graph.query(query)), fixes


def test_inverted_triple_typed_by_rdf_type(graph):
    # Requête réellement générée pour "quel est le prix nobel de la paix 2024 ?"
    body = """SELECT DISTINCT ?nom WHERE {
      ?attribution a nobel:NobelAward .
      ?attribution nobel:category wd:Q35637 .
      ?attribution nobel:year 2024 .
      ?attribution nobel:received ?lauriat .
      ?lauriat nobel:name ?nom . }"""
    assert run(graph, body) == (["Nihon Hidankyō"], 1)


def test_inverted_triple_typed_by_another_property(graph):
    # Sans `a nobel:NobelAward` : le domaine de nobel:category suffit.
    body = "SELECT ?nom WHERE { ?a nobel:category ?c ; nobel:year 2024 ; nobel:received ?l . ?l nobel:name ?nom }"
    assert run(graph, body) == (["Nihon Hidankyō"], 1)


def test_inverted_triple_with_an_individual(graph):
    # wd:Q35637 est un prix Nobel d'après le graphe : il est l'objet de nobel:category.
    body = "SELECT ?y WHERE { wd:Q35637 nobel:category ?a . ?a nobel:year ?y }"
    assert run(graph, body) == (["1906", "1922", "2024"], 1)


def test_triples_in_optional_are_fixed(graph):
    body = """SELECT ?nom WHERE { ?l nobel:name ?nom .
      OPTIONAL { ?a a nobel:NobelAward ; nobel:received ?l } FILTER(BOUND(?a)) }"""
    assert run(graph, body) == (["J. J. Thomson", "Niels Bohr", "Nihon Hidankyō"], 1)


def test_well_oriented_query_is_unchanged(graph):
    body = "SELECT ?nom WHERE { ?l nobel:received ?a ; nobel:name ?nom . ?a a nobel:NobelAward ; nobel:year 2024 }"
    assert run(graph, body) == (["Nihon Hidankyō"], 0)


def test_property_with_same_domain_and_range_is_never_swapped(graph):
    body = "SELECT ?nom WHERE { ?s nobel:doctoralAdvisor ?d . ?d nobel:name ?nom }"
    assert run(graph, body) == (["J. J. Thomson"], 0)


def test_untyped_terms_are_left_as_is(graph):
    body = "SELECT ?nom WHERE { ?x nobel:received ?y . ?y nobel:name ?nom }"
    assert run(graph, body) == ([], 0)


def test_individual_name_is_replaced_by_its_iri(graph):
    g = graph + build_schema()
    g.add((PEACE, NOBEL.name, Literal("prix Nobel de la paix")))
    body = 'SELECT ?nom WHERE { ?a nobel:category "Prix Nobel de la Paix" ; nobel:year 2024 . ?l nobel:received ?a ; nobel:name ?nom }'
    query = translateQuery(parseQuery(PREFIX + body))
    fixes = resolve_individuals(query, g, property_signatures(g), InstanceIndex.from_graph(g))
    assert (sorted(str(r[0]) for r in g.query(query)), fixes) == (["Nihon Hidankyō"], 1)


def test_invented_iri_is_replaced_by_the_mentioned_one(graph):
    body = "SELECT ?nom WHERE { ?a nobel:category nobel:peace ; nobel:year 2024 . ?l nobel:received ?a ; nobel:name ?nom }"
    query = translateQuery(parseQuery(PREFIX + body))
    index = InstanceIndex.from_graph(graph)
    signatures = property_signatures(graph)
    fixes = resolve_individuals(query, graph, signatures, index, [WD.Q1, PEACE])
    assert (sorted(str(r[0]) for r in graph.query(query)), fixes) == (["Nihon Hidankyō"], 1)


def test_invented_iri_without_mention_is_left_as_is(graph):
    body = "SELECT ?a WHERE { ?a nobel:category nobel:peace }"
    query = translateQuery(parseQuery(PREFIX + body))
    fixes = resolve_individuals(
        query, graph, property_signatures(graph), InstanceIndex.from_graph(graph)
    )
    assert (list(graph.query(query)), fixes) == ([], 0)
