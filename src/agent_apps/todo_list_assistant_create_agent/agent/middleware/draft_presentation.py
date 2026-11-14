"""Present the return-direct draft's final reply once the agent loop finishes."""

from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.runtime import Runtime

from ..state import AgentState


class DraftPresentationMiddleware(AgentMiddleware[AgentState]):
    """Present a return-direct draft once, with no second model paraphrase."""

    state_schema = AgentState

    def after_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        last = state["messages"][-1]
        if isinstance(last, ToolMessage) and last.name == "generate_todo_draft":
            reply = state.get("draft_reply") or f"Could not create a draft. {last.text}"
            return {"messages": [AIMessage(reply)], "draft_reply": None}
        return None
