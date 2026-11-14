"""Refresh the model's system context from current saved todos and the draft."""

from collections.abc import Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage

from .. import memory
from ..prompts import build_system_prompt
from ..state import AgentState


class ContextMiddleware(AgentMiddleware[AgentState]):
    """Refresh saved todos and the independent draft for every main model request."""

    state_schema = AgentState

    def wrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse:
        system = build_system_prompt(
            memory.load_todos(), request.state.get("todo_draft")
        )
        return handler(request.override(system_message=SystemMessage(system)))
