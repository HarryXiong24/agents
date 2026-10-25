"""Model factory for Groq chat models.
📘 LEARN: creating the model lazily keeps imports and offline tests independent of API keys.
The graph depends only on BaseChatModel (ainvoke/bind_tools), so providers are replaceable.
ChatGroq sends messages and schemas to Groq and parses native tool calls into AIMessage.

Groq 聊天模型工厂。
📘 LEARN：延迟创建模型，使模块导入和离线测试不依赖 API Key。
图只依赖 BaseChatModel 的 ainvoke/bind_tools 接口，因此可以替换模型服务商。
ChatGroq 将消息和工具 schema 发送给 Groq，并将原生工具调用解析为 AIMessage。
"""

from __future__ import annotations

import os

from langchain_core.language_models import BaseChatModel

from .config import PROJECT_ROOT, settings


def get_chat_model() -> BaseChatModel:
    from langchain_groq import ChatGroq

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
