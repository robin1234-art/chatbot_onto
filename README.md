# chatbot_onto
An ontology-based chatbot that combines LLMs with a formally constructed ontology, pairing natural-language understanding with structured, verifiable knowledge.

## Architecture (prototype v0)

Approche **Text-to-SPARQL** : le LLM lit le schéma de l'ontologie, génère une
requête SPARQL, l'exécute sur le graphe, puis rédige la réponse à partir des
résultats (LangChain `RdfGraph` + `GraphSparqlQAChain`).

```
ontology/           # construction de l'ontologie (rdflib)
  namespace.py       # espace de noms partagé
  schema.py           # TBox : classes + propriétés (règles)
  instances.py        # ABox : individus + faits
  build.py             # sérialise schema.ttl / instances.ttl / ontology.ttl
  data/                 # fichiers .ttl générés

chatbot/            # chatbot LLM (OpenRouter) sur l'ontologie
  config.py           # variables d'environnement, chemin de l'ontologie
  llm.py               # client OpenRouter (API compatible OpenAI)
  entity_matcher.py    # index flou des individus de l'ontologie
  resolver.py          # résolution des noms d'entités avant la chaîne SPARQL
  rdf_graph.py          # RdfGraph nettoyant les réponses markdown du LLM
  graph_qa.py          # chaîne RdfGraph + GraphSparqlQAChain
  cli.py                # boucle de discussion + confirmation des corrections
```

L'ontologie minimale décrit médecins, patients, maladies et hôpitaux via 4
propriétés (`treats`, `hasDisease`, `worksAt`, `specialistIn`).

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt  # installe le projet en mode éditable (-e .)
cp .env.example .env  # puis renseignez OPENROUTER_API_KEY
```

`ontology/` et `chatbot/` utilisent des imports relatifs (`from .schema import
...`). L'install éditable (`pip install -e .`, déclarée dans
`pyproject.toml`) enregistre le repo comme package dans le venv : les imports
relatifs fonctionnent alors depuis n'importe quel répertoire courant.
Toujours lancer les scripts via `python -m <package>.<module>`
(ex. `python -m ontology.build`), jamais en exécution directe
(`python ontology/build.py`), qui casse les imports relatifs.

## Utilisation

```bash
# 1. Générer l'ontologie (TBox + ABox -> ontology/data/*.ttl)
python -m ontology.build

# 2. Poser une question unique
python -m chatbot.cli "Quels médecins soignent des patients atteints de diabète ?"

# ... ou lancer une boucle interactive (sans argument)
python -m chatbot.cli
```

## Résolution des noms d'entités (fuzzy matching)

Constat empirique : le Text2SPARQL échoue silencieusement quand l'utilisateur
(ou le LLM) écrit mal le nom d'un individu — "docteur Bornard" au lieu de
"Dr Bernard", "hopital saint louis" au lieu de "Hôpital Saint-Louis" — la
requête s'exécute et ne renvoie rien.

La correction se fait **sur la question, avant `GraphSparqlQAChain`**, qui
reste inchangée ([chatbot/resolver.py](chatbot/resolver.py)) :

1. **Extraction** (LLM, sortie JSON) : mentions d'individus telles
   qu'écrites dans la question + classe probable (`Doctor`...). Une question
   qui ne porte que sur des classes ne produit aucune mention et part telle
   quelle.
2. **Résolution** (sans LLM, [chatbot/entity_matcher.py](chatbot/entity_matcher.py)) :
   fuzzy match (`rapidfuzz.fuzz.ratio` sur chaînes normalisées, et une 2e fois
   sans préfixe de classe `NAME_PREFIXES` : "Bernard" → "Dr Bernard") contre
   les individus de la classe devinée, élargi à toute l'ontologie si la classe
   ne donne rien.

   | Résultat | Action |
   |---|---|
   | identique après normalisation (accents, casse, préfixe) | corrigé d'office |
   | un candidat ≥ `FUZZY_SUGGEST_THRESHOLD` (défaut 75) | proposé : « Vouliez-vous dire "Dr Bernard" ? » |
   | plusieurs candidats à moins de 5 points | liste proposée |
   | aucun candidat | liste des individus de la classe proposée |

   Le seuil est bas car toute correction non triviale est validée par
   l'utilisateur ; s'il garde sa formulation, elle est transmise telle quelle.
3. **Reformulation** : la mention est remplacée par le label canonique entre
   guillemets (`Que peux-tu me dire du "Dr Bernard" ?`), puis la question
   reformulée est envoyée à `GraphSparqlQAChain`.

Tests (LLM simulé) : `pytest tests`.

### Limites connues

- Concepts (classes/propriétés) non validés : "infirmier" peut encore être
  mappé silencieusement sur `Doctor`.
- La qualité de l'extraction dépend du LLM : une mention non repérée n'est pas
  corrigée (la question part telle quelle).
- Pas d'embeddings/vector store : le fuzzy matching lexical suffit vu la
  taille actuelle de l'ontologie (~10 individus, 4 classes).
