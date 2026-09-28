"""TBox : classes et propriétés de l'ontologie des prix Nobel.

Le vocabulaire est local (`nobel:`) et lisible, contrairement aux identifiants
opaques de Wikidata (`wdt:P166`) : le LLM qui génère le SPARQL ne voit que ce
schéma. Les individus gardent leur IRI Wikidata (`wd:Q937`), ce qui permet de
remonter à la source.

LangChain ne montre au LLM que l'IRI et le `rdfs:comment` de chaque classe et
propriété : domaine et portée sont donc répétés en tête du commentaire.
"""

from rdflib import OWL, RDF, RDFS, SKOS, XSD, Graph, Literal

from ..namespace import CHATBOT, NOBEL

# Classes : URI -> (label FR, commentaire FR)
CLASSES = {
    NOBEL.Person: ("Personne", "Une personne : lauréat d'un prix Nobel ou directeur de thèse."),
    NOBEL.Organization: (
        "Organisation lauréate",
        "Une organisation lauréate d'un prix Nobel (surtout le prix Nobel de la paix).",
    ),
    NOBEL.NobelPrize: (
        "Prix Nobel",
        "Une catégorie de prix Nobel : physique, chimie, physiologie ou médecine, "
        "littérature, paix, sciences économiques.",
    ),
    NOBEL.NobelAward: (
        "Attribution d'un prix Nobel",
        "L'attribution d'un prix Nobel à un lauréat une année donnée : "
        "?laureat nobel:received ?attribution . ?attribution nobel:category ?prix ; "
        "nobel:year ?annee .",
    ),
    NOBEL.Institution: (
        "Établissement",
        "Une université, un institut de recherche ou une entreprise où une personne a "
        "étudié ou travaillé.",
    ),
    NOBEL.Country: ("Pays", "Un pays ou un État, actuel ou historique."),
    NOBEL.Place: ("Lieu", "Une ville ou un lieu de naissance ou de décès."),
}

# Préfixes usuels des noms d'individus, par classe (voir CHATBOT.namePrefix).
NAME_PREFIXES = {
    NOBEL.NobelPrize: ("prix Nobel de", "prix Nobel d'", "prix Nobel", "Nobel de", "Nobel d'"),
    NOBEL.Institution: ("université de", "université d'", "université", "university of"),
}

# Propriétés d'objet : URI -> (label FR, domaine, portée, commentaire FR)
OBJECT_PROPERTIES = {
    NOBEL.wonPrize: (
        "a reçu",
        None,
        NOBEL.NobelPrize,
        "Lauréat (Personne ou Organisation) -> Prix Nobel. Raccourci sans l'année ; "
        "pour l'année, passer par nobel:NobelAward.",
    ),
    # Nommées dans le sens où le LLM les écrit spontanément : avec
    # `nobel:laureate` (Attribution -> lauréat), il inversait sujet et objet.
    NOBEL.received: (
        "a reçu l'attribution",
        None,
        NOBEL.NobelAward,
        "Lauréat (Personne ou Organisation) -> Attribution qu'il a reçue.",
    ),
    NOBEL.category: (
        "catégorie",
        NOBEL.NobelAward,
        NOBEL.NobelPrize,
        "Attribution -> Prix Nobel (catégorie) attribué.",
    ),
    NOBEL.citizenOf: (
        "a la nationalité",
        NOBEL.Person,
        NOBEL.Country,
        "Personne -> Pays dont elle a la nationalité (plusieurs possibles).",
    ),
    NOBEL.bornIn: ("est né à", NOBEL.Person, NOBEL.Place, "Personne -> Lieu de naissance."),
    NOBEL.diedIn: ("est mort à", NOBEL.Person, NOBEL.Place, "Personne -> Lieu de décès."),
    NOBEL.locatedIn: (
        "se situe dans",
        None,
        NOBEL.Country,
        "Lieu ou Établissement -> Pays où il se situe.",
    ),
    NOBEL.educatedAt: (
        "a étudié à",
        NOBEL.Person,
        NOBEL.Institution,
        "Personne -> Établissement où elle a étudié.",
    ),
    NOBEL.worksFor: (
        "a travaillé pour",
        NOBEL.Person,
        NOBEL.Institution,
        "Personne -> Établissement qui l'a employée.",
    ),
    NOBEL.doctoralAdvisor: (
        "a pour directeur de thèse",
        NOBEL.Person,
        NOBEL.Person,
        "Personne (doctorant) -> Personne qui a dirigé sa thèse.",
    ),
}

# Propriétés de donnée : URI -> (label FR, domaine, portée, commentaire FR)
# Le format attendu des valeurs est répété dans le commentaire, seul lu par le
# LLM : sans lui, il écrit les années entre guillemets et compare une date
# complète à une année.
DATATYPE_PROPERTIES = {
    NOBEL.name: (
        "nom",
        None,
        XSD.string,
        "Tout individu -> nom lisible (chaîne sans langue). À utiliser pour désigner "
        'une entité par son nom : ?x nobel:name "Marie Curie".',
    ),
    NOBEL.familyName: ("nom de famille", NOBEL.Person, XSD.string, "Personne -> nom de famille."),
    NOBEL.gender: (
        "genre",
        NOBEL.Person,
        XSD.string,
        'Personne -> genre : "femme" ou "homme".',
    ),
    NOBEL.birthDate: (
        "date de naissance",
        NOBEL.Person,
        XSD.date,
        "Personne -> date de naissance complète (xsd:date AAAA-MM-JJ), absente si "
        "seule l'année est connue. Pour une année, préférer nobel:birthYear.",
    ),
    NOBEL.deathDate: (
        "date de décès",
        NOBEL.Person,
        XSD.date,
        "Personne -> date de décès complète (xsd:date AAAA-MM-JJ), absente si seule "
        "l'année est connue. Pour une année, préférer nobel:deathYear.",
    ),
    NOBEL.birthYear: (
        "année de naissance",
        NOBEL.Person,
        XSD.integer,
        "Personne -> année de naissance (entier sans guillemets : nobel:birthYear 1913).",
    ),
    NOBEL.deathYear: (
        "année de décès",
        NOBEL.Person,
        XSD.integer,
        "Personne -> année de décès (entier sans guillemets : nobel:deathYear 1960).",
    ),
    NOBEL.year: (
        "année",
        NOBEL.NobelAward,
        XSD.integer,
        "Attribution -> année d'attribution du prix (entier sans guillemets : " "nobel:year 2024).",
    ),
    NOBEL.motivation: (
        "motivation",
        NOBEL.NobelAward,
        XSD.string,
        "Attribution -> motivation officielle du prix, en anglais.",
    ),
}

# Propriétés portant un nom d'individu : indexées par le fuzzy matching du
# chatbot, qui indexe les sous-propriétés de rdfs:label et skos:altLabel.
LABEL_SUBPROPERTIES = {NOBEL.name: RDFS.label, NOBEL.familyName: SKOS.altLabel}


def build_schema() -> Graph:
    """Construit le graphe TBox (classes + propriétés) de l'ontologie Nobel."""
    g = Graph()
    g.bind("nobel", NOBEL)
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
        if domain is not None:
            g.add((prop, RDFS.domain, domain))
        if range_ is not None:
            g.add((prop, RDFS.range, range_))

    for prop, (label, domain, range_, comment) in DATATYPE_PROPERTIES.items():
        g.add((prop, RDF.type, OWL.DatatypeProperty))
        g.add((prop, RDFS.label, Literal(label, lang="fr")))
        g.add((prop, RDFS.comment, Literal(comment, lang="fr")))
        if domain is not None:
            g.add((prop, RDFS.domain, domain))
        g.add((prop, RDFS.range, range_))

    for prop, parent in LABEL_SUBPROPERTIES.items():
        g.add((prop, RDFS.subPropertyOf, parent))

    return g
