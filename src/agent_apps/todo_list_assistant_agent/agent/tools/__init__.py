"""Assemble and export the local tools shared by the model and tool node."""

from .calculator import calculate
from .draft import generate_todo_draft
from .history import get_tool_history
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

__all__ = [
    "TOOLS",
    "calculate",
    "delete_todo",
    "generate_todo_draft",
    "get_current_time",
    "get_tool_history",
    "list_todos",
    "save_todo",
]
