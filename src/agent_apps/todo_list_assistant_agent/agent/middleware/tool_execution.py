"""Observe individual tool executions and format recognized input errors."""

from collections.abc import Callable
from time import perf_counter

from langchain_core.messages import ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.prebuilt.tool_node import ToolCallRequest, ToolInvocationError
from langgraph.types import Command
from pydantic import ValidationError

from ..errors import InputTypeError, InputValueError
from ..prompts import TOOL_ERROR_MESSAGE


def handle_tool_error(error: Exception) -> str:
    """Explain known input errors; propagate control signals, storage errors and bugs."""
    # ToolNode also catches exceptions raised by wrappers. An interrupt must reach
    # LangGraph so it can checkpoint the pending approval instead of reporting failure.
    if isinstance(error, GraphBubbleUp):
        raise error
    if isinstance(error, ToolInvocationError):
        # ToolNode already filters injected runtime/State fields out of this error.
        detail = str(error)
    elif isinstance(error, ValidationError):
        detail = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in error.errors()
        )
    elif isinstance(error, (InputValueError, InputTypeError)):
        detail = str(error)
    else:
        # In particular, never turn a database failure into an instruction to
        # retry a write, or hide a programmer's generic TypeError/ValueError.
        raise error
    return f"{TOOL_ERROR_MESSAGE} Details: {detail}"


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
