"""Construction de la chaîne Text-to-SPARQL (RdfGraph + GraphSparqlQAChain).

Le LLM lit le schéma RDFS/OWL exposé par RdfGraph, génère une requête SPARQL,
l'exécute sur le graphe local, puis rédige la réponse à partir des résultats.
"""

from langchain_community.chains.graph_qa.sparql import GraphSparqlQAChain

from .config import ONTOLOGY_PATH
from .llm import get_llm
from .rdf_graph import CleanRdfGraph


def build_chain(verbose: bool = True) -> GraphSparqlQAChain:
    if not ONTOLOGY_PATH.exists():
        raise FileNotFoundError(
            f"Ontologie introuvable : {ONTOLOGY_PATH}. "
            "Générez-la d'abord avec : python -m ontology.build"
        )

    graph = CleanRdfGraph(
        source_file=str(ONTOLOGY_PATH),
        standard="owl",
        serialization="ttl",
    )

    return GraphSparqlQAChain.from_llm(
        get_llm(),
        graph=graph,
        # Le fichier source est local et versionné : le pire cas d'une requête
        # UPDATE générée par erreur est régénérable via `python -m ontology.build`.
        allow_dangerous_requests=True,
        return_sparql_query=True,
        verbose=verbose,
    )
