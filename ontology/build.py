"""Assemble le schéma (TBox) et les instances (ABox) et sérialise le résultat.

Usage :
    python -m ontology.build

Produit trois fichiers dans ontology/data/ :
    - schema.ttl     : classes et propriétés seules
    - instances.ttl   : individus et faits seuls
    - ontology.ttl    : schéma + instances fusionnés (utilisé par le chatbot)
"""
from pathlib import Path

from .instances import build_instances
from .schema import build_schema

DATA_DIR = Path(__file__).resolve().parent / "data"


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)

    schema = build_schema()
    instances = build_instances()
    full = schema + instances

    schema.serialize(destination=DATA_DIR / "schema.ttl", format="turtle")
    instances.serialize(destination=DATA_DIR / "instances.ttl", format="turtle")
    full.serialize(destination=DATA_DIR / "ontology.ttl", format="turtle")

    print(f"Schéma      : {len(schema)} triplets -> {DATA_DIR / 'schema.ttl'}")
    print(f"Instances   : {len(instances)} triplets -> {DATA_DIR / 'instances.ttl'}")
    print(f"Ontologie   : {len(full)} triplets -> {DATA_DIR / 'ontology.ttl'}")


if __name__ == "__main__":
    main()
