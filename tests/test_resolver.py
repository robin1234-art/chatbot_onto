"""Tests de l'index flou et de la résolution d'entités (LLM simulé)."""

import json
from types import SimpleNamespace

import pytest
from rdflib import RDF, RDFS, Literal

from chatbot.entity_matcher import InstanceIndex
from chatbot.resolver import Mention, QuestionResolver, Status, extract_mentions, resolve
from ontology.instances import build_instances
from ontology.namespace import EX
from ontology.schema import build_schema

THRESHOLD = 75


class FakeLLM:
    """Renvoie une réponse fixe et garde le dernier prompt reçu."""

    def __init__(self, response):
        self.response = response if isinstance(response, str) else json.dumps(response)
        self.prompt = None

    def invoke(self, prompt):
        self.prompt = prompt
        return SimpleNamespace(content=self.response)


def mentions(*items):
    return {"mentions": [{"text": t, "class": c} for t, c in items]}


@pytest.fixture(scope="module")
def index():
    return InstanceIndex.from_graph(build_schema() + build_instances())


# --- index flou ------------------------------------------------------------


@pytest.mark.parametrize(
    ("term", "expected"),
    [
        ("Hopital Pitie Salpetriere", EX.HopitalPitieSalpetriere),  # accents, casse
        ("saint-louis", EX.HopitalSaintLouis),  # sans préfixe de classe
        ("l'hopital saint-louis", EX.HopitalSaintLouis),  # article
        ("Docteur Martin", EX.DrMartin),  # autre préfixe de la classe
    ],
)
def test_normalized_equivalents_score_100(index, term, expected):
    best = index.search(term)[0]
    assert (best.uri, best.score) == (expected, 100)


def test_only_name_literals_are_indexed():
    graph = build_schema() + build_instances()
    graph.add((EX.HopitalSaintLouis, RDFS.comment, Literal("Pédiatrie")))
    assert InstanceIndex.from_graph(graph).search("Pédiatrie")[0].score < 100


# --- extraction ------------------------------------------------------------


def test_extract_maps_class_names_to_uris(index):
    response = json.dumps(mentions(("docteur Bornard", "Doctor"), ("Saint-Louis", "Inconnue")))
    llm = FakeLLM(f"```json\n{response}\n```")
    found = extract_mentions("Le docteur Bornard travaille-t-il à Saint-Louis ?", llm, index)
    assert found == [Mention("docteur Bornard", EX.Doctor), Mention("Saint-Louis", None)]
    assert "- Doctor : Médecin" in llm.prompt


@pytest.mark.parametrize("response", ["pas du JSON", '{"autre": 1}'])
def test_extract_ignores_unreadable_response(index, response):
    assert extract_mentions("Qui soigne Bob ?", FakeLLM(response), index) == []


def test_extract_ignores_mention_absent_from_question(index):
    # Le LLM a corrigé l'orthographe au lieu de recopier : non substituable.
    llm = FakeLLM(mentions(("docteur Bernard", "Doctor")))
    assert extract_mentions("Qui est le docteur Bornard ?", llm, index) == []


@pytest.mark.parametrize("text", ["Asthme 2024", "en 2024 Asthme"])
def test_extract_drops_year_next_to_a_mention(index, text):
    llm = FakeLLM(mentions((text, "Disease")))
    assert extract_mentions(f"Qui soigne {text} ?", llm, index) == [Mention("Asthme", EX.Disease)]


# --- résolution ------------------------------------------------------------


@pytest.mark.parametrize(
    ("mention", "status", "expected"),
    [
        (Mention("diabète", EX.Disease), Status.EXACT, {EX.Diabete}),
        (Mention("docteur Bornard", EX.Doctor), Status.SUGGESTION, {EX.DrBernard}),
        # Classe devinée fausse : recherche élargie à toute l'ontologie.
        (Mention("Bornard", EX.Patient), Status.SUGGESTION, {EX.DrBernard}),
        # Rien de proche : individus de la classe.
        (
            Mention("docteur Lefèvre", EX.Doctor),
            Status.NOT_FOUND,
            {EX.DrMartin, EX.DrBernard, EX.DrDupont},
        ),
    ],
)
def test_resolve(index, mention, status, expected):
    r = resolve(mention, index, THRESHOLD)
    assert (r.status, {m.uri for m in r.candidates}) == (status, expected)


def test_exact_homonyms_of_other_classes_are_candidates():
    # "Martin" : le Dr Martin, mais aussi un hôpital Martin exactement homonyme.
    graph = build_schema() + build_instances()
    graph.add((EX.HopitalMartin, RDF.type, EX.Hospital))
    graph.add((EX.HopitalMartin, RDFS.label, Literal("Hôpital Martin", lang="fr")))
    r = resolve(Mention("Martin", EX.Doctor), InstanceIndex.from_graph(graph), THRESHOLD)
    assert r.status is Status.AMBIGUOUS
    assert {m.uri for m in r.candidates} == {EX.DrMartin, EX.HopitalMartin}


# --- flux complet ----------------------------------------------------------


def test_exact_match_is_rewritten_without_asking(index):
    resolver = QuestionResolver(FakeLLM(mentions(("diabète", "Disease"))), index, THRESHOLD)

    def choose(_):
        raise AssertionError("aucune confirmation attendue")

    q = resolver.reformulate("Quels patients ont du diabète ?", choose)
    assert q == f'Quels patients ont du diabète ("Diabète" <{EX.Diabete}>) ?'


def test_rejected_suggestion_keeps_user_wording(index):
    resolver = QuestionResolver(FakeLLM(mentions(("docteur Bornard", "Doctor"))), index, THRESHOLD)
    q = resolver.reformulate("Que peux-tu me dire du docteur Bornard ?", lambda _: None)
    assert q == "Que peux-tu me dire du docteur Bornard ?"
