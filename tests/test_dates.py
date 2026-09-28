"""Tests de l'explicitation des dates d'une question (sans appel au LLM)."""

from datetime import date

import pytest

from chatbot.dates import annotate_dates

TODAY = date(2026, 9, 28)


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Qui est né le 14 septembre 1951 ?", "Qui est né le 14 septembre 1951 (1951-09-14) ?"),
        ("Qui est mort le 4/1/1960 ?", "Qui est mort le 4/1/1960 (1960-01-04) ?"),
        ("Qui est né en août 1951 ?", "Qui est né en août 1951 (1951-08) ?"),
        ("Lauréats des années 50 ?", "Lauréats des années 50 (de 1950 à 1959) ?"),
        ("Prix du XXe siècle ?", "Prix du XXe siècle (de 1901 à 2000) ?"),
        ("Qui a gagné l'an dernier ?", "Qui a gagné l'an dernier (2025) ?"),
        ("Qui a gagné il y a 10 ans ?", "Qui a gagné il y a 10 ans (2016) ?"),
        # Inchangées : année seule déjà explicite, date invalide.
        ("quel est le prix nobel de la paix 2024 ?", "quel est le prix nobel de la paix 2024 ?"),
        ("Qui est né le 30 février 1900 ?", "Qui est né le 30 février 1900 ?"),
    ],
)
def test_annotate_dates(question, expected):
    assert annotate_dates(question, TODAY) == expected
