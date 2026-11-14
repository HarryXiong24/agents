"""Expose local todo persistence through save, delete, and list tools."""

import json
from datetime import date as calendar_date

from langchain_core.tools import tool
from pydantic import StrictInt

from .. import memory
from ..errors import InputValueError


@tool
def save_todo(project: str, minutes: StrictInt, date: str) -> str:
    """Add or update a todo across restarts when the user explicitly requests it.

    project is the todo name, minutes is its estimated duration from 1 to 1440,
    and date is the scheduled date in YYYY-MM-DD format. All fields are required.
    minutes must be an actual integer, not a boolean, numeric string, or float.
    Example: project="Clean room", minutes=30, date="2026-11-04".
    Ask for missing fields. Resolve relative dates with the time tool and convert hours to minutes.
    The same name and date updates duration; a different name or date adds a todo.
    This tool does not rename, reschedule, or mark todos complete.
    """
    # StrictInt prevents Pydantic from converting True, "30", or 30.0 before
    # storage validation. Report success only after the write has committed.
    todo = memory.save_todo(project, minutes, date)
    result = f"Saved todo: {todo['project']}, estimated {todo['minutes']} minutes, scheduled for {todo['date']}."
    print(f"Tool: {result}")
    return result


@tool
def delete_todo(project: str, date: str) -> str:
    """Delete a todo by name and scheduled date only when explicitly requested.

    project is the todo name; date must use YYYY-MM-DD. Duration is not required.
    Example: project="Clean room", date="2026-11-04".
    Ask if the name or date is unclear; resolve relative dates with the time tool.
    By default, the graph pauses for separate human approval before execution.
    Delete only the matching todo. If missing, report that and preserve other todos.
    Saying a todo is done does not authorize deletion; there is no completion field.
    """
    deleted = memory.delete_todo(project, date)
    if deleted:
        result = f"Deleted todo: {project.strip()}, {date}."
    else:
        result = f"Todo not found: {project.strip()}, {date}. No todos were deleted."
    print(f"Tool: {result}")
    return result


@tool
def list_todos(project: str | None = None, date: str | None = None) -> str:
    """Read saved todos for display, optionally matching an exact name and/or date.

    Use whenever the user asks to show or list saved todos. With no arguments,
    return all saved todos. project is the exact name; date is YYYY-MM-DD.
    Resolve relative dates with the time tool before supplying a date filter.
    Each returned record has only project, minutes, and date; an empty list means
    no matches. This read-only tool never saves, deletes, or generates records.
    Use these returned records to answer the user's query; never invent saved rows.
    """
    if project is not None:
        project = project.strip()
        if not project:
            raise InputValueError("The todo name filter must not be blank.")
    if date is not None:
        try:
            parsed_date = calendar_date.fromisoformat(date)
        except ValueError as exc:
            raise InputValueError(
                "The date filter must be a valid YYYY-MM-DD date."
            ) from exc
        if parsed_date.isoformat() != date:
            raise InputValueError("The date filter must use YYYY-MM-DD format.")
    todos = []
    for todo in memory.load_todos():
        if project is not None and todo["project"] != project:
            continue

        if date is not None and todo["date"] != date:
            continue

        todos.append(todo)

    return json.dumps(todos, ensure_ascii=False)
