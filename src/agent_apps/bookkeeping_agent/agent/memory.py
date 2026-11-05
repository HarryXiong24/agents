"""Three layers of memory.
1. Short-term: thread messages/checkpoints in SQLite.
2. Compaction: old messages become a rolling summary.
3. Long-term: user facts in Store, independent of thread IDs.
Store records have namespace=("memories", user_id), a unique key, and a JSON value.
📘 LEARN: starting a new thread changes conversation history, not user preferences.

三层记忆。
1. 短期：SQLite 中的会话消息和检查点。
2. 压缩：将旧消息合并为滚动摘要。
3. 长期：Store 中的用户偏好，不依赖会话 ID。
Store 记录包含命名空间 ("memories", user_id)、唯一键和 JSON 值。
📘 LEARN：新建会话只切换对话历史，不会清空用户偏好。
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from langgraph.store.base import BaseStore

from .config import settings


def namespace(user_id: str) -> tuple[str, ...]:
    # 📘 LEARN: namespaces isolate users; user_id comes from the application, not tool arguments.
    # 📘 LEARN：命名空间隔离用户，user_id 来自应用入口，不是工具参数。
    return ("memories", user_id)


def _tokens(text: str) -> set[str]:
    """Tokenize English words and Chinese characters/bigrams without extra dependencies.
    Chinese has no spaces; adjacent character pairs give useful lexical overlap.

    无需额外依赖，提取英文单词、中文单字和相邻双字。
    中文没有空格，连续双字可以提供简单的词面匹配信号。
    """
    text = text.lower()
    words = set(re.findall(r"[a-z0-9_]+", text))
    cjk = re.findall(r"[一-鿿]", text)
    words |= {a + b for a, b in zip(cjk, cjk[1:])} | set(cjk)
    return words


async def save(store: BaseStore, user_id: str, content: str) -> str:
    key = uuid.uuid4().hex[:8]
    await store.aput(
        namespace(user_id),
        key,
        {"content": content, "created_at": datetime.now(UTC).isoformat()},
    )
    return key


async def delete(store: BaseStore, user_id: str, key: str) -> bool:
    if await store.aget(namespace(user_id), key) is None:
        return False
    await store.adelete(namespace(user_id), key)
    return True


async def list_all(
    store: BaseStore, user_id: str, limit: int = 100
) -> list[tuple[str, str]]:
    items = await store.asearch(namespace(user_id), limit=limit)
    return [(it.key, it.value["content"]) for it in items]


# 异步检索与当前问题相关的用户长期记忆，调用时需要 await recall(...)。
async def recall(
    # store：存储对象，也可以为 None；user_id：限定读取哪个用户的记忆。
    # query：查询文本；k：最多返回的记忆条数，为 None 时使用配置默认值。
    store: BaseStore | None, user_id: str, query: str, k: int | None = None
) -> list[str]:  # 返回字符串列表，每条记忆的格式为 "[标识] 内容"。
    """Rank stored memories by token overlap and return top-k as [id] content.
    A few fallback memories are returned if no terms overlap. This is keyword retrieval,
    not semantic search: synonyms may be missed. Top-k keeps the prompt bounded.

    按词项重叠排序，以 [id] 内容的格式返回 top-k 条记忆。
    无匹配时返回少量兜底记忆。这是关键词检索，不是语义搜索，可能遗漏同义词。
    top-k 避免把全部记忆塞进提示词。
    """
    # 没有存储对象，或查询文本为空时，不进行检索。
    if store is None or not query:
        # 返回空列表，表示没有召回任何记忆。
        return []
    # k 为 None 或 0 时使用配置默认值；正常使用时应传入正整数。
    k = k or settings.memory_recall_k

    # 将查询拆成去重的词项集合：英文词、数字、中文单字和相邻双字。
    q = _tokens(query)
    # 收集每条记忆的 (匹配分数, 唯一标识, 内容)。
    scored = []
    # 异步读取该用户最多 500 条记忆，并逐条拆成 key 和 content。
    for key, content in await list_all(store, user_id, limit=500):
        # & 求两个词项集合的交集，len 统计共同词项数量作为相关性分数。
        # 集合会去重，因此同一词项重复出现不会额外加分；这里没有语义匹配。
        overlap = len(q & _tokens(content))
        # 将评分和原始记忆一起存入列表，供后续排序和格式化使用。
        scored.append((overlap, key, content))
    # 原地降序排序：优先比较分数，同分时比较 key，key 相同再比较 content。
    scored.sort(reverse=True)
    # 先筛选至少有一个共同词项的记忆，再取排序后的前 k 条，不足 k 条不补齐。
    hits = [s for s in scored if s[0] > 0][:k]
    # 没有任何匹配结果时，启用兜底逻辑。
    if not hits:
        # 最多返回 3 条，且不超过 k 和已有记录数；没有记录时仍返回空列表。
        # 全部分数为 0 时，结果主要按 key 排序，不保证相关，也不代表最新记忆。
        hits = scored[: min(3, k)]
    # 忽略评分（用 _ 接收），将每条记忆格式化为 "[标识] 内容" 并返回列表。
    return [f"[{key}] {content}" for _, key, content in hits]
