"""第一块积木：读取模型配置，创建聊天模型。"""

import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel
from langchain_groq import ChatGroq


def create_model() -> BaseChatModel:
    """读取项目根目录的配置，创建聊天模型。"""
    project_root = Path(__file__).resolve().parents[3]
    load_dotenv(project_root / ".env")
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("请在项目根目录的 .env 中设置 GROQ_API_KEY。")

    return ChatGroq(
        model=os.getenv("AGENT_MODEL") or "openai/gpt-oss-20b",
        api_key=api_key,
        base_url=os.getenv("GROQ_BASE_URL") or "https://api.groq.com",
        temperature=0,
        timeout=30,
        max_retries=1,
    )
