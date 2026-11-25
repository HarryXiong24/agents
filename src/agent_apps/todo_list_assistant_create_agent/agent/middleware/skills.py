"""Disclose the skill catalog and active skill instructions to the main model."""

from collections.abc import Callable, Mapping

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage

from ..prompts import build_skills_prompt
from ..skills import Skill
from ..state import AgentState


class SkillsMiddleware(AgentMiddleware[AgentState]):
    """Progressive disclosure: metadata always, instructions once a skill is loaded."""

    state_schema = AgentState

    def __init__(self, skills: Mapping[str, Skill]) -> None:
        self._skills = dict(skills)

    def wrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse:
        if not self._skills:
            return handler(request)
        # State keeps names only. A name missing after a restart is not shown.
        active = [
            name
            for name in request.state.get("active_skills", [])
            if name in self._skills
        ]
        section = build_skills_prompt(self._skills, active)
        # Runs inside ContextMiddleware, so it extends that fresh system message
        # instead of being overwritten by it.
        base = request.system_message.text if request.system_message else ""
        system = f"{base}\n\n{section}" if base else section
        return handler(request.override(system_message=SystemMessage(system)))
