"""Create the chat model from application settings supplied by the caller."""

from langchain_core.language_models import BaseChatModel
from langchain_groq import ChatGroq

from ..config import ModelConfig


def create_model(settings: ModelConfig) -> BaseChatModel:
    """Build the client; configuration loading and validation happen in the config package."""
    return ChatGroq(
        model=settings.model,
        api_key=settings.api_key,
        base_url=settings.base_url,
        temperature=settings.temperature,
        timeout=settings.timeout,
        max_retries=settings.max_retries,
    )
