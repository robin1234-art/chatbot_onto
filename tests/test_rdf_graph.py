"""Tests du nettoyage des requêtes SPARQL générées (sans appel au LLM)."""

from rdflib import Graph

from chatbot.rdf_graph import _clean

# Requête réellement générée pour "Qui a gagné le prix Nobel de la paix en 2024 ?"
DUPLICATE_PREFIXES = """```sparql
PREFIX ex: <http://example.org/onto-nobel#>
PREFIX nobel: <http://example.org/onto-nobel#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>

SELECT DISTINCT ?personName WHERE {
    ?award a nobel:NobelAward .
    ?person nobel:received ?award .
    ?person ex:name ?personName .
}
```"""


def test_duplicate_prefixes_are_merged_into_the_first_one():
    cleaned = _clean(DUPLICATE_PREFIXES)
    assert "PREFIX nobel:" not in cleaned
    assert "?person ex:received ?award" in cleaned
    assert "?award a ex:NobelAward" in cleaned
    assert "PREFIX owl: <http://www.w3.org/2002/07/owl#>" in cleaned
    Graph().query(cleaned)  # rdflib accepte la requête


def test_iris_are_left_untouched():
    query = """PREFIX a: <http://x.org/#>
PREFIX b: <http://x.org/#>
SELECT ?s WHERE { ?s b:p <http://y.org/b:c> . ?s a:q "b:d" }"""
    cleaned = _clean(query)
    assert "?s a:p <http://y.org/b:c>" in cleaned


def test_query_without_duplicates_is_unchanged():
    query = "PREFIX ex: <http://x.org/#>\nSELECT ?s WHERE { ?s ex:p ?o }"
    assert _clean(query) == query
