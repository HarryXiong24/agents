"""SQLite checkpoint storage details and saved conversation queries."""

from contextlib import closing
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

CHECKPOINTS_FILE = Path(__file__).resolve().parent / "data" / "checkpoints.sqlite"


def list_threads(checkpointer: SqliteSaver) -> list[str]:
    """Read conversation IDs without loading all saved messages and checkpoints."""
    # The menu runs before the graph, so no graph writes share this connection yet.
    # SqliteSaver prepares its tables lazily; a new file may have no table at all.
    with closing(checkpointer.conn.cursor()) as cursor:
        exists = cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'checkpoints'"
        ).fetchone()
        if exists is None:
            return []
        rows = cursor.execute(
            "SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id"
        ).fetchall()
    return [row[0] for row in rows]
