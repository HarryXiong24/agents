"""Compose checkpoint storage, console interaction, the model, and the graph."""

import sqlite3
from contextlib import ExitStack

from langgraph.checkpoint.sqlite import SqliteSaver

from .agent import checkpoints
from .agent.agent import build_agent
from .agent.mcp import McpConnections, McpServerError
from .agent.model import create_model
from .agent.skills import load_skills
from .agent.tools import create_tools
from .config import SKILLS_DIR, load_config
from .console import chat, select_thread


def main() -> None:
    """Keep the SQLite saver open for the entire graph and console lifetime."""
    try:
        checkpoints.CHECKPOINTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        # The saver creates its tables on first use. Exiting closes its connection.
        with SqliteSaver.from_conn_string(
            str(checkpoints.CHECKPOINTS_FILE)
        ) as checkpointer:
            threads = checkpoints.list_threads(checkpointer)
            thread_id = select_thread(threads)
            if thread_id is None:
                print("Goodbye!")
                return

            # Browsing the menu and exiting do not need a model or an API key.
            try:
                settings = load_config()
                model = create_model(settings.model)
                # A malformed skill is a SkillLoadError (a ValueError) and stops here.
                skills = load_skills(SKILLS_DIR)
            except (OSError, ValueError) as exc:
                raise SystemExit(f"Startup failed: {exc}") from exc

            # MCP sessions stay open for the whole chat and close on exit.
            reserved = frozenset(tool.name for tool in create_tools(model, skills))
            with ExitStack() as resources:
                try:
                    mcp_tools = resources.enter_context(
                        McpConnections(settings.mcp, reserved_names=reserved)
                    )
                except McpServerError as exc:
                    raise SystemExit(f"Startup failed: {exc}") from exc
                if mcp_tools:
                    print(f"MCP tools: {', '.join(tool.name for tool in mcp_tools)}")
                # Build the standard loop with middleware.
                graph = build_agent(
                    model, checkpointer=checkpointer, skills=skills, mcp_tools=mcp_tools
                )
                # begin chat
                chat(graph, thread_id=thread_id)
    except (EOFError, KeyboardInterrupt):
        print("\nGoodbye!")
    except (OSError, sqlite3.Error) as exc:
        raise SystemExit(f"Checkpoint storage failed: {exc}") from exc
