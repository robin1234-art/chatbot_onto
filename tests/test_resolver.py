"""Tests de l'index flou et de la résolution d'entités (LLM simulé)."""

import json
from types import SimpleNamespace

import pytest
from conftest import (
    CAMBRIDGE_MA,
    CAMBRIDGE_UK,
    CAMBRIDGE_UNIV,
    CAMUS,
    CURIE,
    FEYNMAN,
    FRANCE,
    LITERATURE,
    PEACE,
    PHYSICS,
)

from chatbot.entity_matcher import InstanceIndex
from chatbot.resolver import Mention, QuestionResolver, Status, extract_mentions, resolve
from ontology.namespace import NOBEL

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
def index(nobel_graph):
    return InstanceIndex.from_graph(nobel_graph)


# --- index flou ------------------------------------------------------------


@pytest.mark.parametrize(
    ("term", "expected"),
    [
        ("MARIE CURIE", CURIE),  # casse
        ("Nobel de litterature", LITERATURE),  # accents, autre préfixe de la classe
        ("le prix Nobel de physique", PHYSICS),  # article
    ],
)
def test_normalized_equivalents_score_100(index, term, expected):
    best = index.search(term)[0]
    assert (best.uri, best.score) == (expected, 100)


def test_only_name_literals_are_indexed(index):
    # "physicien américain" est la description de Richard Feynman, pas un nom.
    assert index.search("physicien américain")[0].score < 100


# --- extraction ------------------------------------------------------------


def test_extract_maps_class_names_to_uris(index):
    response = json.dumps(mentions(("Richard Feynmann", "Person"), ("Cambridge", "Inconnue")))
    llm = FakeLLM(f"```json\n{response}\n```")
    found = extract_mentions("Richard Feynmann a-t-il étudié à Cambridge ?", llm, index)
    assert found == [Mention("Richard Feynmann", NOBEL.Person), Mention("Cambridge", None)]
    assert "- Person : Personne" in llm.prompt


@pytest.mark.parametrize("response", ["pas du JSON", '{"autre": 1}'])
def test_extract_ignores_unreadable_response(index, response):
    assert extract_mentions("Qui a formé Marie Curie ?", FakeLLM(response), index) == []


def test_extract_ignores_mention_absent_from_question(index):
    # Le LLM a corrigé l'orthographe au lieu de recopier : non substituable.
    llm = FakeLLM(mentions(("Richard Feynman", "Person")))
    assert extract_mentions("Qui a formé Richard Feinman ?", llm, index) == []


@pytest.mark.parametrize("text", ["prix Nobel de la paix 2024", "en 2024 prix Nobel de la paix"])
def test_extract_drops_year_next_to_a_mention(index, text):
    llm = FakeLLM(mentions((text, "NobelPrize")))
    found = extract_mentions(f"Qui a reçu le {text} ?", llm, index)
    assert found == [Mention("prix Nobel de la paix", NOBEL.NobelPrize)]


# --- résolution ------------------------------------------------------------


@pytest.mark.parametrize(
    ("mention", "status", "expected"),
    [
        (Mention("marie curie", NOBEL.Person), Status.EXACT, {CURIE}),
        (Mention("Richard Feynmann", NOBEL.Person), Status.SUGGESTION, {FEYNMAN}),
        # Classe devinée fausse : recherche élargie à toute l'ontologie.
        (Mention("Richard Feynmann", NOBEL.Place), Status.SUGGESTION, {FEYNMAN}),
        # Rien de proche : individus de la classe.
        (Mention("Niels Bohr", NOBEL.Person), Status.NOT_FOUND, {CAMUS, FRANCE, CURIE, FEYNMAN}),
        # Homonymes : les deux villes, et l'université exactement homonyme sans son préfixe.
        (
            Mention("Cambridge", NOBEL.Place),
            Status.AMBIGUOUS,
            {CAMBRIDGE_UK, CAMBRIDGE_MA, CAMBRIDGE_UNIV},
        ),
    ],
)
def test_resolve(index, mention, status, expected):
    r = resolve(mention, index, THRESHOLD)
    assert (r.status, {m.uri for m in r.candidates}) == (status, expected)


# --- flux complet ----------------------------------------------------------


def test_exact_match_is_rewritten_without_asking(index):
    resolver = QuestionResolver(
        FakeLLM(mentions(("Nobel de la paix", "NobelPrize"))), index, THRESHOLD
    )

    def choose(_):
        raise AssertionError("aucune confirmation attendue")

    q = resolver.reformulate("Qui a reçu le Nobel de la paix ?", choose)
    assert q == f'Qui a reçu le Nobel de la paix ("prix Nobel de la paix" <{PEACE}>) ?'


def test_rejected_suggestion_keeps_user_wording(index):
    resolver = QuestionResolver(FakeLLM(mentions(("Richard Feynmann", "Person"))), index, THRESHOLD)
    q = resolver.reformulate("Qui a formé Richard Feynmann ?", lambda _: None)
    assert q == "Qui a formé Richard Feynmann ?"
