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
  rdf_graph.py          # RdfGraph nettoyant les réponses markdown du LLM
  graph_qa.py          # chaîne RdfGraph + GraphSparqlQAChain
  cli.py                # boucle de discussion en ligne de commande
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

## Limites connues et plan de résolution (fuzzy matching)

Constat empirique (voir tests manuels) : le Text2SPARQL échoue silencieusement
dans deux cas distincts — une requête syntaxiquement valide qui ne retourne
rien, ou pire, qui s'exécute sur le mauvais concept sans le signaler.

1. **Valeurs d'instance mal orthographiées / mal traduites par le LLM**
   (ex. `Diabetes` généré au lieu de `Diabete`, accents manquants).
2. **Concepts (classes/propriétés) hallucinés ou substitués silencieusement**
   (ex. propriété `onto:name` inventée au lieu de `rdfs:label` ; "infirmier"
   mappé sans le dire sur `Doctor` faute de classe correspondante).

### Solution : fuzzy matching en validation post-génération

Point d'ancrage : [chatbot/rdf_graph.py](chatbot/rdf_graph.py) (`CleanRdfGraph`),
déjà responsable du nettoyage de la requête générée avant exécution. On y
ajoute une étape de validation/correction, avant que la requête soit exécutée
par rdflib :

1. **Extraire** les URIs/local names réellement utilisés dans la requête
   SPARQL générée (parsing via `rdflib.plugins.sparql.parser.parseQuery`).
2. **Séparer** ces termes en deux catégories, validées indépendamment :
   - *Concepts* (classes/propriétés) → comparés au vocabulaire du schéma
     ([ontology/schema.py](ontology/schema.py) : local names + `rdfs:label` +
     `rdfs:comment`).
   - *Valeurs d'instance* (URIs d'individus, littéraux de `FILTER`) →
     comparés aux `rdfs:label` des individus
     ([ontology/instances.py](ontology/instances.py)).
3. **Normaliser avant comparaison** : minuscule + suppression des accents +
   retrait d'un **set de préfixes connus par classe** (ex. `Doctor` →
   `{"dr", "docteur", "docteure"}`, `Hospital` → `{"hopital", "chu"}`), pour
   que "Bernard" matche `"Dr Bernard"` et "Hopital Saint Louis" matche
   `"Hôpital Saint-Louis"`.
4. **Fuzzy match** (ex. `rapidfuzz.fuzz.ratio`) entre le terme extrait et
   chaque candidat de l'index correspondant.
5. **Seuil de confiance différent par catégorie** :
   - *Valeurs d'instance* : seuil modéré (~80-85 %) — on cherche activement
     à corriger une faute de frappe/accent ; le risque de faux positif est
     limité (peu d'individus, labels distincts).
   - *Concepts* (classes/propriétés) : **seuil élevé** (~92-95 %+) — un
     mauvais concept mène silencieusement à une réponse sur la mauvaise
     entité (cf. infirmier → Doctor). En dessous du seuil, on **refuse
     d'exécuter** plutôt que de deviner, et on répond explicitement
     "concept inconnu de l'ontologie" plutôt que de laisser rdflib renvoyer
     un résultat vide sans explication.
6. **Si un match valide dépasse le seuil**, substituer le terme halluciné
   par l'URI/label canonique avant exécution (et le tracer dans les logs
   verbeux pour audit).

### Hors périmètre de cette itération

- Pas d'embeddings/vector store : le fuzzy matching lexical suffit vu la
  taille actuelle de l'ontologie (~10 individus, 4 classes). À revisiter si
  l'ontologie grossit significativement.
- Pas de boucle de régénération automatique du SPARQL par le LLM en cas de
  rejet sous le seuil — on se contente ici de répondre proprement plutôt que
  de renvoyer un résultat vide sans explication. Piste d'amélioration
  ultérieure : réinjecter les meilleurs candidats au LLM pour qu'il
  régénère lui-même la requête ("retrieve on empty result").
