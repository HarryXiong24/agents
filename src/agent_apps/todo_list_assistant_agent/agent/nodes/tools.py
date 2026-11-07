"""Execute tool requests sequentially and produce bounded execution-history updates."""

from datetime import datetime
from typing import Any, Literal

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.messages.tool import ToolCall
from langgraph.func import task
from langgraph.prebuilt import ToolNode

from ..state import AgentState, ToolCallRecord
from ..tools import get_tool_history


class ToolsNode:
    """Bind an executor while checkpoint tasks receive only State and call data."""

    def __init__(self, tool_node: ToolNode) -> None:
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
        if draft_calls and len(request.tool_calls) != 1:
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
        updates: dict[str, Any] = {"messages": tool_messages, "tool_history": records}
        if draft_calls:
            # A failed replacement request must not leave an older proposal active.
            updates["todo_draft"] = None
        return updates


def route_after_tools(state: AgentState) -> Literal["draft", "model"]:
    """Send an accepted standalone draft request to generation, otherwise continue ReAct."""
    message = state["messages"][-1]
    if (
        isinstance(message, ToolMessage)
        and message.name == "generate_todo_draft"
        and message.status == "success"
    ):
        return "draft"
    return "model"
