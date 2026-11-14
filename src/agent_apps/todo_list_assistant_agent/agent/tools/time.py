"""Get the local date and time for current and relative-date requests."""

from datetime import datetime

from langchain_core.tools import tool


@tool
def get_current_time() -> str:
    """Get the computer's local date and time for current or relative dates."""
    print("Tool: Getting the current local time.")
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
