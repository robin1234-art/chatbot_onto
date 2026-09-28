"""Correction des types des littéraux d'une requête SPARQL générée.

Le LLM écrit souvent les nombres et les dates entre guillemets malgré la
consigne : `?a nobel:year "2024"` ou `FILTER(?y > "1950")`. En SPARQL, la
chaîne "2024" ne correspond pas à l'entier 2024 stocké : la requête s'exécute
sans erreur et ne renvoie rien.

La requête est donc corrigée de façon déterministe, d'après le schéma : la
portée (`rdfs:range`) de chaque propriété de donnée donne le type attendu.

1. dans les triplets, un littéral objet d'une propriété typée est converti
   vers ce type (`nobel:year "2024"` -> `nobel:year 2024`), et la variable
   objet d'une telle propriété hérite de son type (`nobel:year ?y`) ;
2. dans les comparaisons des filtres, un littéral comparé à une variable
   typée est converti vers le type de la variable (`?y > "1950"`), ou vers
   l'entier renvoyé par une fonction (`YEAR(?d) = "1951"`).

Les dates reçoivent un traitement propre, parce qu'une date partielle ("1951",
"1951-09") désigne une période et non un jour : elle ne peut être égale à
aucune date complète. Elle est remplacée par les bornes de la période :

- `?d > "2000"` devient `?d >= "2001-01-01"` (après l'an 2000) ;
- `?p nobel:birthDate "1951"` devient `?p nobel:birthDate ?v` filtré par
  `?v >= "1951-01-01" && ?v < "1952-01-01"`.

Une date complète écrite autrement ("14/09/1951", "1951-09-14T00:00:00Z")
est ramenée à `xsd:date`, et une date complète donnée pour une propriété
entière (`nobel:year "2024-10-11"`) est ramenée à son année.

La correction porte sur l'algèbre de la requête, pas sur son texte : pas
d'expression régulière sur du SPARQL, et rdflib exécute l'algèbre corrigée.
Un littéral non convertible ("années 50") ou porteur d'une langue est
laissé tel quel.
"""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from datetime import date

from rdflib import RDFS, XSD, Graph, Literal, URIRef, Variable
from rdflib.plugins.sparql import operators
from rdflib.plugins.sparql.algebra import Filter, traverse
from rdflib.plugins.sparql.parserutils import CompValue, Expr
from rdflib.plugins.sparql.sparql import Query

# Fonctions SPARQL dont le résultat est entier.
_INTEGER_BUILTINS = {
    "Builtin_YEAR",
    "Builtin_MONTH",
    "Builtin_DAY",
    "Builtin_HOURS",
    "Builtin_MINUTES",
}

# Période ["début", "fin") : un jour, un mois ou une année.
Period = tuple[date, date]

_ISO_RE = re.compile(r"(-?\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?(?:T[\d:.]+(?:Z|[+-]\d{2}:\d{2})?)?")
_FRENCH_RE = re.compile(r"(?:(\d{1,2})[/.])?(\d{1,2})[/.](\d{4})")


def _next_month(day: date) -> date:
    return date(day.year + day.month // 12, day.month % 12 + 1, 1)


def parse_period(text: str) -> Period | None:
    """Période désignée par une date complète ou partielle, None si illisible.

    Formats : AAAA, AAAA-MM, AAAA-MM-JJ (suivi ou non d'une heure),
    JJ/MM/AAAA et MM/AAAA.
    """
    text = text.strip()
    if match := _ISO_RE.fullmatch(text):
        year, month, day = match.groups()
    elif match := _FRENCH_RE.fullmatch(text):
        day, month, year = match.groups()
    else:
        return None
    try:
        if day is not None:
            start = date(int(year), int(month), int(day))
            return start, date.fromordinal(start.toordinal() + 1)
        if month is not None:
            start = date(int(year), int(month), 1)
            return start, _next_month(start)
        return date(int(year), 1, 1), date(int(year) + 1, 1, 1)
    except ValueError:  # mois 13, 30 février, année hors limites...
        return None


def _is_day(period: Period) -> bool:
    return period[1].toordinal() - period[0].toordinal() == 1


def _date(day: date) -> Literal:
    return Literal(day.isoformat(), datatype=XSD.date)


@contextmanager
def _quiet_rdflib():
    """rdflib journalise une pile d'erreur pour chaque littéral mal typé."""
    rdflib_logger = logging.getLogger("rdflib.term")
    level = rdflib_logger.level
    rdflib_logger.setLevel(logging.CRITICAL)
    try:
        yield
    finally:
        rdflib_logger.setLevel(level)


def datatype_ranges(graph: Graph) -> dict[URIRef, URIRef]:
    """Propriété -> type XSD de sa portée, hors chaînes (rien à convertir)."""
    return {
        prop: range_
        for prop, range_ in graph.subject_objects(RDFS.range)
        if isinstance(prop, URIRef) and str(range_).startswith(str(XSD)) and range_ != XSD.string
    }


def _coerce(literal: Literal, datatype: URIRef) -> Literal:
    """`literal` converti vers `datatype`, inchangé si impossible ou inutile.

    Une date partielle vers `xsd:date` n'est pas convertible : c'est une
    période, traitée par les appelants.
    """
    if literal.datatype == datatype or literal.language is not None:
        return literal
    text = str(literal).strip()
    if datatype == XSD.integer:
        if re.fullmatch(r"[+-]?\d+", text):
            return Literal(int(text), datatype=XSD.integer)
        # Une date complète pour une année : on garde l'année.
        period = parse_period(text)
        return (
            Literal(period[0].year, datatype=XSD.integer) if period and _is_day(period) else literal
        )
    if datatype == XSD.date:
        period = parse_period(text)
        return _date(period[0]) if period and _is_day(period) else literal
    with _quiet_rdflib():
        coerced = Literal(text, datatype=datatype)
        return literal if coerced.ill_typed else coerced


def _relation(left, op: str, right) -> Expr:
    return Expr(
        "RelationalExpression", operators.RelationalExpression, expr=left, op=op, other=right
    )


def _within(term, period: Period, op: str = "=") -> Expr:
    """`term op période`, exprimé avec les bornes de la période."""
    start, end = _date(period[0]), _date(period[1])
    if op == "<":
        return _relation(term, "<", start)
    if op == "<=":
        return _relation(term, "<", end)
    if op == ">":
        return _relation(term, ">=", end)
    if op == ">=":
        return _relation(term, ">=", start)
    if op == "!=":
        return Expr(
            "ConditionalOrExpression",
            operators.ConditionalOrExpression,
            expr=_relation(term, "<", start),
            other=[_relation(term, ">=", end)],
        )
    return Expr(
        "ConditionalAndExpression",
        operators.ConditionalAndExpression,
        expr=_relation(term, ">=", start),
        other=[_relation(term, "<", end)],
    )


# `"1950" < ?y` s'évalue comme `?y > "1950"`.
_FLIPPED = {"<": ">", ">": "<", "<=": ">=", ">=": "<=", "=": "=", "!=": "!="}


def coerce_literals(query: Query, ranges: dict[URIRef, URIRef]) -> int:
    """Corrige en place les littéraux mal typés de `query` ; renvoie leur nombre."""
    var_types: dict[Variable, URIRef] = {}
    fixes = 0
    fresh = 0

    def fix_triples(node):
        nonlocal fixes, fresh
        if not (isinstance(node, CompValue) and node.name == "BGP"):
            return None
        triples, conditions = [], []
        for s, p, o in node.triples:
            datatype = ranges.get(p)
            if datatype is not None:
                if isinstance(o, Variable):
                    var_types[o] = datatype
                elif isinstance(o, Literal) and (coerced := _coerce(o, datatype)) is not o:
                    o, fixes = coerced, fixes + 1
                elif (
                    datatype == XSD.date
                    and isinstance(o, Literal)
                    and o.language is None
                    and (period := parse_period(str(o)))
                    and not _is_day(period)
                ):
                    # Date partielle : une variable, filtrée par la période.
                    fresh += 1
                    var = Variable(f"_periode{fresh}")
                    var_types[var] = datatype
                    conditions.append(_within(var, period))
                    o, fixes = var, fixes + 1
            triples.append((s, p, o))
        node["triples"] = triples
        if not conditions:
            return None
        expr = conditions[0]
        if len(conditions) > 1:
            expr = Expr(
                "ConditionalAndExpression",
                operators.ConditionalAndExpression,
                expr=conditions[0],
                other=conditions[1:],
            )
        wrapped = Filter(expr, node)
        # evalFilter ne garde que les variables de `_vars` pour évaluer le filtre.
        node["_vars"] = {t for triple in triples for t in triple if isinstance(t, Variable)}
        wrapped["_vars"] = node["_vars"]
        return wrapped

    def side_type(term) -> URIRef | None:
        if isinstance(term, Variable):
            return var_types.get(term)
        if isinstance(term, CompValue) and term.name in _INTEGER_BUILTINS:
            return XSD.integer
        return None

    def fix_comparisons(node):
        nonlocal fixes
        if not (isinstance(node, CompValue) and node.name == "RelationalExpression"):
            return None
        # `expr op other` : on convertit le côté littéral d'après l'autre côté.
        for typed_side, lit_side in (("expr", "other"), ("other", "expr")):
            typed, lit = node.get(typed_side), node.get(lit_side)
            datatype = side_type(typed)
            if datatype is None or not isinstance(lit, Literal):
                continue
            if (coerced := _coerce(lit, datatype)) is not lit:
                node[lit_side] = coerced
                fixes += 1
                return None
            op = node.get("op")
            if datatype == XSD.date and op in _FLIPPED and lit.language is None:
                period = parse_period(str(lit))
                if period and not _is_day(period):
                    fixes += 1
                    return _within(typed, period, op if typed_side == "expr" else _FLIPPED[op])
        return None

    # Deux passes : les types des variables viennent de tous les triplets,
    # y compris ceux écrits après le filtre.
    traverse(query.algebra, visitPost=fix_triples)
    traverse(query.algebra, visitPost=fix_comparisons)
    return fixes
