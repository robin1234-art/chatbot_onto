"""Tests de la résolution d'entités en amont de la chaîne SPARQL (LLM simulé)."""

import json
from types import SimpleNamespace

import pytest
from rdflib import RDF, RDFS, Literal

from chatbot.entity_matcher import InstanceIndex
from chatbot.resolver import (
    Mention,
    QuestionResolver,
    Status,
    extract_mentions,
    resolve,
    rewrite,
)
from ontology.instances import build_instances
from ontology.namespace import EX
from ontology.schema import NAME_PREFIXES, build_schema

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
    return InstanceIndex.from_graph(build_schema() + build_instances(), NAME_PREFIXES)


# --- extraction ------------------------------------------------------------


def test_extract_maps_class_names_to_uris(index):
    llm = FakeLLM(mentions(("docteur Bornard", "Doctor"), ("Saint-Louis", "Inconnue")))
    found = extract_mentions(
        "Le docteur Bornard travaille-t-il à Saint-Louis ?", llm, index.classes
    )
    assert found == [Mention("docteur Bornard", EX.Doctor), Mention("Saint-Louis", None)]
    assert "- Doctor : Médecin" in llm.prompt


def test_extract_accepts_code_fenced_json(index):
    llm = FakeLLM("```json\n" + json.dumps(mentions(("Bob", "Patient"))) + "\n```")
    assert extract_mentions("Qui soigne Bob ?", llm, index.classes) == [Mention("Bob", EX.Patient)]


@pytest.mark.parametrize("response", ["pas du JSON", "[]", '{"autre": 1}'])
def test_extract_ignores_unreadable_response(index, response):
    assert extract_mentions("Qui soigne Bob ?", FakeLLM(response), index.classes) == []


def test_extract_ignores_mention_absent_from_question(index):
    # Le LLM a corrigé l'orthographe au lieu de recopier : non substituable.
    llm = FakeLLM(mentions(("docteur Bernard", "Doctor")))
    assert extract_mentions("Qui est le docteur Bornard ?", llm, index.classes) == []


# --- résolution ------------------------------------------------------------


def test_normalized_equivalent_is_exact(index):
    r = resolve(Mention("diabète", EX.Disease), index, THRESHOLD)
    assert r.status is Status.EXACT
    assert r.candidates[0].label == "Diabète"


def test_typo_is_a_suggestion(index):
    r = resolve(Mention("docteur Bornard", EX.Doctor), index, THRESHOLD)
    assert r.status is Status.SUGGESTION
    assert [m.label for m in r.candidates] == ["Dr Bernard"]


def test_wrong_class_hint_falls_back_to_whole_ontology(index):
    r = resolve(Mention("Bornard", EX.Patient), index, THRESHOLD)
    assert r.status is Status.SUGGESTION
    assert r.candidates[0].uri == EX.DrBernard


def test_unknown_name_lists_individuals_of_the_class(index):
    r = resolve(Mention("docteur Lefèvre", EX.Doctor), index, THRESHOLD)
    assert r.status is Status.NOT_FOUND
    assert {m.uri for m in r.candidates} == {EX.DrMartin, EX.DrBernard, EX.DrDupont}


def test_unknown_name_without_class_has_no_candidates(index):
    r = resolve(Mention("Lefèvre", None), index, THRESHOLD)
    assert (r.status, r.candidates) == (Status.NOT_FOUND, ())


def test_close_candidates_are_ambiguous():
    # "Dr Marton" est à égale distance de "Dr Martin" et d'un "Dr Marten" ajouté.
    graph = build_schema() + build_instances()
    graph.add((EX.DrMarten, RDF.type, EX.Doctor))
    graph.add((EX.DrMarten, RDFS.label, Literal("Dr Marten", lang="fr")))
    idx = InstanceIndex.from_graph(graph, NAME_PREFIXES)
    r = resolve(Mention("Dr Marton", EX.Doctor), idx, THRESHOLD)
    assert r.status is Status.AMBIGUOUS
    assert {m.label for m in r.candidates} == {"Dr Martin", "Dr Marten"}


# --- réécriture ------------------------------------------------------------


def test_rewrite_quotes_canonical_label():
    q = rewrite(
        "Que sais-tu du Docteur Bornard ?", [(Mention("docteur Bornard", None), "Dr Bernard")]
    )
    assert q == 'Que sais-tu du "Dr Bernard" ?'


def test_rewrite_does_not_double_quotes():
    q = rewrite('Qui soigne "bob" ?', [(Mention("bob", None), "Bob")])
    assert q == 'Qui soigne "Bob" ?'


# --- flow complet ----------------------------------------------------------


def resolver_for(index, response):
    return QuestionResolver(FakeLLM(response), index, THRESHOLD)


def test_exact_match_is_rewritten_without_asking(index):
    resolver = resolver_for(index, mentions(("diabète", "Disease")))

    def choose(_):
        raise AssertionError("aucune confirmation attendue")

    q = resolver.reformulate("Quels patients ont du diabète ?", choose)
    assert q == 'Quels patients ont du "Diabète" ?'


def test_accepted_suggestion_is_rewritten(index):
    resolver = resolver_for(index, mentions(("docteur Bornard", "Doctor")))
    asked = []

    def choose(resolution):
        asked.append(resolution)
        return resolution.candidates[0].label

    q = resolver.reformulate("Que peux-tu me dire du docteur Bornard ?", choose)
    assert q == 'Que peux-tu me dire du "Dr Bernard" ?'
    assert asked[0].status is Status.SUGGESTION


def test_rejected_suggestion_keeps_user_wording(index):
    resolver = resolver_for(index, mentions(("docteur Bornard", "Doctor")))
    q = resolver.reformulate("Que peux-tu me dire du docteur Bornard ?", lambda _: None)
    assert q == "Que peux-tu me dire du docteur Bornard ?"


def test_question_about_classes_is_unchanged(index):
    resolver = resolver_for(index, mentions())
    q = resolver.reformulate("Quels médecins travaillent à l'hôpital ?", lambda _: None)
    assert q == "Quels médecins travaillent à l'hôpital ?"
