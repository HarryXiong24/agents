"""Agent settings edited directly in code rather than loaded from .env."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentConfig:
    """Configure summary and execution limits; use positive integers for all fields."""

    # Trigger compression when estimated conversation history reaches this threshold.
    summary_trigger_tokens: int = 500
    # Keep this many completed user turns verbatim, in addition to the current turn.
    summary_keep_turns: int = 2
    # Limit graph steps per invocation, including summary, model, and tool nodes.
    recursion_limit: int = 20
    # Retain this many recent tool executions in each conversation's State.
    tool_history_limit: int = 10


# One shared object; creating it does not read files or require model credentials.
AGENT_CONFIG = AgentConfig()
