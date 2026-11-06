"""Conversation state persisted independently for each thread."""

from typing import Annotated, Any, NotRequired, TypedDict

from langgraph.graph import MessagesState

from ..config import agent as agent_settings


class ToolCallRecord(TypedDict):
    """Describe a completed tool request, including a request rejected by a human."""

    tool_name: str
    # Tool argument names are strings; values may have different JSON-compatible types.
    tool_args: dict[str, Any]
    # Store the actual tool output as text, including errors when execution fails.
    result: str
    # Create the timestamp when recording the call, rather than during merging.
    timestamp: str


def add_tool_history(
    old: list[ToolCallRecord],
    new: list[ToolCallRecord],
) -> list[ToolCallRecord]:
    """Merge existing and incoming records, retaining the configured recent entries."""
    # LangGraph passes this field's old value and the node's update, not the full state.
    # Concatenation creates a new list without modifying either input list.
    # All graph executions in this process share the same Agent configuration.
    return (old + new)[-agent_settings.AGENT_CONFIG.tool_history_limit :]


class AgentState(MessagesState):
    """Recent messages, an optional summary, and bounded tool call records."""

    # The summary may be absent before compression; read it with state.get("summary", "").
    summary: NotRequired[str]

    # MessagesState supplies messages and its add_messages reducer.
    # Annotated supplies this list's type and its separate merge rule to LangGraph.
    # A node returns only {"tool_history": new_records}; LangGraph runs the reducer.
    # Declaring this field does not create records; a node must produce the updates.
    # NotRequired lets graph inputs omit this field, just as they can omit summary.
    tool_history: NotRequired[Annotated[list[ToolCallRecord], add_tool_history]]
