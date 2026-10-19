"""Model factory: Qwen served by a local Ollama.

📘 LEARN — why a factory function instead of a module-level `model = ChatOllama(...)`?
    • Importing the module has no side effects (tests import graph code without Ollama).
    • One place to swap providers: return ChatOpenAI(...) / ChatAnthropic(...) here and
      nothing else changes, because the graph only depends on the BaseChatModel interface
      (`ainvoke`, `bind_tools`).

📘 LEARN — what ChatOllama does on each call:
    LangChain messages + tool schemas  ──▶  POST {base_url}/api/chat  ──▶  Ollama runs Qwen
    Qwen's tool-call output (JSON)     ◀──  parsed into AIMessage.tool_calls
    Tool calling only works with models whose Ollama template supports it (Qwen2.5+/Qwen3 do).
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel

from .config import settings


def get_chat_model() -> BaseChatModel:
    from langchain_ollama import ChatOllama  # lazy import: only needed when actually running

    return ChatOllama(
        model=settings.model,
        base_url=settings.base_url,
        temperature=settings.temperature,
        num_ctx=settings.num_ctx,      # ⚠ PITFALL: Ollama's default window is tiny; raise it
        reasoning=settings.reasoning,  # Qwen3 <think> mode; when on, thoughts go to
                                       # additional_kwargs, not content, so parsing stays clean
    )


def get_embeddings():
    """Return an Ollama embeddings object, or None if semantic memory is disabled.

    Used by the long-term Store to turn memory text into vectors (see main.py `index=`).
    🧪 TRY:  ollama pull nomic-embed-text && OLLAMA_EMBED_MODEL=nomic-embed-text python main.py
    """
    if not settings.embed_model:
        return None
    from langchain_ollama import OllamaEmbeddings

    return OllamaEmbeddings(model=settings.embed_model, base_url=settings.base_url)
