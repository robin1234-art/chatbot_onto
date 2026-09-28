"""Corrections des requêtes SPARQL générées, via CleanRdfGraph.query (sans appel au LLM)."""

import pytest
from rdflib import RDF, XSD, Literal

from chatbot.rdf_graph import CleanRdfGraph
from ontology.namespace import NOBEL, WD
from ontology.nobel.schema import build_schema

PEACE = WD.Q35637


@pytest.fixture(scope="module")
def graph(tmp_path_factory):
    """Trois lauréats du prix Nobel de la paix (données simplifiées)."""
    g = build_schema()
    g.bind("wd", WD)
    g.add((PEACE, RDF.type, NOBEL.NobelPrize))
    g.add((PEACE, NOBEL.name, Literal("prix Nobel de la paix")))
    for qid, name, year, born, advisor in [
        ("Q1", "Nihon Hidankyō", 2024, None, None),
        ("Q2", "Albert Camus", 1957, "1913-11-07", "Q3"),
        ("Q3", "Anatole France", 1921, "1844-04-16", None),
    ]:
        award = NOBEL[f"award_{qid}"]
        g.add((WD[qid], NOBEL.name, Literal(name)))
        g.add((WD[qid], NOBEL.received, award))
        g.add((award, RDF.type, NOBEL.NobelAward))
        g.add((award, NOBEL.category, PEACE))
        g.add((award, NOBEL.year, Literal(year, datatype=XSD.integer)))
        if born:
            g.add((WD[qid], NOBEL.birthDate, Literal(born, datatype=XSD.date)))
        if advisor:
            g.add((WD[qid], NOBEL.doctoralAdvisor, WD[advisor]))
    path = tmp_path_factory.mktemp("onto") / "nobel.ttl"
    g.serialize(destination=path, format="turtle")
    return CleanRdfGraph(source_file=str(path), standard="owl", serialization="ttl")


def names(graph, query, mentioned=()):
    graph.mentioned = list(mentioned)
    return sorted(str(row[0]) for row in graph.query(query))


def test_code_fence_and_duplicate_prefixes(graph):
    # Requête réellement générée pour "Qui a gagné le prix Nobel de la paix en 2024 ?"
    query = """```sparql
PREFIX ex: <http://example.org/onto-nobel#>
PREFIX nobel: <http://example.org/onto-nobel#>

SELECT DISTINCT ?personName WHERE {
    ?award a nobel:NobelAward ; ex:year 2024 .
    ?person nobel:received ?award .
    ?person ex:name ?personName .
}
```"""
    assert names(graph, query) == ["Nihon Hidankyō"]


def test_inverted_triple_is_swapped(graph):
    # Requête réellement générée pour "quel est le prix nobel de la paix 2024 ?"
    query = """SELECT DISTINCT ?nom WHERE {
      ?attribution a nobel:NobelAward ; nobel:category wd:Q35637 ; nobel:year 2024 .
      ?attribution nobel:received ?lauriat .
      ?lauriat nobel:name ?nom . }"""
    assert names(graph, query) == ["Nihon Hidankyō"]


def test_property_with_same_domain_and_range_is_never_swapped(graph):
    query = "SELECT ?nom WHERE { ?s nobel:doctoralAdvisor ?d . ?d nobel:name ?nom }"
    assert names(graph, query) == ["Anatole France"]


def test_individual_name_is_replaced_by_its_iri(graph):
    query = """SELECT ?nom WHERE { ?a nobel:category "Prix Nobel de la Paix" ; nobel:year 2024 .
      ?l nobel:received ?a ; nobel:name ?nom }"""
    assert names(graph, query) == ["Nihon Hidankyō"]


@pytest.mark.parametrize(
    ("mentioned", "expected"), [([WD.Q1, PEACE], ["Nihon Hidankyō"]), ([], [])]
)
def test_invented_iri_is_replaced_by_the_mentioned_one(graph, mentioned, expected):
    query = """SELECT ?nom WHERE { ?a nobel:category nobel:peace ; nobel:year 2024 .
      ?l nobel:received ?a ; nobel:name ?nom }"""
    assert names(graph, query, mentioned) == expected


@pytest.mark.parametrize(
    ("clause", "expected"),
    [
        ('?a nobel:year "2024"', ["Nihon Hidankyō"]),
        ('?a nobel:year "2024-10-11"', ["Nihon Hidankyō"]),
        ('?a nobel:year ?y FILTER("2000" < ?y)', ["Nihon Hidankyō"]),
        ('?a nobel:year "années 50"', []),  # non convertible : laissé tel quel
    ],
)
def test_quoted_numbers_are_coerced(graph, clause, expected):
    query = f"SELECT ?n WHERE {{ ?p nobel:received ?a ; nobel:name ?n . {clause} }}"
    assert names(graph, query) == expected


@pytest.mark.parametrize(
    ("clause", "expected"),
    [
        ('?p nobel:birthDate ?b FILTER(YEAR(?b) = "1913")', ["Albert Camus"]),
        ('?p nobel:birthDate ?b FILTER(?b = "1913")', ["Albert Camus"]),
        ('?p nobel:birthDate ?b FILTER(?b != "1913")', ["Anatole France"]),
        ('?p nobel:birthDate ?b FILTER("1900" < ?b)', ["Albert Camus"]),
        # Filtre typé par un triplet écrit après lui.
        ('FILTER(?b < "1900-01-01") ?p nobel:birthDate ?b', ["Anatole France"]),
        ('?p nobel:birthDate "1913"', ["Albert Camus"]),
        ('?p nobel:birthDate "07/11/1913"', ["Albert Camus"]),
    ],
)
def test_dates_are_coerced(graph, clause, expected):
    query = f"SELECT ?n WHERE {{ ?p nobel:name ?n . {clause} }}"
    assert names(graph, query) == expected
