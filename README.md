# chatbot_onto
An ontology-based chatbot that combines LLMs with a formally constructed ontology, pairing natural-language understanding with structured, verifiable knowledge.

## Ontologie

Le chatbot interroge par défaut un **extrait de Wikidata sur les prix Nobel**
([ontology/data/nobel.ttl](ontology/data/nobel.ttl), ~54 000 triplets) :

| Classe | Individus | Exemples de relations |
|---|---|---|
| `Person` | 1 333 (lauréats + directeurs de thèse) | `citizenOf`, `bornIn`, `educatedAt`, `worksFor`, `doctoralAdvisor`, `birthDate`/`birthYear` |
| `Organization` | 31 (surtout prix de la paix) | `received`, `wonPrize` |
| `NobelAward` | 1 031 attributions | `category`, `year`, `motivation` |
| `NobelPrize` | 6 catégories | |
| `Institution` / `Place` / `Country` | 1 566 / 994 / 163 | `locatedIn` |

Wikidata n'est pas une ontologie OWL (pas de `owl:Class`, typage par
`wdt:P31`, identifiants opaques `P166`) : l'extraction
([ontology/extract.py](ontology/extract.py)) interroge le point
d'accès SPARQL de Wikidata et convertit le résultat vers un vocabulaire OWL
lisible (`nobel:`, [ontology/schema.py](ontology/schema.py)). Les
individus gardent leur IRI Wikidata (`wd:Q7186`), avec label (fr, repli
`mul` puis en), alias (`skos:altLabel`) et description (`rdfs:comment`).
L'extrait est versionné : Wikidata évolue, l'évaluation doit porter sur un
instantané fixe.

Dates : Wikidata stocke une date connue à l'année près au 1er janvier
(précision 9). L'extraction lit la précision : l'année est toujours stockée
(`nobel:birthYear`, `nobel:deathYear`, entiers), la date complète
(`nobel:birthDate`, `xsd:date`) seulement si elle est connue au jour près.
Les attributions sans date (personnage de fiction, famille entière) sont
écartées.

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
  ├─ 4. dates (regex, sans LLM)     valeur explicite des dates et périodes
  │
  └─ GraphSparqlQAChain             question -> SPARQL -> résultats -> réponse
         └─ CleanRdfGraph           nettoyage déterministe avant exécution :
                                    balises, préfixes en double, sens des
                                    triplets, individus, types et dates
```

```
ontology/           # ontologie des prix Nobel (rdflib)
  namespace.py       # espaces de noms partagés (dont chatbot:namePrefix)
  schema.py          # TBox : vocabulaire nobel: lisible
  extract.py         # extraction Wikidata -> data/nobel.ttl
  data/nobel.ttl     # extrait versionné

chatbot/            # chatbot LLM sur l'ontologie
  config.py           # variables d'environnement, chemin de l'ontologie
  llm.py               # client LLM (API compatible OpenAI)
  entity_matcher.py    # index flou des individus de l'ontologie
  resolver.py          # résolution des noms d'entités avant la chaîne SPARQL
  dates.py              # explicitation des dates de la question
  rdf_graph.py          # RdfGraph : nettoyage des requêtes, exemples d'individus
  triple_direction.py   # remise des triplets dans le sens du schéma
  individuals.py        # individus désignés par leur nom ou une IRI inventée
  typed_literals.py     # conversion des littéraux (nombres, dates, périodes)
  graph_qa.py          # chaîne RdfGraph + GraphSparqlQAChain, prompts FR
  cli.py                # boucle de discussion + confirmation des corrections

tests/              # tests sans appel LLM, sur un petit graphe Nobel (conftest.py)
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
via `python -m <package>.<module>` (ex. `python -m ontology.extract`), jamais en
exécution directe (`python ontology/extract.py`).

## Utilisation

```bash
# 1. (Optionnel) Réextraire l'ontologie Nobel depuis Wikidata (~2 min)
python -m ontology.extract
#    ... ou n'y remplacer que le schéma, après modification de schema.py
python -m ontology.extract --schema-only

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
   `chatbot:namePrefix` : "Nobel de physique" → "prix Nobel de physique",
   "Cambridge" → "université de Cambridge"). Seuls les littéraux de nom sont indexés
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

## Corrections de la requête générée

`CleanRdfGraph.query` analyse la requête générée avec rdflib (`parseQuery` +
`translateQuery`) et corrige son **algèbre**, pas son texte, avant de
l'exécuter. Chaque correction est déterministe, fondée sur le schéma, et
tracée dans la CLI (`[sens]`, `[individus]`, `[types]`). Le SPARQL affiché
reste celui du LLM.

Ces défauts produisent tous une requête valide qui ne renvoie rien, sans
erreur. Une consigne du prompt ne suffit pas à les éviter : le LLM les
reproduit malgré elle, d'un tirage à l'autre.

### Sens des triplets

[chatbot/triple_direction.py](chatbot/triple_direction.py). Le LLM écrit
`?attribution nobel:received ?laureat` au lieu de
`?laureat nobel:received ?attribution`. Les classes des termes sont déduites
des typages (`?a a nobel:NobelAward`), du domaine et de la portée des *autres*
triplets, et du graphe pour les IRI d'individus. Un triplet dont le sujet est
de la classe de la portée (ou l'objet de celle du domaine) est inversé. Une
propriété dont domaine et portée coïncident (`doctoralAdvisor`) n'est jamais
inversée.

### Individus mal désignés

[chatbot/individuals.py](chatbot/individuals.py). Même quand la question
fournit l'IRI, le LLM écrit parfois `nobel:category "prix Nobel de la paix"`
(un nom) ou `nobel:category nobel:physics` (une IRI inventée). L'objet d'une
propriété d'objet est remplacé par l'individu de la classe de la portée qui
porte exactement ce nom, ou par l'IRI de cette classe citée dans la question.
Sans candidat unique, il est laissé tel quel.

### Types des littéraux et dates

[chatbot/typed_literals.py](chatbot/typed_literals.py). La portée
(`rdfs:range`) de chaque propriété de donnée donne le type attendu
(`nobel:year` → `xsd:integer`, `nobel:birthDate` → `xsd:date`).

| Écrit par le LLM | Exécuté |
|---|---|
| `nobel:year "2024"` | `nobel:year 2024` |
| `FILTER(?y > "1950")`, `?y` lié à `nobel:year` | `FILTER(?y > 1950)` |
| `FILTER(YEAR(?b) = "1913")` | `FILTER(YEAR(?b) = 1913)` |
| `nobel:year "2024-10-11"` | `nobel:year 2024` |
| `nobel:birthDate "14/09/1951"` ou `"1951-09-14T00:00:00Z"` | `nobel:birthDate "1951-09-14"^^xsd:date` |
| `FILTER(?b > "2000")` sur un `xsd:date` | `FILTER(?b >= "2001-01-01"^^xsd:date)` |
| `nobel:birthDate "1913"` (ou `"1913"^^xsd:gYear`) | `nobel:birthDate ?v` + `FILTER(?v >= "1913-01-01" && ?v < "1914-01-01")` |

Une date partielle ("1951", "1951-09") désigne une **période** : elle n'est
égale à aucune date complète. Elle est remplacée par ses bornes, pour chaque
opérateur (`=`, `!=`, `<`, `<=`, `>`, `>=`), des deux côtés de l'opérateur et
dans les filtres imbriqués. Un littéral non convertible (`"années 50"`) ou
porteur d'une langue est laissé tel quel.

Non couvert : `IN (...)`, dates comparées à une fonction autre que
`YEAR`/`MONTH`/`DAY`.

## Dates de la question

[chatbot/dates.py](chatbot/dates.py), après la résolution des entités. Le
LLM ne connaît pas la date du jour et traduit mal les périodes. Chaque
expression reconnue est suivie de sa valeur explicite, comme les entités :

| Question | Reformulée |
|---|---|
| le 14 septembre 1951, le 14/09/1951 | … (1951-09-14) |
| en août 1951 | … (1951-08) |
| l'an dernier, cette année, il y a 10 ans | … (2025), (2026), (2016) |
| les années 50 | … (de 1950 à 1959) |
| au XXe siècle | … (de 1901 à 2000) |

Une année seule est déjà explicite et reste telle quelle. « Le dernier prix »
n'est pas traduit en année (le dernier prix de l'extrait n'est pas forcément
celui de l'année en cours) : le prompt SPARQL demande l'année maximale par
une sous-requête, sans `LIMIT`, pour garder tous les co-lauréats.

Le résolveur d'entités retire aussi l'année accolée à une mention (« prix
Nobel de la paix 2024 » → « prix Nobel de la paix ») : sinon, la
correspondance n'était plus exacte et l'utilisateur devait confirmer.

## Roadmap suivie

Les étapes v0 à v2 portaient sur une ontologie médicale jouet (médecins,
patients, maladies), retirée depuis.

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
   - Questions filtrées par année ("Qui a gagné le prix Nobel de la paix en
     2024 ?") en échec, pour deux raisons cumulées. Le LLM déclarait deux
     préfixes pour le même espace de noms (`ex:` et `nobel:`), que rdflib
     7.6 refuse (`Unknown namespace prefix : ex`) : `CleanRdfGraph` ramène
     les doublons au premier préfixe. Il comparait aussi l'année à une chaîne
     (`nobel:year "2024"`, stockée en `xsd:integer`). Une consigne du prompt
     ("nombres sans guillemets") n'a pas suffi : remplacée par une conversion
     déterministe d'après les types du schéma (voir
     [Corrections de la requête générée](#corrections-de-la-requête-générée)).
   - « Quel est le prix Nobel de la paix 2024 ? » restait sans réponse
     malgré le typage : le LLM inversait `nobel:received` malgré son
     renommage, écrivait le nom de la catégorie au lieu de son IRI, ou
     inventait `nobel:physics`. Ces défauts sont désormais corrigés dans
     l'algèbre, d'après le domaine et la portée des propriétés. Les dates
     sont traitées de bout en bout : précision Wikidata à l'extraction,
     années entières dans le schéma, périodes dans les requêtes, dates
     relatives explicitées dans la question.

## Limites connues

- **Extraction instable des noms communs.** "Nobel de littérature" est
  parfois repéré, parfois non. Sans IRI dans la question, un nom exact
  écrit comme littéral est corrigé, mais pas une IRI inventée
  (`nobel:prixNobelDeLitterature`).
- **SPARQL invalide occasionnel** (`SELECT COUNT(...)` sans alias) : l'erreur
  est affichée, sans nouvel essai.
- **Contraintes logiques ajoutées.** "Lauréats du Nobel de physique nés avant
  1860" génère aussi `FILTER(?annee < 1860)` sur l'année du prix : la
  requête est bien typée mais fausse, aucun résultat.

- **Questions de description pauvres.** "Qui est Marie Curie ?" peut générer
  `SELECT ?name … FILTER(?name = "Marie Curie")` : la requête est correcte
  mais tautologique, la réponse ne dit rien. Le LLM ne sait pas qu'il faut
  renvoyer les relations de l'entité, *dans les deux sens* (les doctorants
  d'une personne ne sont atteignables que par le triplet entrant
  `?doctorant nobel:doctoralAdvisor ?personne`).
- **Réponse déconnectée de l'entité.** Si les résultats SPARQL ne contiennent
  pas le nom de l'entité interrogée, le LLM de réponse ne fait pas le lien
  et peut répondre "aucune donnée" malgré des résultats.
- **Résultats SPARQL peu interprétables par le LLM de réponse.** Il ne
  reçoit que la question et une liste brute de tuples
  (`[(Literal('Nihon Hidankyō'),)]`) : ni le nom des colonnes, ni la requête
  exécutée, ni les conditions appliquées (année, catégorie, « le dernier »),
  ni les corrections faites par `CleanRdfGraph`. Il doit deviner ce que
  représentent les valeurs, et doute parfois de résultats corrects. Ex. « qui
  a reçu le dernier prix Nobel de physique ? » : requête juste, mais réponse
  « les résultats ne précisent pas qui a reçu le dernier prix », l'année
  n'étant pas dans les colonnes. Une consigne du prompt de réponse atténue le
  problème sans le régler.
- **Jointures sur-contraintes.** Le LLM ajoute des triplets non demandés qui
  éliminent des lignes sans le signaler (un triplet obligatoire au lieu
  d'un `OPTIONAL` : les lauréats sans cette information disparaissent).
- **Concepts non validés.** Classes et propriétés ne sont pas vérifiées :
  un concept absent de l'ontologie peut être mappé silencieusement sur une
  classe ou une propriété voisine.
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
     { wd:Q7186 ?p ?other . BIND("sortant" AS ?dir) }
     UNION
     { ?other ?p wd:Q7186 . BIND("entrant" AS ?dir) }
     ?p rdfs:label ?propLabel .
     ?other rdfs:label ?otherLabel .
   }
   ```

   Déterministe, testable sans LLM ; le LLM ne fait que rédiger.
2. **Retravailler l'interprétabilité des résultats SPARQL** transmis au
   LLM de reformulation, pour qu'il comprenne ce que la requête a fait :
   - résultats présentés en tableau avec le nom des colonnes (`?laureat`,
     `?annee`), dates et nombres lisibles, labels plutôt qu'IRI ;
   - résumé en langage naturel de la requête **corrigée** (celle réellement
     exécutée, pas le texte du LLM) : entités ciblées, conditions et filtres
     (« catégorie = prix Nobel de physique, année = année maximale »),
     tris et agrégats ;
   - variables de filtrage ajoutées aux colonnes renvoyées (année,
     catégorie), pour que la réponse puisse les citer ;
   - corrections appliquées par `CleanRdfGraph` (`[sens]`, `[individus]`,
     `[types]`) signalées au LLM ;
   - distinction explicite entre « aucun résultat » et « résultat
     partiel » (colonnes `OPTIONAL` vides).
3. **Prompts personnalisés de la chaîne** (`sparql_select_prompt`,
   `qa_prompt` de `GraphSparqlQAChain.from_llm`, la chaîne restant
   inchangée) : ne contraindre que ce que la question demande, mettre
   l'information annexe en `OPTIONAL`, parcourir les relations dans les deux
   sens, renvoyer les labels ; préciser au LLM de réponse à quelle entité se
   rapportent les résultats.
4. **Contexte d'entité pour toutes les questions.** Injecter le voisinage des
   entités résolues comme contexte de réponse, pas seulement pour
   `describe`.
5. **Diagnostic des jointures.** Si une requête renvoie moins de lignes
   qu'attendu, la relâcher contrainte par contrainte pour signaler "N
   résultats exclus par la condition X".
6. **Validation des concepts** (classes/propriétés) avec un seuil élevé, et
   refus explicite "concept inconnu de l'ontologie" plutôt qu'une
   substitution silencieuse.
7. **Interface web** : le callback `Chooser` se remplace par une
   interruption de graphe (ex. LangGraph) attendant la réponse utilisateur.
8. **Passage à l'échelle** : embeddings/vector store pour la résolution si
   l'ontologie grossit, et sortie de `langchain-community`.
