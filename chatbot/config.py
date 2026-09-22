"""Configuration du chatbot : clé OpenRouter et chemin de l'ontologie."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")

ARISTOTE_API_KEY = os.environ.get("ARISTOTE_API_KEY")
ARISTOTE_BASE_URL = os.environ.get("ARISTOTE_BASE_URL", "https://openrouter.ai/api/v1")
ARISTOTE_MODEL = os.environ.get("ARISTOTE_MODEL", "openai/gpt-4o-mini")

ONTOLOGY_PATH = Path(__file__).resolve().parent.parent / "ontology" / "data" / "ontology.ttl"
