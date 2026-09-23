"""Tests de l'index flou des individus (sans appel au LLM)."""
import pytest
from rdflib import Graph, Literal, OWL, RDF, RDFS

from chatbot.entity_matcher import InstanceIndex, normalize
from ontology.instances import build_instances
from ontology.namespace import EX
from ontology.schema import NAME_PREFIXES, build_schema


@pytest.fixture(scope="module")
def index():
    return InstanceIndex.from_graph(build_schema() + build_instances(), NAME_PREFIXES)


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


def test_classes_are_indexed_with_their_label(index):
    assert index.classes[EX.Doctor] == "Médecin"
    assert set(index.classes) == {EX.Doctor, EX.Patient, EX.Disease, EX.Hospital}


@pytest.mark.parametrize(
    "term, expected",
    [
        ("Hopital Saint Louis", EX.HopitalSaintLouis),
        ("Hopital Pitie Salpetriere", EX.HopitalPitieSalpetriere),
        ("Diabete", EX.Diabete),
        ("Chloe", EX.Chloe),
        ("dr martin", EX.DrMartin),
        # Comparaison sans préfixe de classe
        ("saint-louis", EX.HopitalSaintLouis),
        ("l'hopital saint-louis", EX.HopitalSaintLouis),
        ("CHU Saint-Louis", EX.HopitalSaintLouis),
        ("Bernard", EX.DrBernard),
        ("Docteur Martin", EX.DrMartin),
    ],
)
def test_normalized_equivalents_score_100(index, term, expected):
    best = index.search(term)[0]
    assert (best.uri, best.score) == (expected, 100)


def test_search_returns_canonical_label(index):
    assert index.search("docteur bernard")[0].label == "Dr Bernard"


def test_typo_ranks_closest_individual_first(index):
    ranked = index.search("docteur Bornard")
    assert ranked[0].uri == EX.DrBernard
    assert 80 < ranked[0].score < 100
    assert ranked[1].score < 50


def test_search_restricted_to_class(index):
    ranked = index.search("Bornard", EX.Doctor)
    assert {m.uri for m in ranked} == {EX.DrMartin, EX.DrBernard, EX.DrDupont}
    assert ranked[0].uri == EX.DrBernard


def test_one_match_per_individual(index):
    # rdfs:label et ex:name portent le même texte : un seul résultat.
    uris = [m.uri for m in index.search("Asthme")]
    assert len(uris) == len(set(uris))


def test_individual_without_label_uses_local_name():
    g = Graph()
    g.add((EX.Hospital, RDF.type, OWL.Class))
    g.add((EX.H1, RDF.type, EX.Hospital))
    g.add((EX.H1, EX.name, Literal("Hôpital Necker")))
    assert InstanceIndex.from_graph(g).search("Necker")[0].label == "H1"
