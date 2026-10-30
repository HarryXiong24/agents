"""Block 2: local tools for time, arithmetic, and study plan writes."""

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
def calculate(a: float, b: float, operation: Literal["add", "subtract", "multiply", "divide"]) -> str:
    """Add, subtract, multiply, or divide two numbers, including study durations.

    a is the first number; b is the second number.
    operation must be add, subtract, multiply, or divide.
    Example: 45 minutes per day for 7 days uses a=45, b=7, operation="multiply".
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
    """Save a study plan across restarts when the user asks to save or update it.

    project is the study topic, minutes is an integer from 1 to 1440, and date is YYYY-MM-DD.
    Example: project="Python", minutes=60, date="2026-10-29".
    Ask for missing fields. Resolve relative dates with the time tool and convert hours to minutes.
    The same project and date updates duration; a different project or date adds a plan.
    """
    # Report success only after the write; the tool node handles execution errors.
    plan = memory.save_plan(project, minutes, date)
    result = f"Saved study plan: {plan['project']}, {plan['minutes']} minutes, {plan['date']}."
    print(f"Tool: {result}")
    return result


@tool
def delete_study_plan(project: str, date: str) -> str:
    """Delete a study plan by project and date only when explicitly requested.

    project is the study topic; date must use YYYY-MM-DD. Duration is not required.
    Example: project="Python", date="2026-10-29".
    Ask if the project or date is unclear; resolve relative dates with the time tool.
    Delete only the matching plan. If it is missing, report that and preserve other plans.
    """
    deleted = memory.delete_plan(project, date)
    if deleted:
        result = f"Deleted study plan: {project.strip()}, {date}."
    else:
        result = f"Study plan not found: {project.strip()}, {date}. No plans were deleted."
    print(f"Tool: {result}")
    return result


# All tools run locally. Both model binding and the tool node use this list.
# Adding a tool here does not require changing the graph's edges.
TOOLS = [get_current_time, calculate, save_study_plan, delete_study_plan]
