"""Espaces de noms partagés par les ontologies et le chatbot."""

from rdflib import Namespace

# Ontologie médicale minimale (jouet).
EX = Namespace("http://example.org/onto-medical#")

# Ontologie des prix Nobel, extraite de Wikidata.
NOBEL = Namespace("http://example.org/onto-nobel#")
WD = Namespace("http://www.wikidata.org/entity/")

# Annotations lues par le chatbot, communes à toutes les ontologies.
# `CHATBOT.namePrefix` : préfixe usuel des noms d'individus d'une classe
# ("Dr", "Université de"...), ignoré lors d'une 2e comparaison floue.
CHATBOT = Namespace("http://example.org/chatbot#")
