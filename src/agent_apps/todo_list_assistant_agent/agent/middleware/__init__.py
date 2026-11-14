"""Export tool-call hooks and compose approval outside execution observation."""

from collections.abc import Callable

from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from .approval import approve_tool_call
from .tool_execution import handle_tool_error, observe_tool_call


def tool_call_middleware(
    request: ToolCallRequest,
    execute: Callable[[ToolCallRequest], ToolMessage | Command],
) -> ToolMessage | Command:
    """Run approval outside observation, so timing starts only after approval."""

    def observe(approved_request: ToolCallRequest) -> ToolMessage | Command:
        return observe_tool_call(approved_request, execute)

    return approve_tool_call(request, observe)


__all__ = [
    "approve_tool_call",
    "handle_tool_error",
    "observe_tool_call",
    "tool_call_middleware",
]
