"""Assemble and export the local tools shared by the model and tool node."""

from collections.abc import Mapping

from langchain_core.tools import BaseTool

from ..skills import Skill
from .calculator import calculate
from .draft import generate_todo_draft
from .history import get_tool_history
from .skills import create_skill_tools
from .time import get_current_time
from .todos import delete_todo, list_todos, save_todo

# All tools run locally. Both model binding and the tool node use this list.
# Adding a tool here does not require changing the graph's edges.
TOOLS = [
    get_current_time,
    calculate,
    save_todo,
    delete_todo,
    list_todos,
    generate_todo_draft,
    get_tool_history,
]


def create_tools(skills: Mapping[str, Skill] | None = None) -> list[BaseTool]:
    """Keep base registration order and append tools for the supplied skills."""
    tools: list[BaseTool] = list(TOOLS)
    if skills:
        tools.extend(create_skill_tools(skills))
    return tools


__all__ = [
    "create_tools",
    "TOOLS",
    "calculate",
    "delete_todo",
    "generate_todo_draft",
    "get_current_time",
    "get_tool_history",
    "list_todos",
    "save_todo",
]
