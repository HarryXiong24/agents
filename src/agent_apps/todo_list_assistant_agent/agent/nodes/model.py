"""Call the tool-enabled model and route its response to tools or turn completion."""

from typing import Any, Literal

from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import Runnable

from .. import memory
from ..prompts import build_system_prompt
from ..state import AgentState


class ModelNode:
    """Keep a tool-bound model available for every execution of the model step."""

    def __init__(self, model: Runnable) -> None:
        self._model = model

    def model(self, state: AgentState) -> dict[str, Any]:
        """Return the model's next message using current todos and conversation context."""
        # Reload SQLite before every model call, including after tool writes.
        todos = memory.load_todos()
        system = build_system_prompt(
            todos, state.get("summary", ""), state.get("todo_draft")
        )
        # Send system instructions with each request without appending to history.
        response = self._model.invoke([SystemMessage(system), *state["messages"]])
        # MessagesState appends new message IDs and replaces matching IDs.
        return {"messages": [response]}


def route_after_model(state: AgentState) -> Literal["tools", "__end__"]:
    """Route tool requests to execution, otherwise end the turn without changing State."""
    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"
    # LangGraph's END marker is "__end__"; it finishes this invocation.
    return "__end__"
