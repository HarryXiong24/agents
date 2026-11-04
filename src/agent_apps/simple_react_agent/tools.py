"""Local tools for time, arithmetic, and todos; legacy tool names stay compatible."""

import math
from datetime import datetime
from typing import Literal

from langchain_core.tools import tool

from . import memory


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
    """
    print(f"Tool: Calculating {a} {operation} {b}.")
    if not math.isfinite(a) or not math.isfinite(b):
        return "Cannot calculate: enter finite numbers."

    # Explicit branches keep the code readable without evaluating generated code.
    if operation == "add":
        result = a + b
    elif operation == "subtract":
        result = a - b
    elif operation == "multiply":
        result = a * b
    else:
        if b == 0:
            return "Cannot calculate: the divisor must not be zero. Check the numbers or explain the issue."
        result = a / b

    if not math.isfinite(result):
        return "Cannot calculate: the result is outside the supported numeric range."
    return str(result)


@tool
def save_study_plan(project: str, minutes: int, date: str) -> str:
    """Add or update a todo across restarts when the user explicitly requests it.

    project is the todo name, minutes is its estimated duration from 1 to 1440,
    and date is the scheduled date in YYYY-MM-DD format. All fields are required.
    Example: project="Clean room", minutes=30, date="2026-11-04".
    Ask for missing fields. Resolve relative dates with the time tool and convert hours to minutes.
    The same name and date updates duration; a different name or date adds a todo.
    This tool does not rename, reschedule, or mark todos complete. Its legacy name
    is retained so historical tool calls and unfinished checkpoints still work.
    """
    # Report success only after the write; the tool node handles execution errors.
    plan = memory.save_plan(project, minutes, date)
    result = f"Saved todo: {plan['project']}, estimated {plan['minutes']} minutes, scheduled for {plan['date']}."
    print(f"Tool: {result}")
    return result


@tool
def delete_study_plan(project: str, date: str) -> str:
    """Delete a todo by name and scheduled date only when explicitly requested.

    project is the todo name; date must use YYYY-MM-DD. Duration is not required.
    Example: project="Clean room", date="2026-11-04".
    Ask if the name or date is unclear; resolve relative dates with the time tool.
    Delete only the matching todo. If missing, report that and preserve other todos.
    Saying a todo is done does not authorize deletion; there is no completion field.
    The legacy tool name is retained for historical calls and checkpoints.
    """
    deleted = memory.delete_plan(project, date)
    if deleted:
        result = f"Deleted todo: {project.strip()}, {date}."
    else:
        result = f"Todo not found: {project.strip()}, {date}. No todos were deleted."
    print(f"Tool: {result}")
    return result


# All tools run locally. Both model binding and the tool node use this list.
# Adding a tool here does not require changing the graph's edges.
TOOLS = [get_current_time, calculate, save_study_plan, delete_study_plan]
