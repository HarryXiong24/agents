"""Application fields added to the state managed by create_agent."""

from typing import Annotated, Any, NotRequired, TypedDict

from langchain.agents import AgentState as BaseAgentState

from ..config import agent as agent_settings


class ToolCallRecord(TypedDict):
    """A completed or declined request retained for history queries."""

    tool_name: str
    tool_args: dict[str, Any]
    result: str
    timestamp: str


def add_tool_history(
    old: list[ToolCallRecord], new: list[ToolCallRecord]
) -> list[ToolCallRecord]:
    """Merge only newly observed records and retain recent history."""
    return (old + new)[-agent_settings.AGENT_CONFIG.tool_history_limit :]


class AgentState(BaseAgentState):
    """Messages plus proposal, history and checkpointed per-user-turn usage."""

    todo_draft: NotRequired[dict[str, Any] | None]
    # Internal handoff from the return-direct draft tool to its presentation hook.
    draft_reply: NotRequired[str | None]
    tool_history: NotRequired[Annotated[list[ToolCallRecord], add_tool_history]]
    # Deduplicate tool results across before_model and after_agent hooks.
    recorded_tool_call_ids: NotRequired[list[str]]
    model_calls_this_turn: NotRequired[int]
    # Count admitted requests before approval, rather than completed batches.
    tool_calls_this_turn: NotRequired[int]
