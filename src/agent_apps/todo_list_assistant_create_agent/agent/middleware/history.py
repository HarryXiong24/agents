"""Collect completed and declined tool requests into conversation history."""

from datetime import datetime
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.runtime import Runtime

from ..state import AgentState, ToolCallRecord


class HistoryMiddleware(AgentMiddleware[AgentState]):
    """Observe completed messages, including built-in approval rejections."""

    state_schema = AgentState

    def collect(self, state: AgentState) -> dict[str, Any] | None:
        messages = state["messages"]
        starts = [
            i for i, item in enumerate(messages) if isinstance(item, HumanMessage)
        ]
        current = messages[starts[-1] :] if starts else messages
        calls = {
            call["id"]: call
            for item in current
            if isinstance(item, AIMessage)
            for call in item.tool_calls
        }
        seen = list(state.get("recorded_tool_call_ids", []))
        records: list[ToolCallRecord] = []
        for item in current:
            if not isinstance(item, ToolMessage) or item.tool_call_id in seen:
                continue
            call = calls.get(item.tool_call_id)
            if call is None:
                continue
            seen.append(item.tool_call_id)
            if call["name"] == "get_tool_history":
                continue
            records.append(
                {
                    "tool_name": call["name"],
                    "tool_args": dict(call["args"]),
                    "result": item.text,
                    "timestamp": datetime.now().astimezone().isoformat(),
                }
            )
        if seen == state.get("recorded_tool_call_ids", []):
            return None
        return {"recorded_tool_call_ids": seen, "tool_history": records}

    def before_model(
        self, state: AgentState, runtime: Runtime
    ) -> dict[str, Any] | None:
        # Run before summarization can remove the source tool messages.
        return self.collect(state)

    def after_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        # Also cover return-direct tools and budget exits that skip before_model.
        return self.collect(state)
