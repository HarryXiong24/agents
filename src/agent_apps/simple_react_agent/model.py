"""Block 1: load configuration and create the chat model."""

from langchain_core.language_models import BaseChatModel
from langchain_groq import ChatGroq
from pydantic import SecretStr

from . import config


def create_model() -> BaseChatModel:
    """Create the model using only this agent's .env configuration."""
    env = config.read_env()
    api_key = env.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(f"Set GROQ_API_KEY in {config.ENV_FILE}.")

    return ChatGroq(
        model=env.get("AGENT_MODEL") or "openai/gpt-oss-20b",
        api_key=SecretStr(api_key),
        base_url=env.get("GROQ_BASE_URL") or "https://api.groq.com",
        temperature=0,
        timeout=30,
        max_retries=1,
    )
