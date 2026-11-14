"""Pause protected tool calls until explicit human approval is supplied."""

from collections.abc import Callable

from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command, interrupt

from ...config import agent as agent_settings


def approve_tool_call(
    request: ToolCallRequest,
    execute: Callable[[ToolCallRequest], ToolMessage | Command],
) -> ToolMessage | Command:
    """Pause protected calls and continue only after an explicit boolean approval."""
    call = request.tool_call
    if call["name"] not in agent_settings.AGENT_CONFIG.approval_tools:
        return execute(request)

    # JSON data is saved with the interrupt. Only console.py reads terminal input.
    # On replay, interrupt returns the value supplied by Command(resume=...).
    decision = interrupt(
        {
            "kind": "tool_approval",
            "tool_name": call["name"],
            "tool_call_id": call["id"],
            "args": call["args"],
        }
    )
    if not isinstance(decision, dict) or type(decision.get("approved")) is not bool:
        raise ValueError("Approval requires an explicit boolean 'approved' value.")
    if decision["approved"]:
        return execute(request)

    # Complete the model's tool request even when execution is declined.
    return ToolMessage(
        content="The user rejected this tool call. It was not executed. Do not retry this operation without a new user request.",
        name=call["name"],
        tool_call_id=call["id"],
        status="error",
    )
