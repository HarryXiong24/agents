"""A small stdio MCP server that splits a duration into pomodoro blocks.

Run with: python -m agent_apps.todo_list_assistant_codex_sdk.mcp_servers.pomodoro
It has no side effects and needs no network access.
"""

from mcp.server.fastmcp import FastMCP

# Keep request logs off the shared console; warnings still reach stderr.
server = FastMCP("pomodoro", log_level="WARNING")


@server.tool()
def plan_pomodoros(
    minutes: int, focus_minutes: int = 25, break_minutes: int = 5
) -> str:
    """Split a todo duration into focus blocks separated by short breaks.

    minutes is the total focus time (1-1440). focus_minutes (5-90) is one block;
    break_minutes (0-30) is the pause between blocks. Breaks are added on top.
    """
    if not 1 <= minutes <= 1440:
        raise ValueError("minutes must be between 1 and 1440.")
    if not 5 <= focus_minutes <= 90:
        raise ValueError("focus_minutes must be between 5 and 90.")
    if not 0 <= break_minutes <= 30:
        raise ValueError("break_minutes must be between 0 and 30.")
    full, rest = divmod(minutes, focus_minutes)
    blocks = [focus_minutes] * full + ([rest] if rest else [])
    breaks = len(blocks) - 1
    total = minutes + breaks * break_minutes
    return (
        f"{len(blocks)} focus blocks ({', '.join(map(str, blocks))} minutes) "
        f"with {breaks} breaks of {break_minutes} minutes; "
        f"{total} minutes including breaks."
    )


if __name__ == "__main__":
    server.run("stdio")
