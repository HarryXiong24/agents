"""Observe individual tool calls without changing their requests or results."""

from collections.abc import Callable
from time import perf_counter

from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command


def wrap_tool_call(
    request: ToolCallRequest,
    execute: Callable[[ToolCallRequest], ToolMessage | Command],
) -> ToolMessage | Command:
    """Print a tool call's name, ID, result status, and elapsed execution time."""
    # ToolNode supplies both arguments for each call, including parallel batches.
    # execute(request) continues execution; this wrapper is not a model-facing tool.
    name = request.tool_call["name"]
    call_id = request.tool_call["id"]
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
