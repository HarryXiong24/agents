"""Version 3: store study plans in SQLite and return three-field dictionaries."""

import sqlite3
from collections.abc import Generator
from contextlib import closing, contextmanager
from datetime import date as calendar_date
from pathlib import Path
from typing import TypedDict

# Anchor the path to this module so changing the working directory has no effect.
DATABASE_FILE = Path(__file__).resolve().parent / "data" / "study_plans.sqlite"


class StudyPlan(TypedDict):
    """A plan has exactly these fields; functions below validate data at runtime."""

    project: str
    minutes: int
    date: str


def _validate_plan_key(project: str, planned_date: str) -> tuple[str, str]:
    """Project and date identify a plan; reads and writes share this validation."""
    if not isinstance(project, str):
        raise TypeError("The study project must be a string.")
    project = project.strip()
    if not project:
        raise ValueError("The study project must not be empty.")
    if not isinstance(planned_date, str):
        raise TypeError("The study date must be a string.")
    try:
        parsed_date = calendar_date.fromisoformat(planned_date)
    except ValueError as exc:
        raise ValueError(
            "The study date must be a valid date in YYYY-MM-DD format."
        ) from exc
    # fromisoformat accepts other ISO forms; require the full calendar date here.
    if parsed_date.isoformat() != planned_date:
        raise ValueError("The study date must use YYYY-MM-DD format.")
    return project, planned_date


def _validate_plan(project: str, minutes: int, planned_date: str) -> StudyPlan:
    """Use TypeError for invalid types and ValueError for invalid values."""
    project, planned_date = _validate_plan_key(project, planned_date)
    if type(minutes) is not int:
        raise TypeError("Study duration must be an integer number of minutes.")
    if not 1 <= minutes <= 1440:
        raise ValueError("Study duration must be between 1 and 1440 minutes.")
    return {"project": project, "minutes": minutes, "date": planned_date}


def load_plans() -> list[StudyPlan]:
    """Return all plans in insertion order, or an empty list if there are none."""
    with _connect() as connection:
        rows = connection.execute(
            "SELECT project, minutes, date FROM study_plans ORDER BY rowid"
        ).fetchall()
    # sqlite3.Row supports column names; keep version 2's return shape for prompts.
    return [_validate_plan(row["project"], row["minutes"], row["date"]) for row in rows]


def save_plan(project: str, minutes: int, planned_date: str) -> StudyPlan:
    """Insert a plan or update its duration when project and date already exist."""
    plan = _validate_plan(project, minutes, planned_date)
    with _connect() as connection:
        # Bind values using ? parameters, including project names containing quotes.
        # Update only duration on a key conflict, preserving insertion order.
        connection.execute(
            """INSERT INTO study_plans (project, minutes, date) VALUES (?, ?, ?)
            ON CONFLICT(project, date) DO UPDATE SET minutes = excluded.minutes""",
            (plan["project"], plan["minutes"], plan["date"]),
        )
    # Return only after the transaction commits so tools can report success.
    return plan


def delete_plan(project: str, planned_date: str) -> bool:
    """Delete by project and date; return True if deleted, otherwise False."""
    project, planned_date = _validate_plan_key(project, planned_date)
    with _connect() as connection:
        result = connection.execute(
            "DELETE FROM study_plans WHERE project = ? AND date = ?",
            (project, planned_date),
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
                """CREATE TABLE IF NOT EXISTS study_plans (
                    project TEXT NOT NULL CHECK (length(trim(project)) > 0),
                    minutes INTEGER NOT NULL
                        CHECK (typeof(minutes) = 'integer' AND minutes BETWEEN 1 AND 1440),
                    date TEXT NOT NULL,
                    PRIMARY KEY (project, date)
                )"""
            )
            yield connection
