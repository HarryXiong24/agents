"""Local tools for time, arithmetic, and todo management."""

import json
import math
from datetime import datetime
from typing import Literal

from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from . import memory
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
def save_todo(project: str, minutes: int, date: str) -> str:
    """Add or update a todo across restarts when the user explicitly requests it.

    project is the todo name, minutes is its estimated duration from 1 to 1440,
    and date is the scheduled date in YYYY-MM-DD format. All fields are required.
    Example: project="Clean room", minutes=30, date="2026-11-04".
    Ask for missing fields. Resolve relative dates with the time tool and convert hours to minutes.
    The same name and date updates duration; a different name or date adds a todo.
    This tool does not rename, reschedule, or mark todos complete.
    """
    # Report success only after the write; the tool node handles execution errors.
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


# The model requests this tool with {}: runtime is hidden from its input schema.
# When the graph reaches ToolNode, it creates and injects ToolRuntime before calling
# this function. The model and console user do not construct or supply runtime.
# ToolRuntime[None, AgentState] describes two types: no custom context (None), and
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
TOOLS = [get_current_time, calculate, save_todo, delete_todo, get_tool_history]
