"""Validate todos and persist them in a local SQLite database."""

import sqlite3
from collections.abc import Generator
from contextlib import closing, contextmanager
from datetime import date as calendar_date
from typing import TypedDict

from ..config import DATA_DIR

# Resolve data files from application configuration, independent of this module.
DATABASE_FILE = DATA_DIR / "todos.sqlite"


class TodoItem(TypedDict):
    """A todo has a name, an estimated duration, and a scheduled date."""

    project: str
    minutes: int
    date: str


def _validate_todo_key(project: str, scheduled_date: str) -> tuple[str, str]:
    """Project and date identify a todo; reads and writes share this validation."""
    if not isinstance(project, str):
        raise TypeError("The todo name must be a string.")
    project = project.strip()
    if not project:
        raise ValueError("The todo name must not be empty.")
    if not isinstance(scheduled_date, str):
        raise TypeError("The scheduled date must be a string.")
    try:
        parsed_date = calendar_date.fromisoformat(scheduled_date)
    except ValueError as exc:
        raise ValueError(
            "The scheduled date must be a valid date in YYYY-MM-DD format."
        ) from exc
    # fromisoformat accepts other ISO forms; require the full calendar date here.
    if parsed_date.isoformat() != scheduled_date:
        raise ValueError("The scheduled date must use YYYY-MM-DD format.")
    return project, scheduled_date


def _validate_todo(project: str, minutes: int, scheduled_date: str) -> TodoItem:
    """Use TypeError for invalid types and ValueError for invalid values."""
    project, scheduled_date = _validate_todo_key(project, scheduled_date)
    if type(minutes) is not int:
        raise TypeError("Estimated duration must be an integer number of minutes.")
    if not 1 <= minutes <= 1440:
        raise ValueError("Estimated duration must be between 1 and 1440 minutes.")
    return {"project": project, "minutes": minutes, "date": scheduled_date}


def load_todos() -> list[TodoItem]:
    """Return all todos in insertion order, or an empty list if there are none."""
    with _connect() as connection:
        rows = connection.execute(
            "SELECT project, minutes, date FROM todos ORDER BY rowid"
        ).fetchall()
    # sqlite3.Row supports column names; prompts receive ordinary dictionaries.
    return [_validate_todo(row["project"], row["minutes"], row["date"]) for row in rows]


def save_todo(project: str, minutes: int, scheduled_date: str) -> TodoItem:
    """Insert a todo or update its duration when project and date already exist."""
    todo = _validate_todo(project, minutes, scheduled_date)
    with _connect() as connection:
        # Bind values using ? parameters, including project names containing quotes.
        # Update only duration on a key conflict, preserving insertion order.
        connection.execute(
            """INSERT INTO todos (project, minutes, date) VALUES (?, ?, ?)
            ON CONFLICT(project, date) DO UPDATE SET minutes = excluded.minutes""",
            (todo["project"], todo["minutes"], todo["date"]),
        )
    # Return only after the transaction commits so tools can report success.
    return todo


def delete_todo(project: str, scheduled_date: str) -> bool:
    """Delete by project and date; return True if deleted, otherwise False."""
    project, scheduled_date = _validate_todo_key(project, scheduled_date)
    with _connect() as connection:
        result = connection.execute(
            "DELETE FROM todos WHERE project = ? AND date = ?",
            (project, scheduled_date),
        )
        deleted = result.rowcount > 0
    return deleted


@contextmanager
def _connect() -> Generator[sqlite3.Connection]:
    """Open a connection, prepare the table, commit or roll back, then close."""
    DATABASE_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Each thread opens its own connection; SQLite waits up to 10 seconds for writes.
    with closing(sqlite3.connect(DATABASE_FILE, timeout=10)) as connection:
        connection.row_factory = sqlite3.Row
        # The connection context manages transactions; closing releases the connection.
        with connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS todos (
                    project TEXT NOT NULL CHECK (length(trim(project)) > 0),
                    minutes INTEGER NOT NULL
                        CHECK (typeof(minutes) = 'integer' AND minutes BETWEEN 1 AND 1440),
                    date TEXT NOT NULL,
                    PRIMARY KEY (project, date)
                )"""
            )
            yield connection
