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

Règles :
- N'utilise que les classes et propriétés du schéma ci-dessous, et déclare tous
  les préfixes employés.
- Quand la question donne l'IRI d'un individu entre chevrons, utilise cette
  IRI telle quelle.
- Déclare les préfix en haut de requête.
- N'invente jamais l'IRI d'un individu (personne, lieu, prix...). Sans IRI
  fournie, désigne-le par sa propriété de nom, en recopiant exactement le
  texte de la question.
- Renvoie le nom lisible des individus (propriété de nom), jamais leur IRI seul.
- Respecte le sens des propriétés : la description « A -> B » d'une propriété
  signifie que A est le sujet du triplet et B son objet.
- Écris les nombres et les années sans guillemets (nobel:year 2024), et les
  dates complètes typées ("1951-09-14"^^xsd:date, préfixe xsd déclaré).
- Pour une année seule, utilise une propriété d'année entière si le schéma
  en a une, sinon YEAR(?date) : une année n'est jamais égale à une date.
- Pour « le dernier », « le plus récent » ou « le premier », ne suppose pas
  l'année en cours : calcule l'année extrême dans une sous-requête
  ({{ SELECT (MAX(?y) AS ?annee) WHERE {{ ... }} }}), puis garde toutes les
  lignes de cette année, sans LIMIT (un prix peut avoir plusieurs lauréats).
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
- Les résultats répondent à la question telle quelle : la requête a déjà
  appliqué ses conditions (année, « le dernier »...), même quand elles
  n'apparaissent pas dans les colonnes. Ne les remets pas en doute.
- Si les résultats sont vides, réponds que l'information n'a pas été trouvée
  dans l'ontologie.
- Ne mentionne ni IRI ni SPARQL.
- Écris les dates en toutes lettres (« 14 septembre 1951 » pour 1951-09-14).

Résultats :
{context}

Question : {prompt}
Réponse :"""
)


def build_chain(verbose: bool = True) -> GraphSparqlQAChain:
    if not ONTOLOGY_PATH.exists():
        raise FileNotFoundError(
            f"Ontologie introuvable : {ONTOLOGY_PATH}. "
            "Générez-la d'abord avec : python -m ontology.extract"
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
        # UPDATE générée par erreur est régénérable via `python -m ontology.extract`.
        allow_dangerous_requests=True,
        return_sparql_query=True,
        verbose=verbose,
    )
