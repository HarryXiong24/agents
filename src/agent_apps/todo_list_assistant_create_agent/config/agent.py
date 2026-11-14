"""Agent behavior settings, defined in code independently of model credentials."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentConfig:
    """Configure summaries, persistent per-turn limits, history and approval policy."""

    summary_trigger_tokens: int = 500
    # The built-in summarizer retains a message count, not complete user turns.
    summary_keep_messages: int = 6
    # Framework middleware hooks add graph steps to the standard loop.
    recursion_limit: int = 80
    max_model_calls_per_turn: int = 6
    max_tool_calls_per_turn: int = 8
    tool_history_limit: int = 10
    approval_tools: tuple[str, ...] = ("delete_todo",)


AGENT_CONFIG = AgentConfig()
