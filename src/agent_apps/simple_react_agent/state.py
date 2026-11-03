"""Conversation state persisted independently for each thread."""

from typing import NotRequired

from langgraph.graph import MessagesState


class AgentState(MessagesState):
    """Recent original messages plus an optional summary of earlier turns."""

    # Version 4 checkpoints have no summary; read it with state.get("summary", "").
    summary: NotRequired[str]
