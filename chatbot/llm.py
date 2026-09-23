"""Client LLM pointant vers Aristote (API compatible OpenAI)."""

from langchain_openai import ChatOpenAI

from .config import ARISTOTE_API_KEY, ARISTOTE_BASE_URL, ARISTOTE_MODEL


def get_llm(temperature: float = 0.0) -> ChatOpenAI:
    if not ARISTOTE_API_KEY:
        raise RuntimeError(
            "ARISTOTE_API_KEY manquante : copiez .env.example vers .env "
            "et renseignez votre clé Aristote."
        )
    return ChatOpenAI(
        model=ARISTOTE_MODEL,
        api_key=ARISTOTE_API_KEY,
        base_url=ARISTOTE_BASE_URL,
        temperature=temperature,
        timeout=60,
    )
