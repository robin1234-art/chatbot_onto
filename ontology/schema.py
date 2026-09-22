"""TBox : classes et propriétés de l'ontologie médicale minimale.

Domaine choisi : médecins, patients, maladies et hôpitaux, avec 4 propriétés
d'objet reliant ces classes.
"""
from rdflib import Graph, Literal, OWL, RDF, RDFS, XSD

from .namespace import EX

# Classes : URI -> (label FR, commentaire FR)
CLASSES = {
    EX.Doctor: ("Médecin", "Une personne qui exerce la médecine."),
    EX.Patient: ("Patient", "Une personne suivie médicalement."),
    EX.Disease: ("Maladie", "Une pathologie pouvant être diagnostiquée chez un patient."),
    EX.Hospital: ("Hôpital", "Un établissement de soins."),
}

# Propriétés de type donnée : URI -> (label FR, commentaire FR)
# Nécessaire pour que GraphSparqlQAChain sache qu'il existe un composant
# interrogeable pour identifier une entité par son nom (sans ça, le LLM
# hallucine un prédicat "name" sur le modèle de l'exemple foaf:name du
# prompt SPARQL par défaut de LangChain, et la requête générée ne matche
# jamais rien).
DATATYPE_PROPERTIES = {
    EX.name: (
        "nom",
        "Nom lisible d'un médecin, patient, maladie ou hôpital.",
    ),
}

# Propriétés d'objet : URI -> (label FR, domaine, portée, commentaire FR)
OBJECT_PROPERTIES = {
    EX.treats: (
        "soigne",
        EX.Doctor,
        EX.Patient,
        "Relie un médecin au patient qu'il soigne.",
    ),
    EX.hasDisease: (
        "est atteint de",
        EX.Patient,
        EX.Disease,
        "Relie un patient à une maladie diagnostiquée.",
    ),
    EX.worksAt: (
        "travaille à",
        EX.Doctor,
        EX.Hospital,
        "Relie un médecin à l'hôpital où il exerce.",
    ),
    EX.specialistIn: (
        "est spécialiste de",
        EX.Doctor,
        EX.Disease,
        "Relie un médecin à une maladie dont il est spécialiste.",
    ),
}


def build_schema() -> Graph:
    """Construit le graphe TBox (classes + propriétés) de l'ontologie."""
    g = Graph()
    g.bind("ex", EX)

    for cls, (label, comment) in CLASSES.items():
        g.add((cls, RDF.type, OWL.Class))
        g.add((cls, RDFS.label, Literal(label, lang="fr")))
        g.add((cls, RDFS.comment, Literal(comment, lang="fr")))

    for prop, (label, domain, range_, comment) in OBJECT_PROPERTIES.items():
        g.add((prop, RDF.type, OWL.ObjectProperty))
        g.add((prop, RDFS.label, Literal(label, lang="fr")))
        g.add((prop, RDFS.comment, Literal(comment, lang="fr")))
        g.add((prop, RDFS.domain, domain))
        g.add((prop, RDFS.range, range_))

    for prop, (label, comment) in DATATYPE_PROPERTIES.items():
        g.add((prop, RDF.type, OWL.DatatypeProperty))
        g.add((prop, RDFS.label, Literal(label, lang="fr")))
        g.add((prop, RDFS.comment, Literal(comment, lang="fr")))
        g.add((prop, RDFS.range, XSD.string))

    return g
