"""Memory management.

📘 LEARN — an agent's "memory" is really three different mechanisms:

  1. Short-term  — the message list of ONE thread (conversation).
                   Persisted by the checkpointer (SQLite) after every super-step,
                   keyed by thread_id. Gone from view when you start a new thread.
                   → configured in main.py (AsyncSqliteSaver)

  2. Compaction  — when that thread grows past a token budget, old messages are
                   summarised into `state.summary` and deleted.
                   → graph.py: compact_context

  3. Long-term   — facts about the USER that survive across threads, stored in a
                   LangGraph Store (key-value + optional vector search), namespaced
                   by user_id. Recalled at the start of each turn; written by tools.
                   → this file

    thread A ──┐                                     ┌── thread B (days later)
    "I prefer  │   save_memory ──▶ Store ──▶ recall  │   "how should you format
     bullets"  │        ("memories", "harry")        │    answers for me?"
               ┘                                     └── system prompt includes the fact

📘 LEARN — the Store data model:
    namespace : tuple path, like a folder   → ("memories", "harry")
    key       : unique id within namespace  → "a1b2c3d4"
    value     : a JSON dict                 → {"content": "...", "created_at": "..."}
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from langgraph.store.base import BaseStore

from .config import settings


def namespace(user_id: str) -> tuple[str, ...]:
    # Namespacing by user is the isolation boundary: user A's recall never sees user B's facts.
    return ("memories", user_id)


def _tokens(text: str) -> set[str]:
    """Cheap tokenizer that works for English words and Chinese (char + char bigrams).

    📘 LEARN: Chinese has no spaces, so splitting on whitespace returns whole sentences.
    Character bigrams ("喜欢喝茶" → 喜欢, 欢喝, 喝茶) are a classic, dependency-free way
    to get useful overlap matching for CJK text.
    """
    text = text.lower()
    words = set(re.findall(r"[a-z0-9_]+", text))
    cjk = re.findall(r"[一-鿿]", text)
    words |= {a + b for a, b in zip(cjk, cjk[1:])} | set(cjk)
    return words


async def save(store: BaseStore, user_id: str, content: str) -> str:
    key = uuid.uuid4().hex[:8]  # short id so the model can reference it ("delete a1b2c3d4")
    await store.aput(
        namespace(user_id),
        key,
        {"content": content, "created_at": datetime.now(timezone.utc).isoformat()},
    )
    # If the store was created with an `index` (embeddings), aput also embeds `content`
    # automatically, making it searchable by meaning.
    return key


async def delete(store: BaseStore, user_id: str, key: str) -> bool:
    if await store.aget(namespace(user_id), key) is None:
        return False
    await store.adelete(namespace(user_id), key)
    return True


async def list_all(store: BaseStore, user_id: str, limit: int = 100) -> list[tuple[str, str]]:
    # asearch without a query = list items in the namespace.
    items = await store.asearch(namespace(user_id), limit=limit)
    return [(it.key, it.value["content"]) for it in items]


async def recall(store: BaseStore | None, user_id: str, query: str, k: int | None = None) -> list[str]:
    """Return up to k memories relevant to `query`, formatted as '[key] content'.

    📘 LEARN — two retrieval strategies:
      • Semantic (OLLAMA_EMBED_MODEL set): the store embeds the query and returns the
        nearest memories by vector similarity. Matches meaning: "what do I drink?" finds
        "prefers tea" even with no shared words.
      • Keyword (default, zero setup): score memories by token overlap with the query.
        Good enough for a demo and for hundreds of memories; misses synonyms.

    Why recall only top-k instead of injecting ALL memories? Same reason as compaction:
    context is a budget. 500 memories in every prompt would be slow and distracting.
    """
    if store is None or not query:
        return []
    k = k or settings.memory_recall_k

    if settings.embed_model:  # semantic search through the store's vector index
        items = await store.asearch(namespace(user_id), query=query, limit=k)
        return [f"[{it.key}] {it.value['content']}" for it in items]

    # Keyword fallback: score every memory by token overlap (fine for hundreds of items).
    q = _tokens(query)
    scored = []
    for key, content in await list_all(store, user_id, limit=500):
        overlap = len(q & _tokens(content))
        scored.append((overlap, key, content))
    scored.sort(reverse=True)
    hits = [s for s in scored if s[0] > 0][:k]
    if not hits:  # nothing matched: still surface a few as general context about the user
        hits = scored[: min(3, k)]
    return [f"[{key}] {content}" for _, key, content in hits]
