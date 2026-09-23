"""Tests du fuzzy matching des labels d'instance (sans appel au LLM)."""
import pytest
from rdflib import Graph, Literal, OWL, RDF, RDFS

from chatbot.entity_matcher import InstanceIndex, correct_instance_literals, normalize
from ontology.instances import build_instances
from ontology.schema import NAME_PREFIXES, build_schema
from ontology.namespace import EX

THRESHOLD = 90

PREFIXES = """PREFIX ex: <http://example.org/onto-medical#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
"""

DOCTORS_AT_SAINT_LOUIS = {EX.DrMartin, EX.DrDupont}


@pytest.fixture(scope="module")
def graph():
    return build_schema() + build_instances()


@pytest.fixture(scope="module")
def index(graph):
    return InstanceIndex.from_graph(graph, NAME_PREFIXES)


def correct(query, index):
    return correct_instance_literals(PREFIXES + query, index, THRESHOLD)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Hôpital Saint-Louis", "hopital saint louis"),
        ("l'hopital saint louis", "l hopital saint louis"),
        ("  HOPITAL   Saint Louis ", "hopital saint louis"),
        ("Diabète", "diabete"),
        ("Pitié-Salpêtrière", "pitie salpetriere"),
    ],
)
def test_normalize(raw, expected):
    assert normalize(raw) == expected


@pytest.mark.parametrize(
    "term, expected",
    [
        ("Hopital Saint Louis", "Hôpital Saint-Louis"),
        ("hopital saint-loui", "Hôpital Saint-Louis"),
        ("Hopital Pitie Salpetriere", "Hôpital Pitié-Salpêtrière"),
        ("Diabete", "Diabète"),
        ("Chloe", "Chloé"),
        ("dr martin", "Dr Martin"),
        # Comparaison sans préfixe de classe
        ("saint-louis", "Hôpital Saint-Louis"),
        ("Saint Louis", "Hôpital Saint-Louis"),
        ("l'hopital saint-louis", "Hôpital Saint-Louis"),
        ("CHU Saint-Louis", "Hôpital Saint-Louis"),
        ("Pitie Salpetriere", "Hôpital Pitié-Salpêtrière"),
        ("Bernard", "Dr Bernard"),
        ("Docteur Martin", "Dr Martin"),
    ],
)
def test_match_accepts_close_labels(index, term, expected):
    match = index.match(term, RDFS.label, THRESHOLD)
    assert match is not None
    assert match.literal == Literal(expected, lang="fr")


@pytest.mark.parametrize(
    "term", ["Saint", "Louis", "Hôpital", "Dr", "Dr Durand", "Durand", "Grippe"]
)
def test_match_rejects_distant_or_partial_labels(index, term):
    assert index.match(term, RDFS.label, THRESHOLD) is None


def test_same_stripped_name_in_two_individuals_is_ambiguous():
    g = Graph()
    g.add((EX.Hospital, RDF.type, OWL.Class))
    for uri, label in [(EX.H1, "Hôpital Saint-Louis"), (EX.H2, "CHU Saint-Louis")]:
        g.add((uri, RDF.type, EX.Hospital))
        g.add((uri, RDFS.label, Literal(label, lang="fr")))
    index = InstanceIndex.from_graph(g, NAME_PREFIXES)
    assert index.match("Saint-Louis", RDFS.label, THRESHOLD) is None
    assert index.match("CHU Saint Louis", RDFS.label, THRESHOLD).literal == Literal(
        "CHU Saint-Louis", lang="fr"
    )


def test_triple_object_on_label_gets_lang_tag(index):
    q = correct('SELECT ?h WHERE { ?h rdfs:label "Hopital Saint Louis" . }', index)
    assert '"Hôpital Saint-Louis"@fr' in q


def test_triple_object_on_name_stays_plain(index):
    q = correct('SELECT ?h WHERE { ?h ex:name "Hopital Saint Louis"@fr . }', index)
    assert 'ex:name "Hôpital Saint-Louis" .' in q


def test_filter_equality_uses_predicate_of_variable(index):
    q = correct(
        'SELECT ?h WHERE { ?h rdfs:label ?l . FILTER(?l = "hopital saint louis") }', index
    )
    assert 'FILTER(?l = "Hôpital Saint-Louis"@fr)' in q


def test_filter_str_equality_stays_plain(index):
    q = correct(
        'SELECT ?h WHERE { ?h rdfs:label ?l . FILTER(STR(?l) = "hopital saint louis") }', index
    )
    assert 'FILTER(STR(?l) = "Hôpital Saint-Louis")' in q


def test_filter_equality_literal_on_left(index):
    q = correct('SELECT ?h WHERE { ?h ex:name ?n . FILTER("Diabete" = ?n) }', index)
    assert 'FILTER("Diabète" = ?n)' in q


@pytest.mark.parametrize(
    "clause",
    [
        'FILTER(CONTAINS(?l, "saint louis"))',
        'FILTER(REGEX(?l, "hopital saint louis", "i"))',
        'FILTER(LCASE(?l) = "hopital saint louis")',
        'FILTER(LCASE(STR(?l)) = "hopital saint louis")',
    ],
)
def test_function_arguments_are_left_untouched(index, clause):
    query = f"SELECT ?h WHERE {{ ?h rdfs:label ?l . {clause} }}"
    assert correct(query, index) == PREFIXES + query


def test_unknown_predicate_is_left_untouched(index):
    query = 'SELECT ?h WHERE { ?h ex:nom "Hopital Saint Louis" . }'
    assert correct(query, index) == PREFIXES + query


@pytest.mark.parametrize(
    "where",
    [
        '?h rdfs:label "Hopital Saint Louis" .',
        '?h ex:name "hopital saint-louis"@fr .',
        '?h ex:name "saint-louis" .',
        '?h rdfs:label ?l . FILTER(?l = "Hopital Saint Louis")',
    ],
)
def test_corrected_query_returns_results(graph, index, where):
    query = f"""SELECT ?d WHERE {{
        {where}
        ?d ex:worksAt ?h .
    }}"""
    assert not set(graph.query(PREFIXES + query))  # sans correction : vide
    rows = graph.query(correct(query, index))
    assert {row.d for row in rows} == DOCTORS_AT_SAINT_LOUIS
