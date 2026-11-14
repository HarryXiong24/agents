"""Observe tool execution and format recognized input failures."""

from collections.abc import Callable
from time import perf_counter

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.prebuilt.tool_node import ToolCallRequest, ToolInvocationError
from langgraph.types import Command
from pydantic import ValidationError

from ..errors import InputTypeError, InputValueError
from ..prompts import TOOL_ERROR_MESSAGE
from ..state import AgentState


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


class ToolExecutionMiddleware(AgentMiddleware[AgentState]):
    """Observe one actual execution and format only explicit input errors."""

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        call = request.tool_call
        print(f"Tool call started: name={call['name']}, id={call['id']}")
        started = perf_counter()
        status = "exception"
        try:
            try:
                result = handler(request)
            except (
                InputValueError,
                InputTypeError,
                ValidationError,
                ToolInvocationError,
            ) as error:
                # Only known input errors become model-visible failures.
                # Unknown exceptions, storage faults and graph signals propagate.
                result = ToolMessage(
                    content=handle_tool_error(error),
                    name=call["name"],
                    tool_call_id=call["id"],
                    status="error",
                )
            status = result.status if isinstance(result, ToolMessage) else "command"
            return result
        finally:
            print(
                f"Tool call finished: name={call['name']}, id={call['id']}, "
                f"status={status}, elapsed={perf_counter() - started:.3f}s"
            )
