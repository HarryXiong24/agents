from langchain_groq import ChatGroq
from pydantic import SecretStr

from ..config import AGENT_MODEL, BASE_URL, GROQ_API_KEY


def create_model() -> ChatGroq:
    """Build a Groq model using credentials loaded from the project's .env."""
    return ChatGroq(
        model=AGENT_MODEL,
        api_key=SecretStr(GROQ_API_KEY) if GROQ_API_KEY else None,
        base_url=BASE_URL,
        # The Groq SDK waits for Retry-After on 429 responses before retrying.
        max_retries=3,
    )
