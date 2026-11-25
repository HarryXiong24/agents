"""Assemble the agent's tools and bind the model and skills they depend on."""

from collections.abc import Mapping

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from ..skills import Skill
from .calculator import calculate
from .draft import create_draft_tool
from .history import get_tool_history
from .skills import create_skill_tools
from .time import get_current_time
from .todos import delete_todo, list_todos, save_todo


def create_tools(
    model: BaseChatModel, skills: Mapping[str, Skill] | None = None
) -> list[BaseTool]:
    """Return tools in registration order, with one model-bound draft tool."""
    # create_agent uses this list for both model binding and local execution.
    # Adding a tool here does not require changing the agent's internal edges.
    tools: list[BaseTool] = [
        get_current_time,
        calculate,
        save_todo,
        delete_todo,
        list_todos,
        get_tool_history,
        create_draft_tool(model),
    ]
    # Skill tools exist only when the application ships at least one skill.
    if skills:
        tools.extend(create_skill_tools(skills))
    return tools


__all__ = ["create_tools"]
