"""Model factory: chat models served by Groq.

📘 LEARN — why a factory function instead of a module-level `model = ChatGroq(...)`?
    • Importing the module needs no API key (tests import graph code without Groq).
    • One place to swap providers: return ChatOpenAI(...) / ChatAnthropic(...) here and
      nothing else changes, because the graph only depends on the BaseChatModel interface
      (`ainvoke`, `bind_tools`).

📘 LEARN — what ChatGroq does on each call:
    LangChain messages + tool schemas  ──▶  POST /openai/v1/chat/completions  ──▶  Groq
    The model's tool-call output (JSON) ◀── parsed into AIMessage.tool_calls
    Choose a Groq model that supports tool calling.
"""

from __future__ import annotations

import os

from langchain_core.language_models import BaseChatModel

from .config import PROJECT_ROOT, settings


def get_chat_model() -> BaseChatModel:
    from langchain_groq import ChatGroq  # lazy import: only needed when actually running

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError(f"Set GROQ_API_KEY in {PROJECT_ROOT / '.env'} or your environment.")

    return ChatGroq(
        model=settings.model,
        api_key=api_key,
        base_url=settings.base_url,
        temperature=settings.temperature,
        max_retries=3,
    )
