# chatbot_onto
An ontology-based chatbot that combines LLMs with a formally constructed ontology, pairing natural-language understanding with structured, verifiable knowledge.

## Ontologie

Le chatbot interroge par défaut un **extrait de Wikidata sur les prix Nobel**
([ontology/data/nobel.ttl](ontology/data/nobel.ttl), ~52 000 triplets) :

| Classe | Individus | Exemples de relations |
|---|---|---|
| `Person` | 1 333 (lauréats + directeurs de thèse) | `citizenOf`, `bornIn`, `educatedAt`, `worksFor`, `doctoralAdvisor` |
| `Organization` | 33 (surtout prix de la paix) | `received`, `wonPrize` |
| `NobelAward` | 1 033 attributions | `category`, `year`, `motivation` |
| `NobelPrize` | 6 catégories | |
| `Institution` / `Place` / `Country` | 1 566 / 994 / 163 | `locatedIn` |

Wikidata n'est pas une ontologie OWL (pas de `owl:Class`, typage par
`wdt:P31`, identifiants opaques `P166`) : l'extraction
([ontology/nobel/extract.py](ontology/nobel/extract.py)) interroge le point
d'accès SPARQL de Wikidata et convertit le résultat vers un vocabulaire OWL
lisible (`nobel:`, [ontology/nobel/schema.py](ontology/nobel/schema.py)). Les
individus gardent leur IRI Wikidata (`wd:Q7186`), avec label (fr, repli
`mul` puis en), alias (`skos:altLabel`) et description (`rdfs:comment`).
L'extrait est versionné : Wikidata évolue, l'évaluation doit porter sur un
instantané fixe.

L'ontologie médicale jouet d'origine reste disponible
(`ONTOLOGY_PATH=ontology/data/ontology.ttl`) et sert aux tests.

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
  ├─ 3. reformulation               label canonique + IRI de l'individu
  │
  └─ GraphSparqlQAChain (inchangée) question -> SPARQL -> résultats -> réponse
```

```
ontology/           # construction des ontologies (rdflib)
  namespace.py       # espaces de noms partagés (dont chatbot:namePrefix)
  nobel/              # ontologie des prix Nobel (défaut)
    schema.py          # TBox : vocabulaire nobel: lisible
    extract.py         # extraction Wikidata -> data/nobel.ttl
  schema.py           # ontologie médicale jouet : TBox
  instances.py        # ontologie médicale jouet : ABox
  build.py             # sérialise schema.ttl / instances.ttl / ontology.ttl
  data/                 # fichiers .ttl générés

chatbot/            # chatbot LLM sur l'ontologie
  config.py           # variables d'environnement, chemin de l'ontologie
  llm.py               # client LLM (API compatible OpenAI)
  entity_matcher.py    # index flou des individus de l'ontologie
  resolver.py          # résolution des noms d'entités avant la chaîne SPARQL
  rdf_graph.py          # RdfGraph : balises markdown, exemples d'individus
  graph_qa.py          # chaîne RdfGraph + GraphSparqlQAChain, prompts FR
  cli.py                # boucle de discussion + confirmation des corrections

tests/              # tests sans appel LLM (LLM simulé)
```


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
# 1. (Optionnel) Réextraire l'ontologie Nobel depuis Wikidata (~2 min)
python -m ontology.nobel.extract
#    ... ou régénérer l'ontologie médicale jouet
python -m ontology.build

# 2. Poser une question unique
python -m chatbot.cli "Quels lauréats du Nobel de chimie ont étudié à Cambridge ?"

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

Exemples de corrections confirmées :

```
Question> Qui était le directeur de thèse de Richard Feynmann ?
Vouliez-vous dire "Richard Feynman" (Personne, physicien américain) au lieu de "Richard Feynmann" ? [O/n]
Question reformulée : Qui était le directeur de thèse de Richard Feynmann ("Richard Feynman" <http://www.wikidata.org/entity/Q39246>) ?

Question> Quels lauréats sont nés à Varsovie ?
"Varsovie" peut désigner plusieurs entités :
  1. Université de Varsovie (Établissement, université publique polonaise)
  2. Varsovie (Lieu, capitale de la Pologne)
  0. Garder "Varsovie"
```

## Résolution des entités

Implémentée dans [chatbot/resolver.py](chatbot/resolver.py) et
[chatbot/entity_matcher.py](chatbot/entity_matcher.py).

1. **Extraction** : le LLM renvoie les mentions d'individus *telles
   qu'écrites* et leur classe probable. Une question qui ne porte que sur des
   classes ne produit aucune mention et part telle quelle.
2. **Résolution** : `rapidfuzz.fuzz.ratio` sur chaînes normalisées
   (minuscules, sans accents ni ponctuation), comparées une 2e fois sans le
   préfixe usuel de la classe, lu dans l'ontologie (annotation
   `chatbot:namePrefix` : "Bernard" → "Dr Bernard", "Nobel de physique" →
   "prix Nobel de physique"). Seuls les littéraux de nom sont indexés
   (`rdfs:label`, `skos:altLabel` et leurs sous-propriétés). La recherche est
   restreinte à la classe devinée, élargie à toute l'ontologie si elle ne
   donne rien ; les homonymes exacts des autres classes sont toujours
   proposés ("Cambridge" : villes et université).

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
3. **Reformulation** : la mention est suivie du label canonique et de l'IRI
   de l'individu (`Français ("France" <…Q142>)`). Le LLM SPARQL utilise
   l'IRI sans jointure sur le nom, qui ne distingue pas les homonymes.

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
3. **v2 — Résolution en amont avec confirmation.** La correction
   porte sur la question, pas sur le SPARQL : la chaîne reste une boîte
   noire, et la validation par l'utilisateur autorise un seuil bas.
4. **v3 — Extrait Wikidata des prix Nobel** (actuel). Passage à l'échelle
   (≈ 17 700 noms indexés, ≈ 5 ms par recherche). Constats et corrections :
   - Wikidata place les noms propres dans la langue `mul`, sans label fr/en
     (Marie Curie n'avait pas de nom) : repli fr → mul → en.
   - Tous les littéraux étaient indexés : "femme" devenait l'alias de 67
     personnes. Index restreint aux propriétés de nom.
   - Homonymes ("Cambridge" ×2) : descriptions Wikidata affichées au choix,
     et IRI injectée dans la question, car une jointure sur le nom renvoyait
     les deux villes.
   - Le LLM inventait l'IRI des individus nommés par un nom commun
     (`nobel:Physics`) : exemples d'individus par classe ajoutés au schéma
     et au prompt d'extraction, prompt SPARQL en français.
   - `nobel:laureate` (Attribution → lauréat) était écrit à l'envers :
     renommé `nobel:received` (lauréat → Attribution).
   - Résultats vides complétés par les connaissances du LLM de réponse
     (hallucination masquée) : prompt de réponse restreint aux résultats.

## Limites connues

- **Extraction instable des noms communs.** "Nobel de littérature" est
  parfois repéré, parfois non ; sans IRI, le LLM SPARQL invente
  `nobel:prixNobelDeLitterature` ou compare une propriété d'objet à une chaîne.
- **SPARQL invalide occasionnel** (`SELECT COUNT(...)` sans alias) : l'erreur
  est affichée, sans nouvel essai.
- **Questions filtrées par année** ("Qui a gagné le prix Nobel de la paix en
  2024 ?") : échec, pour deux raisons cumulées.
  1. Le LLM déclare deux préfixes pour le même espace de noms
     (`PREFIX ex:` et `PREFIX nobel:` → `http://example.org/onto-nobel#`).
     rdflib (7.6) n'en retient qu'un : `Unknown namespace prefix : ex`,
     alors que la requête est du SPARQL valide.
  2. Même corrigée, la requête compare l'année à une chaîne
     (`nobel:year "2024"`) alors qu'elle est stockée en `xsd:integer` : aucun
     résultat. Avec `nobel:year 2024`, la réponse est bien *Nihon Hidankyō*.

  Pistes : normaliser les préfixes avant exécution (dans `CleanRdfGraph`),
  préciser le type dans le commentaire de `nobel:year` ("entier, sans
  guillemets"), ou renvoyer l'erreur au LLM pour un nouvel essai.

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
