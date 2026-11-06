"""Compose human approval and observation around individual tool calls."""

from collections.abc import Callable
from time import perf_counter

from langchain_core.messages import ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command, interrupt

from ..config import agent as agent_settings
from .prompts import TOOL_ERROR_MESSAGE


def handle_tool_error(error: Exception) -> str:
    """Preserve graph control signals while formatting ordinary tool errors."""
    # ToolNode also catches exceptions raised by wrappers. An interrupt must reach
    # LangGraph so it can checkpoint the pending approval instead of reporting failure.
    if isinstance(error, GraphBubbleUp):
        raise error
    return TOOL_ERROR_MESSAGE


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


def observe_tool_call(
    request: ToolCallRequest,
    execute: Callable[[ToolCallRequest], ToolMessage | Command],
) -> ToolMessage | Command:
    """Print a tool call's name, ID, result status, and elapsed execution time."""
    # ToolNode supplies both arguments for each individual call.
    # execute(request) continues execution; this wrapper is not a model-facing tool.
    name = request.tool_call["name"]
    call_id = request.tool_call["id"]
    print("------")
    print(f"Tool call started: name={name}, id={call_id}")
    started = perf_counter()
    status = "exception"
    try:
        # Execute exactly once and preserve the original result object.
        result = execute(request)
        # ToolMessage.status describes the tool protocol, not business success.
        # Command is also a supported ToolNode result; pass it through unchanged.
        status = result.status if isinstance(result, ToolMessage) else "command"
        return result
    finally:
        # Always report completion, then let any exception continue to ToolNode.
        # Local variables keep concurrent calls' timing and status independent.
        elapsed = perf_counter() - started
        print(
            f"Tool call finished: name={name}, id={call_id}, "
            f"status={status}, elapsed={elapsed:.3f}s"
        )
        print("------")


def tool_call_middleware(
    request: ToolCallRequest,
    execute: Callable[[ToolCallRequest], ToolMessage | Command],
) -> ToolMessage | Command:
    """Run approval outside observation, so timing starts only after approval."""

    def observe(approved_request: ToolCallRequest) -> ToolMessage | Command:
        return observe_tool_call(approved_request, execute)

    return approve_tool_call(request, observe)
