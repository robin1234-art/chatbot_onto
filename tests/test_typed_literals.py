"""Tests de la correction des types des littéraux SPARQL (sans appel au LLM)."""

import pytest
from rdflib import RDF, XSD, Literal
from rdflib.plugins.sparql.algebra import translateQuery
from rdflib.plugins.sparql.parser import parseQuery

from chatbot.typed_literals import coerce_literals, datatype_ranges, parse_period
from ontology.namespace import NOBEL, WD
from ontology.nobel.schema import build_schema

PREFIX = "PREFIX nobel: <http://example.org/onto-nobel#>\nPREFIX xsd: <http://www.w3.org/2001/XMLSchema#>\n"


@pytest.fixture(scope="module")
def graph():
    g = build_schema()
    for qid, name, year, born in [
        ("Q1", "Nihon Hidankyō", 2024, None),
        ("Q2", "Albert Camus", 1957, "1913-11-07"),
        ("Q3", "Anatole France", 1921, "1844-04-16"),
    ]:
        award = NOBEL[f"award_{qid}"]
        g.add((WD[qid], NOBEL.name, Literal(name)))
        g.add((WD[qid], NOBEL.received, award))
        g.add((award, RDF.type, NOBEL.NobelAward))
        g.add((award, NOBEL.year, Literal(year, datatype=XSD.integer)))
        if born:
            g.add((WD[qid], NOBEL.birthDate, Literal(born, datatype=XSD.date)))
    return g


def run(graph, body):
    query = translateQuery(parseQuery(PREFIX + body))
    fixes = coerce_literals(query, datatype_ranges(graph))
    return sorted(str(row[0]) for row in graph.query(query)), fixes


def test_ranges_come_from_the_schema(graph):
    ranges = datatype_ranges(graph)
    assert ranges[NOBEL.year] == XSD.integer
    assert ranges[NOBEL.birthDate] == XSD.date
    assert NOBEL.name not in ranges  # chaîne : rien à convertir


def test_quoted_year_in_triple_is_coerced(graph):
    # Requête réellement générée pour "Qui a gagné le prix Nobel de la paix en 2024 ?"
    body = 'SELECT ?n WHERE { ?a nobel:year "2024" . ?p nobel:received ?a ; nobel:name ?n }'
    assert run(graph, body) == (["Nihon Hidankyō"], 1)


@pytest.mark.parametrize("comparison", ['?y > "1950"', '"1950" < ?y'])
def test_quoted_number_in_filter_is_coerced(graph, comparison):
    body = f"SELECT ?n WHERE {{ ?p nobel:received ?a ; nobel:name ?n . ?a nobel:year ?y . FILTER({comparison}) }}"
    assert run(graph, body) == (["Albert Camus", "Nihon Hidankyō"], 1)


def test_filter_typed_by_a_triple_written_after_it(graph):
    body = 'SELECT ?n WHERE { FILTER(?b < "1900-01-01") ?p nobel:birthDate ?b ; nobel:name ?n }'
    assert run(graph, body) == (["Anatole France"], 1)


def test_nested_filters_are_coerced(graph):
    body = (
        "SELECT ?n WHERE { ?p nobel:received ?a ; nobel:name ?n ; nobel:birthDate ?b ."
        ' ?a nobel:year ?y . FILTER(?y > "1950" && ?b < "1920-01-01") }'
    )
    assert run(graph, body) == (["Albert Camus"], 2)


def test_well_typed_query_is_unchanged(graph):
    body = "SELECT ?n WHERE { ?a nobel:year 2024 . ?p nobel:received ?a ; nobel:name ?n }"
    assert run(graph, body) == (["Nihon Hidankyō"], 0)


@pytest.mark.parametrize("value", ['"années 50"', '"2024"@fr'])
def test_unconvertible_literal_is_left_as_is(graph, value):
    body = f"SELECT ?n WHERE {{ ?a nobel:year {value} . ?p nobel:received ?a ; nobel:name ?n }}"
    assert run(graph, body) == ([], 0)


def test_string_properties_are_not_touched(graph):
    body = 'SELECT ?p WHERE { ?p nobel:name "2024" }'
    assert run(graph, body) == ([], 0)


@pytest.mark.parametrize(
    ("text", "period"),
    [
        ("1951", ("1951-01-01", "1952-01-01")),
        ("1951-09", ("1951-09-01", "1951-10-01")),
        ("1951-12", ("1951-12-01", "1952-01-01")),
        ("1951-09-14", ("1951-09-14", "1951-09-15")),
        ("1951-09-14T00:00:00Z", ("1951-09-14", "1951-09-15")),
        ("14/09/1951", ("1951-09-14", "1951-09-15")),
        ("09/1951", ("1951-09-01", "1951-10-01")),
    ],
)
def test_parse_period(text, period):
    start, end = parse_period(text)
    assert (start.isoformat(), end.isoformat()) == period


@pytest.mark.parametrize("text", ["années 50", "1951-13", "30/02/1951", "Camus"])
def test_parse_period_rejects_non_dates(text):
    assert parse_period(text) is None


@pytest.mark.parametrize("comparison", ['YEAR(?b) = "1913"', '"1913" = YEAR(?b)'])
def test_quoted_number_compared_to_a_function_is_coerced(graph, comparison):
    body = f"SELECT ?n WHERE {{ ?p nobel:birthDate ?b ; nobel:name ?n . FILTER({comparison}) }}"
    assert run(graph, body) == (["Albert Camus"], 1)


@pytest.mark.parametrize(
    ("comparison", "names"),
    [
        ('?b = "1913"', ["Albert Camus"]),
        ('?b != "1913"', ["Anatole France"]),
        ('?b < "1913"', ["Anatole France"]),
        ('?b <= "1913"', ["Albert Camus", "Anatole France"]),
        ('?b > "1844"', ["Albert Camus"]),
        ('?b >= "1844-04"', ["Albert Camus", "Anatole France"]),
        ('"1900" < ?b', ["Albert Camus"]),
        ('?b = "1913"^^xsd:gYear', ["Albert Camus"]),
    ],
)
def test_partial_date_in_filter_becomes_a_period(graph, comparison, names):
    body = f"SELECT ?n WHERE {{ ?p nobel:birthDate ?b ; nobel:name ?n . FILTER({comparison}) }}"
    assert run(graph, body) == (names, 1)


@pytest.mark.parametrize("value", ['"1913"', '"1913-11"', '"1913"^^xsd:gYear'])
def test_partial_date_in_triple_becomes_a_period(graph, value):
    body = f"SELECT ?n WHERE {{ ?p nobel:birthDate {value} ; nobel:name ?n }}"
    assert run(graph, body) == (["Albert Camus"], 1)


def test_partial_date_in_optional_triple(graph):
    body = 'SELECT ?n ?b WHERE { ?p nobel:name ?n . OPTIONAL { ?p nobel:birthDate "1913" . BIND(1 AS ?b) } FILTER(BOUND(?b)) }'
    assert run(graph, body) == (["Albert Camus"], 1)


@pytest.mark.parametrize("value", ['"1913-11-07T00:00:00Z"', '"07/11/1913"'])
def test_full_date_written_otherwise_is_coerced(graph, value):
    body = f"SELECT ?n WHERE {{ ?p nobel:birthDate {value} ; nobel:name ?n }}"
    assert run(graph, body) == (["Albert Camus"], 1)


def test_full_date_for_a_year_keeps_the_year(graph):
    body = 'SELECT ?n WHERE { ?a nobel:year "2024-10-11" . ?p nobel:received ?a ; nobel:name ?n }'
    assert run(graph, body) == (["Nihon Hidankyō"], 1)


def test_unconvertible_literal_logs_nothing(graph, caplog):
    run(graph, 'SELECT ?n WHERE { ?a nobel:motivation ?m . ?a nobel:year "années 50" }')
    assert not caplog.records
