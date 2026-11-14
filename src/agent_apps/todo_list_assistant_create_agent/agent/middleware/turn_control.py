"""Enforce persistent per-turn quotas and one tool request per model response."""

from typing import Any

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
from langgraph.runtime import Runtime

from ...config import AgentConfig
from ..state import AgentState


class TurnControlMiddleware(AgentMiddleware[AgentState]):
    """Keep persistent user-turn budgets and admit one tool per model step."""

    state_schema = AgentState

    def __init__(self, settings: AgentConfig) -> None:
        self._settings = settings

    @hook_config(can_jump_to=["end"])
    def before_model(
        self, state: AgentState, runtime: Runtime
    ) -> dict[str, Any] | None:
        used = state.get("model_calls_this_turn", 0)
        if used >= self._settings.max_model_calls_per_turn:
            return {
                "messages": [
                    AIMessage(
                        "This turn reached the model-call limit. Completed work was kept. "
                        "Send a new message to continue."
                    )
                ],
                "jump_to": "end",
            }
        return None

    @hook_config(can_jump_to=["model", "end"])
    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any]:
        message = state["messages"][-1]
        if not isinstance(message, AIMessage):
            raise TypeError("The model must return an AIMessage.")
        updates: dict[str, Any] = {
            "model_calls_this_turn": state.get("model_calls_this_turn", 0) + 1,
        }
        calls = message.tool_calls
        if not calls:
            return updates
        if any(call["name"] == "generate_todo_draft" for call in calls):
            # Clear before approval or generation, including failed replacements.
            updates.update(todo_draft=None, draft_reply=None)
        used = state.get("tool_calls_this_turn", 0)
        over_limit = used + len(calls) > self._settings.max_tool_calls_per_turn
        if over_limit or len(calls) > 1:
            reason = (
                "This batch exceeds the remaining tool-call budget."
                if over_limit
                else "Call exactly one tool per model step; this entire batch was declined."
            )
            replies: list[AnyMessage] = [
                ToolMessage(
                    content=reason + " No tools in this batch were executed.",
                    tool_call_id=call["id"],
                    name=call["name"],
                    status="error",
                )
                for call in calls
            ]
            updates["messages"] = replies
            if over_limit:
                replies.append(AIMessage(reason + " Send a new message to continue."))
                updates["jump_to"] = "end"
            else:
                updates["tool_calls_this_turn"] = used + len(calls)
                updates["jump_to"] = "model"
            return updates
        # Reserve before built-in HITL. A rejected approval still uses one slot;
        # restoring its checkpoint does not rerun this completed after_model hook.
        updates["tool_calls_this_turn"] = used + 1
        return updates
