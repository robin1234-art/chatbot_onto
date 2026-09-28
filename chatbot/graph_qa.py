"""Construction de la chaîne Text-to-SPARQL (RdfGraph + GraphSparqlQAChain).

Le LLM lit le schéma RDFS/OWL exposé par RdfGraph, génère une requête SPARQL,
l'exécute sur le graphe local, puis rédige la réponse à partir des résultats.
"""

from langchain_community.chains.graph_qa.sparql import GraphSparqlQAChain
from langchain_core.prompts import PromptTemplate

from .config import ONTOLOGY_PATH
from .llm import get_llm
from .rdf_graph import CleanRdfGraph

# Remplace le prompt par défaut de LangChain, dont l'exemple (foaf:name) pousse
# le LLM à inventer des prédicats, et qui ne dit rien des individus : le LLM
# inventait leur IRI (nobel:Physics) et renvoyait des IRI que le LLM de
# réponse ne savait pas lire.
SPARQL_SELECT_PROMPT = PromptTemplate.from_template(
    """Tâche : écrire une requête SPARQL SELECT qui répond à une question sur un graphe OWL.

Exemple, sur un autre graphe, pour la question :
Qui a réalisé le Voyage dans la Lune ("Le Voyage dans la Lune" <http://example.org/films#f42>) ?
PREFIX ex: <http://example.org/films#>
SELECT DISTINCT ?directorName WHERE {{
    <http://example.org/films#f42> ex:directedBy ?director .
    ?director ex:name ?directorName .
}}

Règles :
- N'utilise que les classes et propriétés du schéma ci-dessous, et déclare tous
  les préfixes employés.
- Quand la question donne l'IRI d'un individu entre chevrons, utilise cette
  IRI telle quelle.
- N'invente jamais l'IRI d'un individu (personne, lieu, prix...). Sans IRI
  fournie, désigne-le par sa propriété de nom, en recopiant exactement le
  texte de la question.
- Renvoie le nom lisible des individus (propriété de nom), jamais leur IRI seul.
- Respecte le sens des propriétés : la description « A -> B » d'une propriété
  signifie que A est le sujet du triplet et B son objet.
- Utilise DISTINCT, et OPTIONAL pour une information qui peut manquer.
- Réponds uniquement avec la requête, sans explication.

Schéma :
{schema}

Question : {prompt}"""
)


# Remplace le prompt de réponse par défaut, qui laissait le LLM compléter des
# résultats vides avec ses propres connaissances.
SPARQL_QA_PROMPT = PromptTemplate.from_template(
    """Tâche : répondre en français à une question à partir des résultats d'une requête SPARQL.

Règles :
- Appuie-toi uniquement sur les résultats ci-dessous, jamais sur tes propres
  connaissances : n'ajoute aucun fait qui n'y figure pas.
- Si les résultats sont vides, réponds que l'information n'a pas été trouvée
  dans l'ontologie.
- Ne mentionne ni IRI ni SPARQL.

Résultats :
{context}

Question : {prompt}
Réponse :"""
)


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
        sparql_select_prompt=SPARQL_SELECT_PROMPT,
        qa_prompt=SPARQL_QA_PROMPT,
        # Le fichier source est local et versionné : le pire cas d'une requête
        # UPDATE générée par erreur est régénérable via `python -m ontology.build`.
        allow_dangerous_requests=True,
        return_sparql_query=True,
        verbose=verbose,
    )
