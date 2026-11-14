"""Read the retained tool history from graph-injected runtime state."""

import json

from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from ..state import AgentState


# The model requests this tool with {}: runtime is hidden from its input schema.
# When the graph reaches ToolNode, it creates and injects ToolRuntime before calling
# this function. The model and console user do not construct or supply runtime.
# ToolRuntime[None, AgentState] describes no custom context and
# the shape of runtime.state (AgentState). These are type parameters, not call values.
# runtime.state contains this conversation's current messages, proposal, and history;
# the graph restores saved state using thread_id before tools read it.
# Read fields with runtime.state.get(...); this function does not open checkpoints.
# Only one tool per model step is admitted by the control middleware.
# A standalone tool.invoke({}) does not create this runtime automatically.
@tool
def get_tool_history(runtime: ToolRuntime[None, AgentState]) -> str:
    """Read retained recent tool call results in the current conversation.

    Use when the user asks which tools ran, their arguments, results, or timestamps.
    Returns a JSON list, ordered oldest to newest; an empty list means no records.
    Records come from the current conversation state, including restored checkpoints.
    Rejected requests are included; their result states that execution was declined.
    This read-only lookup excludes its own calls and never executes recorded calls.
    Call this tool in a later step to include earlier completed executions.
    """
    print("Tool: Reading recent tool history.")
    # ToolNode injects runtime; the model does not supply it as an argument.
    # Reading state does not change it or require a separate database connection.
    history = runtime.state.get("tool_history", [])
    return json.dumps(history, ensure_ascii=False, indent=2)
