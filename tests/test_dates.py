"""Tests de l'explicitation des dates d'une question (sans appel au LLM)."""

from datetime import date

import pytest

from chatbot.dates import annotate_dates

TODAY = date(2026, 9, 28)


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Qui est né le 14 septembre 1951 ?", "Qui est né le 14 septembre 1951 (1951-09-14) ?"),
        ("Qui est né le 1er février 1900 ?", "Qui est né le 1er février 1900 (1900-02-01) ?"),
        ("Qui est né le 1er fevrier 1900 ?", "Qui est né le 1er fevrier 1900 (1900-02-01) ?"),
        ("Qui est mort le 4/1/1960 ?", "Qui est mort le 4/1/1960 (1960-01-04) ?"),
        ("Qui est né en août 1951 ?", "Qui est né en août 1951 (1951-08) ?"),
        ("Lauréats des années 50 ?", "Lauréats des années 50 (de 1950 à 1959) ?"),
        ("Lauréats des années 1990 ?", "Lauréats des années 1990 (de 1990 à 1999) ?"),
        ("Prix du XXe siècle ?", "Prix du XXe siècle (de 1901 à 2000) ?"),
        ("Prix du XIXe siècle ?", "Prix du XIXe siècle (de 1801 à 1900) ?"),
        ("Prix du 21ème siècle ?", "Prix du 21ème siècle (de 2001 à 2100) ?"),
        ("Qui a gagné l'an dernier ?", "Qui a gagné l'an dernier (2025) ?"),
        ("Qui a gagné l'année dernière ?", "Qui a gagné l'année dernière (2025) ?"),
        ("Qui a gagné cette année ?", "Qui a gagné cette année (2026) ?"),
        ("Qui a gagné il y a 10 ans ?", "Qui a gagné il y a 10 ans (2016) ?"),
    ],
)
def test_dates_are_made_explicit(question, expected):
    assert annotate_dates(question, TODAY) == expected


@pytest.mark.parametrize(
    "question",
    [
        "quel est le prix nobel de la paix 2024 ?",  # année seule : déjà explicite
        "Qui est né le 30 février 1900 ?",  # date invalide
        "Qui a gagné ce siècle ?",  # "ce" n'est pas un nombre romain
        'Qui a gagné en 2024 ("prix Nobel" <http://www.wikidata.org/entity/Q35637>) ?',
    ],
)
def test_other_questions_are_unchanged(question):
    assert annotate_dates(question, TODAY) == question


def test_annotation_is_idempotent():
    once = annotate_dates("Qui est né le 14 septembre 1951 l'an dernier ?", TODAY)
    assert annotate_dates(once, TODAY) == once
