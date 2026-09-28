"""Explicitation des dates d'une question, en amont de GraphSparqlQAChain.

Le LLM qui écrit le SPARQL ne connaît pas la date du jour, et traduit mal les
dates en toutes lettres ou les périodes : "l'an dernier", "le 14 septembre
1951", "les années 50", "au XXe siècle".

Chaque expression de date reconnue est suivie, entre parenthèses, de sa
valeur explicite, comme les entités (voir resolver.py) ; la phrase reste
lisible :

- "le 14 septembre 1951" -> "le 14 septembre 1951 (1951-09-14)" ;
- "en septembre 1951" -> "en septembre 1951 (1951-09)" ;
- "l'an dernier" -> "l'an dernier (2025)", d'après la date du jour ;
- "les années 50" -> "les années 50 (de 1950 à 1959)" ;
- "au XXe siècle" -> "au XXe siècle (de 1901 à 2000)".

Une année seule ("en 1951") est déjà explicite : elle est laissée telle
quelle. "Les années 20" désigne les années 1920 : l'ontologie porte sur
l'histoire des prix, pas sur la décennie en cours.

Les superlatifs ("le dernier prix") ne sont pas traduits en année : le
dernier prix de l'ontologie n'est pas forcément celui de l'année en cours.
Le prompt SPARQL demande pour eux un tri (voir graph_qa.py).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date

MONTHS = (
    "janvier",
    "fevrier",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "aout",
    "septembre",
    "octobre",
    "novembre",
    "decembre",
)
_ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}

# Mois avec ou sans accents : "février" comme "fevrier".
_MONTH = r"(?P<{}>janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[ée]cembre)"

_PATTERNS = [
    # Les plus longs d'abord : "14 septembre 1951" avant "septembre 1951".
    ("day", rf"(?P<day>1er|\d{{1,2}})\s+{_MONTH.format('day_month')}\s+(?P<day_year>\d{{4}})"),
    ("numeric", r"(?P<num_day>\d{1,2})/(?P<num_month>\d{1,2})/(?P<num_year>\d{4})"),
    ("month", rf"{_MONTH.format('month')}\s+(?P<month_year>\d{{4}})"),
    ("decade", r"ann[ée]es\s+(?P<decade>\d0|\d{3}0)"),
    ("century", r"(?P<century>(?-i:[IVXLC]+)|\d{1,2})(?:e|ème|eme|è)\s+si[èe]cle"),
    ("ago", r"il\s+y\s+a\s+(?P<ago>\d+)\s+ans"),
    ("last_year", r"l'an\s+(?:dernier|pass[ée])|l'ann[ée]e\s+(?:derni[èe]re|pass[ée]e)"),
    ("this_year", r"cette\s+ann[ée]e"),
    ("next_year", r"l'an\s+prochain|l'ann[ée]e\s+prochaine"),
]
# Groupe `is_<type>` par type d'expression (lu par `match.lastgroup`).
# Pas d'annotation en double : l'expression ne doit pas être déjà suivie
# d'une parenthèse (question reformulée deux fois).
_DATES_RE = re.compile(
    r"\b(?:"
    + "|".join(f"(?P<is_{kind}>{pattern})" for kind, pattern in _PATTERNS)
    + r")\b(?!\s*\()",
    re.IGNORECASE,
)


def _month_number(name: str) -> int:
    ascii_name = unicodedata.normalize("NFKD", name.lower()).encode("ascii", "ignore").decode()
    return MONTHS.index(ascii_name) + 1


def _roman(numeral: str) -> int:
    values = [_ROMAN[c] for c in numeral.upper()]
    return sum(-v if v < nxt else v for v, nxt in zip(values, [*values[1:], 0], strict=True))


def _explicit(match: re.Match, today: date) -> str | None:
    """Valeur explicite d'une expression de date, None si invalide."""
    kind = match.lastgroup.removeprefix("is_")
    g = match.group
    try:
        if kind == "day":
            day = 1 if g("day").lower() == "1er" else int(g("day"))
            return date(int(g("day_year")), _month_number(g("day_month")), day).isoformat()
        if kind == "numeric":
            return date(int(g("num_year")), int(g("num_month")), int(g("num_day"))).isoformat()
    except ValueError:  # 30 février, mois 13...
        return None
    if kind == "month":
        return f"{g('month_year')}-{_month_number(g('month')):02d}"
    if kind == "decade":
        start = int(g("decade")) + (1900 if len(g("decade")) == 2 else 0)
        return f"de {start} à {start + 9}"
    if kind == "century":
        century = int(g("century")) if g("century").isdigit() else _roman(g("century"))
        return f"de {(century - 1) * 100 + 1} à {century * 100}"
    if kind == "ago":
        return str(today.year - int(g("ago")))
    offsets = {"last_year": -1, "this_year": 0, "next_year": 1}
    return str(today.year + offsets[kind])


def annotate_dates(question: str, today: date) -> str:
    """Fait suivre chaque expression de date de sa valeur explicite."""

    def annotate(match: re.Match) -> str:
        value = _explicit(match, today)
        return match.group(0) if value is None else f"{match.group(0)} ({value})"

    return _DATES_RE.sub(annotate, question)
