"""Configuration for the model, loop budgets, memory, approval policy and storage.
📘 LEARN: frozen settings prevent accidental mutation; environment variables let you experiment.
🧪 TRY: AGENT_MAX_ITERATIONS=2 uv run react-agent

模型、循环预算、记忆、审批策略和存储配置。
📘 LEARN：冻结配置避免意外修改；通过环境变量进行实验。
🧪 TRY：调低步数预算，观察 Agent 如何结束尚未完成的任务。
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = Path(__file__).resolve().parents[4]
load_dotenv(PROJECT_ROOT / ".env")


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # Model factory configuration; low temperature makes tool selection more stable.
    # 模型工厂配置：较低温度有助于稳定工具选择。
    model: str = os.getenv("AGENT_MODEL") or "openai/gpt-oss-20b"

    # The Groq SDK adds /openai/v1; configure only the host here.
    # Groq SDK 会添加 /openai/v1，此处只配置主机地址。
    base_url: str = os.getenv("GROQ_BASE_URL") or "https://api.groq.com"

    temperature: float = float(os.getenv("GROQ_TEMPERATURE", "0.2"))

    # Per-call timeout and per-turn budgets; reflection has its own cap.
    # 每次调用的超时与每轮预算；反思有独立上限。
    tool_timeout_seconds: float = float(os.getenv("AGENT_TOOL_TIMEOUT_SECONDS", "20"))
    max_iterations: int = int(os.getenv("AGENT_MAX_ITERATIONS", "8"))
    max_reflections: int = int(os.getenv("AGENT_MAX_REFLECTIONS", "1"))
    enable_reflection: bool = _bool("AGENT_REFLECTION", True)
    repeat_call_limit: int = 3
    error_streak_limit: int = 3

    # One ReAct iteration spans several nodes; 60 leaves room above the 8-step soft budget.
    # 一次 ReAct 迭代经过多个节点，60 为默认 8 步软预算留出余量。
    recursion_limit: int = 60

    # Budget only the history; leave context space for system instructions and tool schemas.
    # 这里估算历史消息预算，为系统指令和工具 schema 保留上下文空间。
    context_token_budget: int = int(os.getenv("AGENT_CONTEXT_BUDGET", "6000"))
    keep_recent_messages: int = 6
    memory_recall_k: int = 5

    # Policy applies equally to local and MCP tools; the model cannot bypass the gate.
    # 策略同样适用于本地和 MCP 工具，模型不能绕过审批节点。
    risky_tools: frozenset[str] = field(
        default_factory=lambda: frozenset(
            name.strip()
            for name in os.getenv(
                "AGENT_RISKY_TOOLS", "add_expense,update_expense,delete_expense"
            ).split(",")
            if name.strip()
        )
    )

    data_dir: Path = Path(os.getenv("AGENT_DATA_DIR", ROOT / "data")).resolve()
    mcp_config: Path = ROOT / "mcp_servers.json"


settings = Settings()


def user_data_dir(user_id: str) -> Path:
    """Choose a user directory in trusted application code.
    Hashing makes slashes in user IDs harmless. Both ledger and checkpoints are separated
    by user, so another user’s paused write cannot resume against this user’s ledger.
    This is local data organization, not authentication.

    由可信应用代码选择用户目录。
    哈希避免用户 ID 中的斜杠变成文件路径。账本和检查点均按用户分开，
    避免将另一个用户的待审批写入恢复到当前账本。这是本地数据分组，不是登录认证。
    """
    key = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    return settings.data_dir / "users" / key
