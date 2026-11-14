"""Assemble the agent's tools and bind the model used for draft generation."""

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from .calculator import calculate
from .draft import create_draft_tool
from .history import get_tool_history
from .time import get_current_time
from .todos import delete_todo, list_todos, save_todo


def create_tools(model: BaseChatModel) -> list[BaseTool]:
    """Return tools in registration order, with one model-bound draft tool."""
    # create_agent uses this list for both model binding and local execution.
    # Adding a tool here does not require changing the agent's internal edges.
    return [
        get_current_time,
        calculate,
        save_todo,
        delete_todo,
        list_todos,
        get_tool_history,
        create_draft_tool(model),
    ]


__all__ = ["create_tools"]
