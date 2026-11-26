"""Keep business records independent of Codex conversation history."""

import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Generator

from .schemas import TodoDraft, TodoView


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS todos (
                    project TEXT NOT NULL,
                    minutes INTEGER NOT NULL CHECK (minutes BETWEEN 1 AND 1440),
                    date TEXT NOT NULL,
                    PRIMARY KEY (project, date)
                );
                CREATE TABLE IF NOT EXISTS drafts (
                    thread_id TEXT PRIMARY KEY, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tool_history (
                    id INTEGER PRIMARY KEY, thread_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL, arguments TEXT NOT NULL,
                    result TEXT NOT NULL, status TEXT NOT NULL,
                    timestamp TEXT NOT NULL, elapsed_ms INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS tool_history_thread
                    ON tool_history (thread_id, id DESC);
            """)

    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.row_factory = sqlite3.Row
            yield db

    def save(self, todo: TodoView) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO todos (project, minutes, date) VALUES (?, ?, ?)
                ON CONFLICT (project, date) DO UPDATE SET minutes = excluded.minutes
                """,
                (todo.project, todo.minutes, todo.date),
            )

    def list_todos(self, project: str | None, date: str | None) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT project, minutes, date FROM todos
                WHERE (? IS NULL OR project = ?) AND (? IS NULL OR date = ?)
                ORDER BY date, project
                """,
                (project, project, date, date),
            )
            return [dict(row) for row in rows]

    def delete(self, todo: TodoView) -> bool:
        # If another session updated the duration after preview, require a new request.
        with self.connect() as db:
            return (
                db.execute(
                    "DELETE FROM todos WHERE project = ? AND date = ? AND minutes = ?",
                    (todo.project, todo.date, todo.minutes),
                ).rowcount
                == 1
            )

    def set_draft(self, thread_id: str, draft: TodoDraft | None) -> None:
        with self.connect() as db:
            if draft is None:
                db.execute("DELETE FROM drafts WHERE thread_id = ?", (thread_id,))
            else:
                db.execute(
                    "INSERT OR REPLACE INTO drafts (thread_id, payload) VALUES (?, ?)",
                    (thread_id, draft.model_dump_json()),
                )

    def get_draft(self, thread_id: str) -> TodoDraft | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT payload FROM drafts WHERE thread_id = ?", (thread_id,)
            ).fetchone()
        return TodoDraft.model_validate_json(row["payload"]) if row else None

    def record(
        self,
        thread_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        result: str,
        status: str,
        elapsed_ms: int,
        limit: int,
    ) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO tool_history
                    (thread_id, tool_name, arguments, result, status, timestamp, elapsed_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    thread_id,
                    tool_name,
                    json.dumps(arguments),
                    result,
                    status,
                    datetime.now().astimezone().isoformat(),
                    elapsed_ms,
                ),
            )
            db.execute(
                """
                DELETE FROM tool_history WHERE thread_id = ? AND id IN (
                    SELECT id FROM tool_history WHERE thread_id = ?
                    ORDER BY id DESC LIMIT -1 OFFSET ?
                )
                """,
                (thread_id, thread_id, limit),
            )

    def history(self, thread_id: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT tool_name, arguments, result, status, timestamp, elapsed_ms
                FROM tool_history WHERE thread_id = ? ORDER BY id DESC
                """,
                (thread_id,),
            )
            return [
                {
                    "tool_name": row["tool_name"],
                    "tool_args": json.loads(row["arguments"]),
                    "result": row["result"],
                    "status": row["status"],
                    "timestamp": row["timestamp"],
                    "elapsed_ms": row["elapsed_ms"],
                }
                for row in rows
            ]
