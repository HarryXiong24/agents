"""Execute tool requests sequentially and produce bounded execution-history updates."""

from datetime import datetime
from typing import Any, Literal

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.messages.tool import ToolCall
from langgraph.func import task
from langgraph.prebuilt import ToolNode

from ...config import AgentConfig
from ..state import AgentState, ToolCallRecord
from ..tools import get_tool_history


class ToolsNode:
    """Bind an executor while checkpoint tasks receive only State and call data."""

    def __init__(self, tool_node: ToolNode, agent_config: AgentConfig) -> None:
        @task
        def execute_tool(state: AgentState, call: ToolCall) -> ToolMessage:
            """Checkpoint one call's result so replay can reuse completed executions."""
            request = state["messages"][-1]
            if not isinstance(request, AIMessage):
                raise TypeError("The tool task requires an AIMessage.")
            # Isolate one request while preserving the pre-batch State for runtime injection.
            single_request = request.model_copy(update={"tool_calls": [call]})
            tool_state = {
                **state,
                "messages": [*state["messages"][:-1], single_request],
            }
            # RunnableConfig is inherited from the task's graph context, not serialized
            # as an argument. Inputs and returned ToolMessage are checkpoint-serializable.
            # The executor is captured, not passed as a serialized task argument.
            updates = tool_node.invoke(tool_state)
            return updates["messages"][0]

        self._execute_tool = execute_tool
        self._agent_config = agent_config

    def tools(self, state: AgentState) -> dict[str, Any]:
        """Return completed tool messages alongside this batch's history records."""
        request = state["messages"][-1]
        if not isinstance(request, AIMessage):
            raise TypeError("The tool node requires an AIMessage with tool calls.")

        # Stable task order lets checkpoints match cached results after a restart.
        # Wait for each call before starting the next; approvals never race for input.
        draft_calls = [
            call for call in request.tool_calls if call["name"] == "generate_todo_draft"
        ]
        used = state.get("tool_calls_this_turn", 0)
        requested = len(request.tool_calls)
        over_limit = used + requested > self._agent_config.max_tool_calls_per_turn
        if over_limit:
            # Reject the whole batch before any effects or approval prompts.
            # Complete every tool request so the next turn has valid message pairs.
            tool_messages = [
                ToolMessage(
                    content="Not executed: this batch exceeds the turn's tool-call limit. Continue only after a new user request.",
                    tool_call_id=call["id"],
                    name=call["name"],
                    status="error",
                )
                for call in request.tool_calls
            ]
        elif draft_calls and len(request.tool_calls) != 1:
            # Drafting ends the turn, so mixing it with writes or other calls
            # would skip follow-up work. Reject the whole batch before side effects.
            tool_messages = [
                ToolMessage(
                    content="Call generate_todo_draft alone in its batch. No tools in this batch were executed.",
                    tool_call_id=call["id"],
                    name=call["name"],
                    status="error",
                )
                for call in request.tool_calls
            ]
        else:
            tool_messages = [
                self._execute_tool(state, call).result() for call in request.tool_calls
            ]
        calls_by_id = {call["id"]: call for call in request.tool_calls}
        records: list[ToolCallRecord] = []
        for message in tool_messages:
            call = calls_by_id[message.tool_call_id]
            # Keep lookup results in messages, but avoid nesting history inside itself.
            if call["name"] == get_tool_history.name:
                continue
            records.append(
                {
                    "tool_name": call["name"],
                    "tool_args": dict(call["args"]),
                    # Record the actual output, including handled error messages.
                    "result": message.text,
                    # This is the record creation time, with the local UTC offset.
                    "timestamp": datetime.now().astimezone().isoformat(),
                }
            )

        # Return only this batch; reducers merge messages and bounded history.
        # A paused batch returns nothing. On resume, cached task results are reused
        # and its requests are counted once when the whole node completes.
        updates: dict[str, Any] = {
            "messages": tool_messages,
            "tool_history": records,
            "tool_calls_this_turn": used if over_limit else used + requested,
        }
        if draft_calls:
            # A failed replacement request must not leave an older proposal active.
            updates["todo_draft"] = None
        if over_limit:
            # Append only after recording ToolMessages: this is a final reply,
            # not another tool result or another model call.
            updates["messages"] = [
                *tool_messages,
                AIMessage(
                    "This batch exceeds the remaining tool-call budget "
                    f"({used}/{self._agent_config.max_tool_calls_per_turn} used; "
                    f"{requested} requested). No tools in this batch were executed. "
                    "Earlier completed work was kept. Send a new message to continue."
                ),
            ]
        return updates


def route_after_tools(state: AgentState) -> Literal["draft", "model", "__end__"]:
    """Finish a budget rejection, generate an accepted draft, or continue ReAct."""
    message = state["messages"][-1]
    # Normal execution ends with a ToolMessage for the model to read. When a
    # batch exceeds its budget, tools() instead appends a code-generated final
    # AIMessage after the declined ToolMessages. End that turn here; routing it
    # back to model would make an unnecessary call after we already explained the stop.
    # "__end__" is LangGraph's END marker, not another registered node.
    if isinstance(message, AIMessage) and not message.tool_calls:
        return "__end__"
    if (
        isinstance(message, ToolMessage)
        and message.name == "generate_todo_draft"
        and message.status == "success"
    ):
        return "draft"
    return "model"
