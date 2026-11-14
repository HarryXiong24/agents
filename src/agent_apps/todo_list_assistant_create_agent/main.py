"""Compose checkpoint storage, console interaction, the model, and the graph."""

import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver

from .agent import checkpoints
from .agent.agent import build_agent
from .agent.model import create_model
from .config import load_config
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
            except (OSError, ValueError) as exc:
                raise SystemExit(f"Startup failed: {exc}") from exc

            # Build the standard loop with middleware.
            graph = build_agent(model, checkpointer=checkpointer)
            # begin chat
            chat(graph, thread_id=thread_id)
    except (EOFError, KeyboardInterrupt):
        print("\nGoodbye!")
    except (OSError, sqlite3.Error) as exc:
        raise SystemExit(f"Checkpoint storage failed: {exc}") from exc
