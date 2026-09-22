"""ABox : instances (individus et faits) de l'ontologie médicale minimale.

Ce fichier ne redéfinit aucune classe ni propriété : il se contente
d'instancier le vocabulaire déclaré dans schema.py.
"""
from rdflib import Graph, Literal, RDF, RDFS

from .namespace import EX

HOSPITALS = {
    EX.HopitalSaintLouis: "Hôpital Saint-Louis",
    EX.HopitalPitieSalpetriere: "Hôpital Pitié-Salpêtrière",
}

DISEASES = {
    EX.Diabete: "Diabète",
    EX.Asthme: "Asthme",
    EX.Migraine: "Migraine",
}

# uri -> (nom, hôpital, maladie dont il est spécialiste ou None)
DOCTORS = {
    EX.DrMartin: ("Dr Martin", EX.HopitalSaintLouis, EX.Diabete),
    EX.DrBernard: ("Dr Bernard", EX.HopitalPitieSalpetriere, EX.Asthme),
    EX.DrDupont: ("Dr Dupont", EX.HopitalSaintLouis, None),
}

# uri -> (nom, maladie, médecin traitant)
PATIENTS = {
    EX.Alice: ("Alice", EX.Diabete, EX.DrMartin),
    EX.Bob: ("Bob", EX.Asthme, EX.DrBernard),
    EX.Chloe: ("Chloé", EX.Diabete, EX.DrDupont),
}


def build_instances() -> Graph:
    """Construit le graphe ABox (individus + faits) de l'ontologie."""
    g = Graph()
    g.bind("ex", EX)

    for uri, label in HOSPITALS.items():
        g.add((uri, RDF.type, EX.Hospital))
        g.add((uri, RDFS.label, Literal(label, lang="fr")))
        g.add((uri, EX.name, Literal(label)))

    for uri, label in DISEASES.items():
        g.add((uri, RDF.type, EX.Disease))
        g.add((uri, RDFS.label, Literal(label, lang="fr")))
        g.add((uri, EX.name, Literal(label)))

    for uri, (name, hospital, specialty) in DOCTORS.items():
        g.add((uri, RDF.type, EX.Doctor))
        g.add((uri, RDFS.label, Literal(name, lang="fr")))
        g.add((uri, EX.name, Literal(name)))
        g.add((uri, EX.worksAt, hospital))
        if specialty is not None:
            g.add((uri, EX.specialistIn, specialty))

    for uri, (name, disease, doctor) in PATIENTS.items():
        g.add((uri, RDF.type, EX.Patient))
        g.add((uri, RDFS.label, Literal(name, lang="fr")))
        g.add((uri, EX.name, Literal(name)))
        g.add((uri, EX.hasDisease, disease))
        g.add((doctor, EX.treats, uri))

    return g
