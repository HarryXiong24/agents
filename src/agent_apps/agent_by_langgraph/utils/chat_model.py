from langchain_groq import ChatGroq

from ..config import AGENT_MODEL, BASE_URL, GROQ_API_KEY


def create_model() -> ChatGroq:
    """Build a Groq model using credentials loaded from the project's .env."""
    return ChatGroq(
        model=AGENT_MODEL,
        api_key=GROQ_API_KEY,
        base_url=BASE_URL,
    )
