"""TBox : classes et propriétés de l'ontologie médicale minimale.

Domaine choisi : médecins, patients, maladies et hôpitaux, avec 4 propriétés
d'objet reliant ces classes.
"""

from rdflib import OWL, RDF, RDFS, XSD, Graph, Literal

from .namespace import CHATBOT, EX

# Classes : URI -> (label FR, commentaire FR)
CLASSES = {
    EX.Doctor: ("Médecin", "Une personne qui exerce la médecine."),
    EX.Patient: ("Patient", "Une personne suivie médicalement."),
    EX.Disease: ("Maladie", "Une pathologie pouvant être diagnostiquée chez un patient."),
    EX.Hospital: ("Hôpital", "Un établissement de soins."),
}

# Préfixes usuels des noms d'individus, par classe, publiés dans l'ontologie
# (chatbot:namePrefix). Le fuzzy matching du chatbot compare aussi les noms
# privés de ce préfixe, pour que "Saint-Louis" retrouve "Hôpital Saint-Louis"
# et "Bernard" retrouve "Dr Bernard".
NAME_PREFIXES = {
    EX.Doctor: ("Dr", "Docteur", "Docteure"),
    EX.Hospital: ("Hôpital", "CHU"),
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
    g.bind("chatbot", CHATBOT)

    g.add((CHATBOT.namePrefix, RDF.type, OWL.AnnotationProperty))

    for cls, (label, comment) in CLASSES.items():
        g.add((cls, RDF.type, OWL.Class))
        g.add((cls, RDFS.label, Literal(label, lang="fr")))
        g.add((cls, RDFS.comment, Literal(comment, lang="fr")))
        for prefix in NAME_PREFIXES.get(cls, ()):
            g.add((cls, CHATBOT.namePrefix, Literal(prefix, lang="fr")))

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
        # Indexée par le fuzzy matching du chatbot comme un label.
        g.add((prop, RDFS.subPropertyOf, RDFS.label))

    return g
