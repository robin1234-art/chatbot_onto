"""Configuration du chatbot : accès LLM, chemin de l'ontologie, seuil flou."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ARISTOTE_API_KEY = os.environ.get("ARISTOTE_API_KEY")
ARISTOTE_BASE_URL = os.environ.get("ARISTOTE_BASE_URL", "https://openrouter.ai/api/v1")
ARISTOTE_MODEL = os.environ.get("ARISTOTE_MODEL", "openai/gpt-4o-mini")

# Ontologie interrogée : extrait Wikidata des prix Nobel.
_DATA_DIR = Path(__file__).resolve().parent.parent / "ontology" / "data"
ONTOLOGY_PATH = Path(os.environ.get("ONTOLOGY_PATH", _DATA_DIR / "nobel.ttl"))

# Score minimal (0-100, rapidfuzz.fuzz.ratio sur chaînes normalisées) pour
# proposer à l'utilisateur un individu de l'ontologie à la place d'un nom
# mal orthographié. Seuil bas : la correction est confirmée par l'utilisateur.
FUZZY_SUGGEST_THRESHOLD = float(os.environ.get("FUZZY_SUGGEST_THRESHOLD", "75"))
