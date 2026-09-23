"""RdfGraph qui nettoie les requêtes SPARQL générées par le LLM.

`GraphSparqlQAChain` transmet le texte généré par le LLM tel quel à
`RdfGraph.query`/`update`. Or beaucoup de modèles de chat entourent leur
réponse de balises ```sparql ... ``` malgré la consigne du prompt de ne
renvoyer que la requête, ce qui fait échouer le parseur SPARQL de rdflib sur
le backtick.

Les noms d'entités mal orthographiés sont corrigés en amont, sur la
question elle-même (voir resolver.py).
"""

import re

from langchain_community.graphs import RdfGraph

_CODE_FENCE_RE = re.compile(r"^```[a-zA-Z]*\n?|\n?```$", re.MULTILINE)


def _strip_code_fence(query: str) -> str:
    return _CODE_FENCE_RE.sub("", query).strip()


class CleanRdfGraph(RdfGraph):
    """RdfGraph qui retire les balises markdown avant d'exécuter une requête."""

    def query(self, query: str):
        return super().query(_strip_code_fence(query))

    def update(self, query: str) -> None:
        return super().update(_strip_code_fence(query))
