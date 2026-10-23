"""Central configuration. Everything can be overridden with environment variables.

📘 LEARN: Agent behaviour is tuned mostly by a handful of numbers (step budget,
context budget, which tools need approval). Keeping them in one place makes the
trade-offs visible and lets you experiment without touching graph code.

🧪 TRY:  AGENT_MAX_ITERATIONS=2 python main.py
         then ask something that needs 3+ tool calls and watch the forced final answer.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent  # repo root (parent of agent/)
PROJECT_ROOT = Path(__file__).resolve().parents[4]
load_dotenv(PROJECT_ROOT / ".env")


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)  # frozen: settings can't be changed by accident at runtime
class Settings:
    # ---- Model (Groq) ---------------------------------------------------------
    model: str = os.getenv("AGENT_MODEL") or "openai/gpt-oss-20b"
    # The Groq SDK appends /openai/v1 to this host itself.
    base_url: str = os.getenv("GROQ_BASE_URL") or "https://api.groq.com"
    # Low temperature = more deterministic tool calls. Agents want reliability, not creativity.
    temperature: float = float(os.getenv("GROQ_TEMPERATURE", "0.2"))

    # ---- Loop engineering ----------------------------------------------------
    # 📘 LEARN: these are the knobs that bound the agent loop. See graph.py for the
    # five layers (budget awareness → forced answer → error-as-observation → loop
    # guard → recursion fuse) and how each number is used.
    max_iterations: int = int(os.getenv("AGENT_MAX_ITERATIONS", "8"))      # ReAct steps per turn
    max_reflections: int = int(os.getenv("AGENT_MAX_REFLECTIONS", "1"))    # critic revisions per turn
    enable_reflection: bool = _bool("AGENT_REFLECTION", True)
    repeat_call_limit: int = 3          # identical tool call N times -> loop warning
    error_streak_limit: int = 3         # N consecutive tool errors -> loop warning
    # Hard ceiling on LangGraph super-steps. One ReAct iteration ≈ 4 super-steps
    # (compact → agent → tools → loop_guard), so 60 leaves ample room above
    # max_iterations=8. If this ever fires, the softer layers have a bug.
    recursion_limit: int = 60

    # ---- Context / memory management ----------------------------------------
    # Approximate tokens of message history before compaction kicks in. Deliberately
    # below the model's context window: system prompt + tools + the answer need room too.
    context_token_budget: int = int(os.getenv("AGENT_CONTEXT_BUDGET", "6000"))
    keep_recent_messages: int = 6       # newest messages always kept verbatim
    memory_recall_k: int = 5            # long-term memories injected per turn

    # ---- Human-in-the-loop ---------------------------------------------------
    # 📘 LEARN: approval is a POLICY (a list of names), not something the model decides.
    # The model cannot talk its way past it. Works the same for local and MCP tools.
    risky_tools: frozenset[str] = field(
        default_factory=lambda: frozenset(
            os.getenv("AGENT_RISKY_TOOLS", "run_shell,write_file,delete_file").split(",")
        )
    )

    # ---- Paths ---------------------------------------------------------------
    data_dir: Path = ROOT / "data"            # SQLite files (checkpoints + store)
    workspace_dir: Path = ROOT / "workspace"  # sandbox for file/shell tools
    mcp_config: Path = ROOT / "mcp_servers.json"


settings = Settings()
