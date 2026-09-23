"""RdfGraph qui nettoie et corrige les requêtes SPARQL générées par le LLM.

`GraphSparqlQAChain` transmet le texte généré par le LLM tel quel à
`RdfGraph.query`/`update`. Deux corrections sont appliquées avant exécution :

1. Beaucoup de modèles de chat entourent leur réponse de balises
   ```sparql ... ``` malgré la consigne du prompt de ne renvoyer que la
   requête, ce qui fait échouer le parseur SPARQL de rdflib sur le backtick.
2. Les noms d'entités mal orthographiés sont remplacés par le label canonique
   de l'individu le plus proche (voir entity_matcher.py).
"""
import re

from langchain_community.graphs import RdfGraph

from ontology.schema import NAME_PREFIXES

from .config import FUZZY_INSTANCE_THRESHOLD
from .entity_matcher import InstanceIndex, correct_instance_literals

_CODE_FENCE_RE = re.compile(r"^```[a-zA-Z]*\n?|\n?```$", re.MULTILINE)


def _strip_code_fence(query: str) -> str:
    return _CODE_FENCE_RE.sub("", query).strip()


class CleanRdfGraph(RdfGraph):
    """RdfGraph qui nettoie les balises markdown et corrige les noms d'entités."""

    def __init__(self, *args, fuzzy_threshold: float = FUZZY_INSTANCE_THRESHOLD, **kwargs):
        self.fuzzy_threshold = fuzzy_threshold
        # Le constructeur parent charge le schéma via self.query : pas de
        # correction tant que l'index n'est pas construit.
        self.instance_index = None
        super().__init__(*args, **kwargs)
        self.instance_index = InstanceIndex.from_graph(self.graph, NAME_PREFIXES)

    def query(self, query: str):
        query = _strip_code_fence(query)
        if self.instance_index is not None:
            query = correct_instance_literals(query, self.instance_index, self.fuzzy_threshold)
        return super().query(query)

    def update(self, query: str) -> None:
        return super().update(_strip_code_fence(query))
