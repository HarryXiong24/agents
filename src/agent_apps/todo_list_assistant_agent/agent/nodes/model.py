"""Call the tool-enabled model and route its response to tools or turn completion."""

from typing import Any, Literal

from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import Runnable

from ...config import AgentConfig
from .. import memory
from ..prompts import build_system_prompt
from ..state import AgentState


class ModelNode:
    """Keep a tool-bound model available for every execution of the model step."""

    def __init__(self, model: Runnable, agent_config: AgentConfig) -> None:
        self._model = model
        self._agent_config = agent_config

    def model(self, state: AgentState) -> dict[str, Any]:
        """Return the model's next message using current todos and conversation context."""
        used = state.get("model_calls_this_turn", 0)
        if used >= self._agent_config.max_model_calls_per_turn:
            # A plain final message routes to END without another model request.
            return {
                "messages": [
                    AIMessage(
                        "This turn reached the model-call limit "
                        f"({self._agent_config.max_model_calls_per_turn}). "
                        "Completed tool results and saved todos were kept. "
                        "Send a new message to continue."
                    )
                ]
            }
        # Reload SQLite before every model call, including after tool writes.
        todos = memory.load_todos()
        system = build_system_prompt(
            todos, state.get("summary", ""), state.get("todo_draft")
        )
        # Send system instructions with each request without appending to history.
        response = self._model.invoke([SystemMessage(system), *state["messages"]])
        # MessagesState appends new message IDs and replaces matching IDs.
        # Commit usage with the result. A failed invocation returns no update;
        # this counts completed calls, not HTTP attempts or provider retries.
        return {"messages": [response], "model_calls_this_turn": used + 1}


def route_after_model(state: AgentState) -> Literal["tools", "__end__"]:
    """Route tool requests to execution, otherwise end the turn without changing State."""
    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"
    # LangGraph's END marker is "__end__"; it finishes this invocation.
    return "__end__"
