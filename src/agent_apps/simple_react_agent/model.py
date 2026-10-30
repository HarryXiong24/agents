"""Block 1: load configuration and create the chat model."""

import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel
from langchain_groq import ChatGroq
from pydantic import SecretStr


def create_model() -> BaseChatModel:
    """Read configuration from the project root and create the chat model."""
    project_root = Path(__file__).resolve().parents[3]
    load_dotenv(project_root / ".env")
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("Set GROQ_API_KEY in the project root .env file.")

    return ChatGroq(
        model=os.getenv("AGENT_MODEL") or "openai/gpt-oss-20b",
        api_key=SecretStr(api_key),
        base_url=os.getenv("GROQ_BASE_URL") or "https://api.groq.com",
        temperature=0,
        timeout=30,
        max_retries=1,
    )
