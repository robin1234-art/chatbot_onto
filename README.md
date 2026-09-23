# chatbot_onto
An ontology-based chatbot that combines LLMs with a formally constructed ontology, pairing natural-language understanding with structured, verifiable knowledge.

## Architecture

Approche **Text-to-SPARQL** : le LLM lit le schéma de l'ontologie, génère une
requête SPARQL, l'exécute sur le graphe, puis rédige la réponse à partir des
résultats (LangChain `RdfGraph` + `GraphSparqlQAChain`).

En amont de la chaîne, une étape de **résolution des entités** corrige les
noms d'individus mal orthographiés, avec confirmation de l'utilisateur :

```
question
  │
  ├─ 1. extraction (LLM, JSON)      mentions d'individus + classe probable
  ├─ 2. résolution (fuzzy, sans LLM) candidats dans l'ontologie
  │      └─ confirmation utilisateur si la correction n'est pas triviale
  ├─ 3. reformulation               label canonique entre guillemets
  │
  └─ GraphSparqlQAChain (inchangée) question -> SPARQL -> résultats -> réponse
```

```
ontology/           # construction de l'ontologie (rdflib)
  namespace.py       # espace de noms partagé
  schema.py           # TBox : classes + propriétés + préfixes de noms
  instances.py        # ABox : individus + faits
  build.py             # sérialise schema.ttl / instances.ttl / ontology.ttl
  data/                 # fichiers .ttl générés

chatbot/            # chatbot LLM sur l'ontologie
  config.py           # variables d'environnement, chemin de l'ontologie
  llm.py               # client LLM (API compatible OpenAI)
  entity_matcher.py    # index flou des individus de l'ontologie
  resolver.py          # résolution des noms d'entités avant la chaîne SPARQL
  rdf_graph.py          # RdfGraph retirant les balises markdown du SPARQL
  graph_qa.py          # chaîne RdfGraph + GraphSparqlQAChain
  cli.py                # boucle de discussion + confirmation des corrections

tests/              # tests sans appel LLM (LLM simulé)
```

L'ontologie minimale décrit médecins, patients, maladies et hôpitaux via 4
propriétés d'objet (`treats`, `hasDisease`, `worksAt`, `specialistIn`) et une
propriété de donnée (`name`).

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install -e ".[dev]"          # optionnel : pytest, pre-commit, deptry
pre-commit install               # optionnel : hooks avant chaque commit
cp .env.example .env             # puis renseignez ARISTOTE_API_KEY
```

Le client LLM ([chatbot/llm.py](chatbot/llm.py)) accepte tout endpoint
compatible OpenAI (Aristote, OpenRouter...) via `ARISTOTE_API_KEY`,
`ARISTOTE_BASE_URL` et `ARISTOTE_MODEL`.

`ontology/` et `chatbot/` utilisent des imports relatifs. L'install éditable
enregistre le repo comme package dans le venv : toujours lancer les scripts
via `python -m <package>.<module>` (ex. `python -m ontology.build`), jamais en
exécution directe (`python ontology/build.py`).

## Utilisation

```bash
# 1. Générer l'ontologie (TBox + ABox -> ontology/data/*.ttl)
python -m ontology.build

# 2. Poser une question unique
python -m chatbot.cli "Quels médecins soignent des patients atteints de diabète ?"

# ... ou lancer une boucle interactive (sans argument)
python -m chatbot.cli

# Tests (sans LLM)
pytest tests
```

### Qualité du code

Hooks [pre-commit](.pre-commit-config.yaml) exécutés à chaque commit :
**ruff** (lint, imports/variables/arguments inutilisés, code commenté),
**black** (formatage, lignes de 100) et **vulture** (fonctions, classes et
attributs jamais utilisés). Configuration dans [pyproject.toml](pyproject.toml).

```bash
pre-commit run --all-files   # passe complète
```

pre-commit 4 requiert git ≥ 2.31.

Exemple de correction confirmée :

```
Question> Que peux-tu me dire du docteur Bornard ?
Vouliez-vous dire "Dr Bernard" au lieu de "docteur Bornard" ? [O/n]
Question reformulée : Que peux-tu me dire du "Dr Bernard" ?
```

## Résolution des entités

Implémentée dans [chatbot/resolver.py](chatbot/resolver.py) et
[chatbot/entity_matcher.py](chatbot/entity_matcher.py).

1. **Extraction** : le LLM renvoie les mentions d'individus *telles
   qu'écrites* et leur classe probable. Une question qui ne porte que sur des
   classes ne produit aucune mention et part telle quelle.
2. **Résolution** : `rapidfuzz.fuzz.ratio` sur chaînes normalisées
   (minuscules, sans accents ni ponctuation), comparées une 2e fois sans le
   préfixe usuel de la classe (`NAME_PREFIXES` dans
   [ontology/schema.py](ontology/schema.py) : "Bernard" → "Dr Bernard").
   La recherche est restreinte à la classe devinée, élargie à toute
   l'ontologie si elle ne donne rien.

   | Résultat | Action |
   |---|---|
   | identique après normalisation (accents, casse, préfixe) | corrigé d'office |
   | un candidat ≥ `FUZZY_SUGGEST_THRESHOLD` (défaut 75) | proposé à l'utilisateur |
   | plusieurs candidats à moins de 5 points | liste proposée |
   | aucun candidat | liste des individus de la classe proposée |

   Le seuil est bas car toute correction non triviale est validée par
   l'utilisateur (fautes de frappe ≥ 80, noms différents ≤ 40 sur
   l'ontologie actuelle). S'il garde sa formulation, elle est transmise
   telle quelle.
3. **Reformulation** : la mention est remplacée par le label canonique entre
   guillemets, que le LLM SPARQL recopie à l'identique.

Le choix de l'utilisateur passe par un callback (`Chooser`) : le resolver ne
fait aucune entrée/sortie, la CLI fournit l'implémentation terminal.

## Roadmap suivie

1. **v0 — Text-to-SPARQL brut.** `GraphSparqlQAChain` sur l'ontologie.
   Constat : échecs silencieux dès qu'un nom est mal orthographié ("Diabetes"
   au lieu de "Diabète", accents manquants) — la requête s'exécute et ne
   renvoie rien. Ajout de la propriété `ex:name` documentée dans le schéma,
   sans laquelle le LLM inventait un prédicat de nom.
2. **v1 — Fuzzy matching post-génération** (abandonné). Correction des
   littéraux dans la requête SPARQL générée, avant exécution, avec un seuil
   élevé (90) faute de confirmation. Limites : parsing positionnel fragile
   (seules les égalités étaient corrigeables, pas `CONTAINS` ni les URIs
   hallucinées), et fautes réelles sous le seuil ("Bornard"/"Bernard" = 86).
3. **v2 — Résolution en amont avec confirmation** (actuel). La correction
   porte sur la question, pas sur le SPARQL : la chaîne reste une boîte
   noire, et la validation par l'utilisateur autorise un seuil bas.

## Limites connues

- **Questions de description pauvres.** "Qui est Bob ?" génère
  `SELECT ?name … FILTER(?name = "Bob")` : la requête est correcte mais
  tautologique, la réponse ne dit rien. Le LLM ne sait pas qu'il faut
  renvoyer les relations de l'entité, *dans les deux sens* (le médecin de
  Bob n'est atteignable que par le triplet entrant `DrBernard treats Bob`).
- **Réponse déconnectée de l'entité.** Si les résultats SPARQL ne contiennent
  pas le nom de l'entité interrogée, le LLM de réponse ne fait pas le lien
  ("Dr Bernard" : Bob/Asthme/Pitié-Salpêtrière trouvés, réponse "aucune
  donnée").
- **Jointures sur-contraintes.** Le LLM ajoute des triplets non demandés qui
  éliminent des lignes sans le signaler. Ex. "quels patients sont soignés de
  quelles maladies et où ?" exige `?doctor specialistIn ?disease` : Chloé
  disparaît car le Dr Dupont n'a pas de spécialité.
- **Modélisation incomplète.** Aucune relation "soigné *pour* telle
  maladie" : `treats` relie médecin et patient, sans maladie. Le LLM
  improvise un lien (souvent `specialistIn`).
- **Concepts non validés.** Classes et propriétés ne sont pas vérifiées :
  "infirmier" peut être mappé silencieusement sur `Doctor`.
- **Dépendance à l'extraction.** Une mention non repérée par le LLM n'est pas
  corrigée ; deux mentions dont l'une contient l'autre peuvent être mal
  substituées (remplacement textuel de la 1re occurrence).
- **`langchain-community` en fin de vie** (avertissement de dépréciation à
  l'import) : `GraphSparqlQAChain` et `RdfGraph` devront être remplacés à
  terme.

## Améliorations envisagées

Par ordre de priorité :

1. **Route "décrire une entité" sans génération SPARQL.** L'extraction
   renvoie aussi une intention (`describe` / `query`). Pour `describe` avec
   une entité résolue (le resolver connaît déjà son URI, `Match.uri`), une
   requête fixe récupère son voisinage à 1 saut, sortant et entrant, avec
   les labels :

   ```sparql
   SELECT ?dir ?propLabel ?otherLabel WHERE {
     { ex:Bob ?p ?other . BIND("sortant" AS ?dir) }
     UNION
     { ?other ?p ex:Bob . BIND("entrant" AS ?dir) }
     ?p rdfs:label ?propLabel .
     ?other rdfs:label ?otherLabel .
   }
   ```

   Déterministe, testable sans LLM ; le LLM ne fait que rédiger.
2. **Prompts personnalisés de la chaîne** (`sparql_select_prompt`,
   `qa_prompt` de `GraphSparqlQAChain.from_llm`, la chaîne restant
   inchangée) : ne contraindre que ce que la question demande, mettre
   l'information annexe en `OPTIONAL`, parcourir les relations dans les deux
   sens, renvoyer les labels ; préciser au LLM de réponse à quelle entité se
   rapportent les résultats.
3. **Contexte d'entité pour toutes les questions.** Injecter le voisinage des
   entités résolues comme contexte de réponse, pas seulement pour
   `describe`.
4. **Diagnostic des jointures.** Si une requête renvoie moins de lignes
   qu'attendu, la relâcher contrainte par contrainte pour signaler "N
   résultats exclus par la condition X".
5. **Modélisation n-aire du traitement** (individu `Traitement` reliant
   médecin, patient et maladie), si le sens "soigné pour" doit être
   exprimable.
6. **Validation des concepts** (classes/propriétés) avec un seuil élevé, et
   refus explicite "concept inconnu de l'ontologie" plutôt qu'une
   substitution silencieuse.
7. **Interface web** : le callback `Chooser` se remplace par une
   interruption de graphe (ex. LangGraph) attendant la réponse utilisateur.
8. **Passage à l'échelle** : embeddings/vector store pour la résolution si
   l'ontologie grossit, et sortie de `langchain-community`.
