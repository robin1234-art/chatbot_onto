"""Espaces de noms partagés par l'ontologie et le chatbot."""

from rdflib import Namespace

# Vocabulaire lisible de l'ontologie des prix Nobel ; individus Wikidata.
NOBEL = Namespace("http://example.org/onto-nobel#")
WD = Namespace("http://www.wikidata.org/entity/")

# Annotations lues par le chatbot.
# `CHATBOT.namePrefix` : préfixe usuel des noms d'individus d'une classe
# ("prix Nobel de", "université de"...), ignoré lors d'une 2e comparaison floue.
CHATBOT = Namespace("http://example.org/chatbot#")
