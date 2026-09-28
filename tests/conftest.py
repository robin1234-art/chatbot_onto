"""Petit graphe Nobel partagé par les tests (données simplifiées)."""

import pytest
from rdflib import RDF, RDFS, XSD, Graph, Literal

from ontology.namespace import NOBEL, WD
from ontology.schema import build_schema

PEACE, PHYSICS, LITERATURE = WD.Q35637, WD.Q38104, WD.Q37922
HIDANKYO, CAMUS, FRANCE = WD.Q1, WD.Q2, WD.Q3
CURIE, FEYNMAN = WD.Q7186, WD.Q39246
CAMBRIDGE_UK, CAMBRIDGE_MA, CAMBRIDGE_UNIV = WD.Q350, WD.Q49111, WD.Q35794


def add_individual(g: Graph, uri, cls, name, description=None):
    g.add((uri, RDF.type, cls))
    g.add((uri, RDFS.label, Literal(name, lang="fr")))
    g.add((uri, NOBEL.name, Literal(name)))
    if description:
        g.add((uri, RDFS.comment, Literal(description)))


@pytest.fixture(scope="session")
def nobel_graph() -> Graph:
    g = build_schema()
    g.bind("wd", WD)
    for uri, cls, name, description in [
        (PEACE, NOBEL.NobelPrize, "prix Nobel de la paix", None),
        (PHYSICS, NOBEL.NobelPrize, "prix Nobel de physique", None),
        (LITERATURE, NOBEL.NobelPrize, "prix Nobel de littérature", None),
        (HIDANKYO, NOBEL.Organization, "Nihon Hidankyō", None),
        (CAMUS, NOBEL.Person, "Albert Camus", None),
        (FRANCE, NOBEL.Person, "Anatole France", None),
        (CURIE, NOBEL.Person, "Marie Curie", None),
        (FEYNMAN, NOBEL.Person, "Richard Feynman", "physicien américain"),
        (CAMBRIDGE_UK, NOBEL.Place, "Cambridge", "ville d'Angleterre"),
        (CAMBRIDGE_MA, NOBEL.Place, "Cambridge", "ville du Massachusetts"),
        (CAMBRIDGE_UNIV, NOBEL.Institution, "université de Cambridge", None),
    ]:
        add_individual(g, uri, cls, name, description)

    for laureate, year, born, advisor in [
        (HIDANKYO, 2024, None, None),
        (CAMUS, 1957, "1913-11-07", FRANCE),
        (FRANCE, 1921, "1844-04-16", None),
    ]:
        award = NOBEL[f"award_{laureate.removeprefix(str(WD))}"]
        g.add((laureate, NOBEL.received, award))
        g.add((award, RDF.type, NOBEL.NobelAward))
        g.add((award, NOBEL.category, PEACE))
        g.add((award, NOBEL.year, Literal(year, datatype=XSD.integer)))
        if born:
            g.add((laureate, NOBEL.birthDate, Literal(born, datatype=XSD.date)))
        if advisor:
            g.add((laureate, NOBEL.doctoralAdvisor, advisor))
    return g
