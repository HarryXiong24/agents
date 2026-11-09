"""Local tools for time, arithmetic, and todo management."""

import json
import math
from datetime import date as calendar_date
from datetime import datetime
from typing import Any, Literal

from langchain.tools import ToolRuntime
from langchain_core.tools import tool
from pydantic import StrictInt

from . import memory
from .errors import InputValueError
from .schemas import TodoDraftRequest
from .state import AgentState


@tool
def get_current_time() -> str:
    """Get the computer's local date and time for current or relative dates."""
    print("Tool: Getting the current local time.")
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@tool
def calculate(
    a: float, b: float, operation: Literal["add", "subtract", "multiply", "divide"]
) -> str:
    """Add, subtract, multiply, or divide two numbers, including todo estimates.

    a is the first number; b is the second number.
    operation must be add, subtract, multiply, or divide.
    Example: seven 45-minute tasks use a=45, b=7, operation="multiply".
    Perform one operation per call; use the result in subsequent calls as needed.
    Nonfinite values, division by zero and numeric overflow are input errors.
    """
    print(f"Tool: Calculating {a} {operation} {b}.")
    if not math.isfinite(a) or not math.isfinite(b):
        raise InputValueError("Enter finite numbers.")

    # Explicit branches keep the code readable without evaluating generated code.
    if operation == "add":
        result = a + b
    elif operation == "subtract":
        result = a - b
    elif operation == "multiply":
        result = a * b
    else:
        if b == 0:
            raise InputValueError("The divisor must not be zero.")
        result = a / b

    if not math.isfinite(result):
        raise InputValueError("The result is outside the supported numeric range.")
    return str(result)


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


@tool(args_schema=TodoDraftRequest, response_format="content_and_artifact")
def generate_todo_draft(
    projects: list[str], date: str, max_minutes: int
) -> tuple[str, dict[str, Any]]:
    """Request an unsaved arrangement for named tasks on one date within a time budget.

    Use when the user wants proposed durations or an arrangement draft, not saving.
    Copy distinct task names, date and total time limit from the user's requirements;
    ask if any are missing. Resolve relative dates with the time tool first.
    max_minutes is the total budget for this draft, from 1 to 1440 minutes.
    Call this tool alone in its batch. The graph's draft node generates and checks
    the proposal next, then ends the turn with one displayed draft. Nothing is saved
    to the todo database. A later explicit save request can use save_todo.
    """
    request = TodoDraftRequest(projects=projects, date=date, max_minutes=max_minutes)
    if len(request.projects) > request.max_minutes:
        raise InputValueError("The budget must allow at least one minute per task.")
    return (
        "Draft request accepted. The draft node will generate and validate it. This request does not save any todos.",
        request.model_dump(mode="json"),
    )


# The model requests this tool with {}: runtime is hidden from its input schema.
# When the graph reaches ToolNode, it creates and injects ToolRuntime before calling
# this function. The model and console user do not construct or supply runtime.
# ToolRuntime[None, AgentState] describes no custom context and
# the shape of runtime.state (AgentState). These are type parameters, not call values.
# runtime.state contains this conversation's current messages, summary, and history;
# the graph restores saved state using thread_id before tools read it.
# Read fields with runtime.state.get(...); this function does not open checkpoints.
# Tools in the same batch see state before that batch's returned updates are merged.
# A standalone tool.invoke({}) does not create this runtime automatically.
@tool
def get_tool_history(runtime: ToolRuntime[None, AgentState]) -> str:
    """Read retained recent tool call results in the current conversation.

    Use when the user asks which tools ran, their arguments, results, or timestamps.
    Returns a JSON list, ordered oldest to newest; an empty list means no records.
    Records come from the current conversation state, including restored checkpoints.
    Rejected requests are included; their result states that execution was declined.
    This read-only lookup excludes its own calls and never executes recorded calls.
    If other tools run in the same batch, their new records appear only after that
    batch completes. Call this tool in a later step to include those executions.
    """
    print("Tool: Reading recent tool history.")
    # ToolNode injects runtime; the model does not supply it as an argument.
    # Reading state does not change it or require a separate database connection.
    history = runtime.state.get("tool_history", [])
    return json.dumps(history, ensure_ascii=False, indent=2)


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
