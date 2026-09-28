"""Extrait de Wikidata les lauréats des prix Nobel et les sérialise en OWL.

Usage :
    python -m ontology.nobel.extract

Produit ontology/data/nobel.ttl (schéma + individus), versionné pour que le
chatbot et son évaluation portent sur un instantané fixe : Wikidata évolue.

Déroulé :
1. attributions : lauréat, prix, année et motivation (qualificatifs de P166) ;
2. faits sur les lauréats (nationalité, naissance, études, employeurs...) ;
3. pays des lieux et des établissements rencontrés ;
4. labels, alias et descriptions (fr, repli mul puis en) des entités rencontrées.

Chaque entité est typée d'après son rôle dans l'extrait (objet de P27 ->
Pays, de P69/P108 -> Établissement...) plutôt que par sa classe Wikidata,
trop fine et hétérogène (université publique, collège d'Oxford...).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from pathlib import Path

from rdflib import OWL, RDF, RDFS, SKOS, XSD, Graph, Literal, URIRef
from rdflib.namespace import DCTERMS

from ..namespace import NOBEL, WD
from .schema import build_schema

ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = "chatbot-onto/0.1 (extraction pédagogique des prix Nobel)"
BATCH_SIZE = 200
OUTPUT = Path(__file__).resolve().parent.parent / "data" / "nobel.ttl"

PRIZES = ("Q38104", "Q44585", "Q80061", "Q37922", "Q35637", "Q47170")
HUMAN = "Q5"
GENDERS = {"Q6581072": "femme", "Q6581097": "homme"}

# Faits sur les lauréats : propriété Wikidata -> propriété nobel
PERSON_LINKS = {
    "P27": NOBEL.citizenOf,
    "P19": NOBEL.bornIn,
    "P20": NOBEL.diedIn,
    "P69": NOBEL.educatedAt,
    "P108": NOBEL.worksFor,
    "P184": NOBEL.doctoralAdvisor,
}
# Classe de l'objet de chaque lien, d'après son rôle.
LINK_RANGES = {
    NOBEL.citizenOf: NOBEL.Country,
    NOBEL.bornIn: NOBEL.Place,
    NOBEL.diedIn: NOBEL.Place,
    NOBEL.educatedAt: NOBEL.Institution,
    NOBEL.worksFor: NOBEL.Institution,
    NOBEL.doctoralAdvisor: NOBEL.Person,
}
PERSON_VALUES = ("P31", "P21", "P569", "P570", "P734")
# "mul" : label multilingue par défaut, que Wikidata utilise pour les noms
# propres à la place des labels fr/en identiques.
LANGS = ("fr", "mul", "en")


def sparql(query: str, retries: int = 4) -> list[dict[str, dict]]:
    """Exécute une requête sur le point d'accès Wikidata (réessaie si limité)."""
    body = urllib.parse.urlencode({"query": query}).encode()
    request = urllib.request.Request(
        ENDPOINT,
        data=body,
        headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.load(response)["results"]["bindings"]
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == retries - 1:
                raise
            wait = int(error.headers.get("Retry-After") or 5 * (attempt + 1))
            print(f"  Wikidata indisponible ({error.code}), nouvel essai dans {wait} s")
            time.sleep(wait)
    raise RuntimeError("inatteignable")


def qid(binding: dict) -> str:
    return binding["value"].rsplit("/", 1)[-1]


def batches(ids: Iterable[str]) -> Iterable[str]:
    """Blocs `wd:Q1 wd:Q2 ...` pour une clause VALUES."""
    ids = sorted(ids)
    for i in range(0, len(ids), BATCH_SIZE):
        yield " ".join(f"wd:{q}" for q in ids[i : i + BATCH_SIZE])


def to_date(value: str) -> date | None:
    """Date Wikidata ("1879-03-14T00:00:00Z") -> date, None si inexploitable."""
    try:
        return date.fromisoformat(value[:10])
    except ValueError:  # année négative, date partielle mal formée...
        return None


def fetch_awards() -> list[tuple[str, str, int | None, str | None]]:
    """(lauréat, prix, année, motivation en anglais), dédoublonnés."""
    rows = sparql(f"""
        SELECT ?laureate ?prize ?date ?why WHERE {{
          VALUES ?prize {{ {" ".join(f"wd:{p}" for p in PRIZES)} }}
          ?laureate p:P166 ?st . ?st ps:P166 ?prize .
          OPTIONAL {{ ?st pq:P585 ?date }}
          OPTIONAL {{ ?st pq:P6208 ?why FILTER(LANG(?why) = "en") }}
        }}""")
    awards: dict[tuple[str, str, int | None], str | None] = {}
    for row in rows:
        day = to_date(row["date"]["value"]) if "date" in row else None
        key = (qid(row["laureate"]), qid(row["prize"]), day.year if day else None)
        awards[key] = awards.get(key) or (row["why"]["value"] if "why" in row else None)
    return [(*key, why) for key, why in awards.items()]


def fetch_values(ids: set[str], props: Iterable[str]) -> list[tuple[str, str, dict]]:
    """(sujet, propriété, valeur brute) pour les propriétés `props` des `ids`."""
    values = " ".join(f"wdt:{p}" for p in props)
    triples = []
    for block in batches(ids):
        for row in sparql(f"""
            SELECT ?s ?p ?o WHERE {{
              VALUES ?s {{ {block} }} VALUES ?p {{ {values} }}
              ?s ?p ?o .
            }}"""):
            triples.append((qid(row["s"]), qid(row["p"]), row["o"]))
    return triples


def fetch_labels(
    ids: set[str],
) -> tuple[dict[str, str], dict[str, set[str]], dict[str, str]]:
    """Label préféré (fr, sinon mul, sinon en), alias et description."""
    labels: dict[str, dict[str, str]] = defaultdict(dict)
    aliases: dict[str, set[str]] = defaultdict(set)
    descriptions: dict[str, dict[str, str]] = defaultdict(dict)
    langs = ", ".join(f'"{lang}"' for lang in LANGS)
    for block in batches(ids):
        for row in sparql(f"""
            SELECT ?e ?kind ?text WHERE {{
              VALUES ?e {{ {block} }}
              VALUES ?kind {{ rdfs:label skos:altLabel schema:description }}
              ?e ?kind ?text . FILTER(LANG(?text) IN ({langs}))
            }}"""):
            entity, text = qid(row["e"]), row["text"]["value"]
            lang, kind = row["text"]["xml:lang"], row["kind"]["value"]
            if kind.endswith("#label"):
                labels[entity][lang] = text
            elif kind.endswith("/description"):
                descriptions[entity][lang] = text
            else:
                aliases[entity].add(text)
    preferred = {}
    for entity, by_lang in labels.items():
        preferred[entity] = next(by_lang[lang] for lang in LANGS if lang in by_lang)
        # Le label dans l'autre langue sert d'alias ("Cambridge University").
        aliases[entity].update(by_lang.values())
    described = {
        entity: next(by_lang[lang] for lang in LANGS if lang in by_lang)
        for entity, by_lang in descriptions.items()
    }
    return preferred, aliases, described


def build_graph() -> Graph:
    g = build_schema()
    g.bind("wd", WD)
    types: dict[str, URIRef] = {}

    print("1/4 attributions des prix Nobel")
    awards = fetch_awards()
    laureates = {laureate for laureate, *_ in awards}
    for prize in PRIZES:
        types[prize] = NOBEL.NobelPrize

    print(f"2/4 faits sur {len(laureates)} lauréats")
    person_facts = fetch_values(laureates, [*PERSON_LINKS, *PERSON_VALUES])
    humans = {s for s, p, o in person_facts if p == "P31" and qid(o) == HUMAN}
    for laureate in laureates:
        types[laureate] = NOBEL.Person if laureate in humans else NOBEL.Organization

    family_names: dict[str, set[str]] = defaultdict(set)
    for s, p, o in person_facts:
        if s not in humans:
            continue
        subject = WD[s]
        if p in PERSON_LINKS:
            prop = PERSON_LINKS[p]
            types.setdefault(qid(o), LINK_RANGES[prop])
            g.add((subject, prop, WD[qid(o)]))
        elif p == "P21":
            g.add((subject, NOBEL.gender, Literal(GENDERS.get(qid(o), "autre"))))
        elif p in ("P569", "P570") and (day := to_date(o["value"])):
            prop = NOBEL.birthDate if p == "P569" else NOBEL.deathDate
            g.add((subject, prop, Literal(day, datatype=XSD.date)))
        elif p == "P734":
            family_names[s].add(qid(o))

    located = {e for e, cls in types.items() if cls in (NOBEL.Place, NOBEL.Institution)}
    print(f"3/4 pays de {len(located)} lieux et établissements")
    for s, _, o in fetch_values(located, ["P17"]):
        types.setdefault(qid(o), NOBEL.Country)
        g.add((WD[s], NOBEL.locatedIn, WD[qid(o)]))

    name_items = {item for items in family_names.values() for item in items}
    print(f"4/4 labels de {len(types) + len(name_items)} entités")
    labels, aliases, descriptions = fetch_labels(set(types) | name_items)

    for entity, cls in types.items():
        uri = WD[entity]
        label = labels.get(entity, entity)
        g.add((uri, RDF.type, cls))
        g.add((uri, RDFS.label, Literal(label, lang="fr")))
        g.add((uri, NOBEL.name, Literal(label)))
        if entity in descriptions:
            # Distingue les homonymes ("Cambridge" : ville d'Angleterre / du Massachusetts).
            g.add((uri, RDFS.comment, Literal(descriptions[entity])))
        for alias in aliases.get(entity, ()):
            if alias != label:
                g.add((uri, SKOS.altLabel, Literal(alias)))
        for item in family_names.get(entity, ()):
            if item in labels:
                g.add((uri, NOBEL.familyName, Literal(labels[item])))

    for laureate, prize, year, why in awards:
        award = NOBEL[f"award_{laureate}_{prize}_{year or 'unknown'}"]
        g.add((award, RDF.type, NOBEL.NobelAward))
        g.add((WD[laureate], NOBEL.received, award))
        g.add((award, NOBEL.category, WD[prize]))
        g.add((WD[laureate], NOBEL.wonPrize, WD[prize]))
        # Pas de label : l'attribution n'est pas une entité que l'on nomme,
        # et elle encombrerait l'index flou du chatbot.
        if year is not None:
            g.add((award, NOBEL.year, Literal(year, datatype=XSD.integer)))
        if why:
            g.add((award, NOBEL.motivation, Literal(why, lang="en")))

    ontology = URIRef(str(NOBEL).rstrip("#"))
    g.add((ontology, RDF.type, OWL.Ontology))
    g.add((ontology, DCTERMS.source, URIRef("https://www.wikidata.org")))
    g.add((ontology, DCTERMS.created, Literal(date.today(), datatype=XSD.date)))
    return g


def main() -> None:
    graph = build_graph()
    OUTPUT.parent.mkdir(exist_ok=True)
    graph.serialize(destination=OUTPUT, format="turtle")
    counts = defaultdict(int)
    for cls in graph.objects(None, RDF.type):
        counts[cls] += 1
    print(f"\n{len(graph)} triplets -> {OUTPUT}")
    for cls in (NOBEL.Person, NOBEL.Organization, NOBEL.NobelAward, NOBEL.Institution):
        print(f"  {cls.split('#')[-1]:<13} {counts[cls]}")
    print(f"  {'Country':<13} {counts[NOBEL.Country]}\n  {'Place':<13} {counts[NOBEL.Place]}")


if __name__ == "__main__":
    main()
