"""Check SQLite CRUD, transactions, concurrent calls, and cross-process reads."""

import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from agent_apps.simple_react_agent import memory


@pytest.fixture(autouse=True)
def isolate_plans(tmp_path, monkeypatch):
    monkeypatch.setattr(
        memory, "DATABASE_FILE", tmp_path / "data" / "study_plans.sqlite"
    )


def read_in_new_process():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json, sys; from pathlib import Path; "
                "from agent_apps.simple_react_agent import memory; "
                "memory.DATABASE_FILE = Path(sys.argv[1]); "
                "print(json.dumps(memory.load_plans()))"
            ),
            str(memory.DATABASE_FILE),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_first_start_creates_database_with_only_three_columns():
    assert memory.load_plans() == []
    assert memory.DATABASE_FILE.exists()
    with closing(sqlite3.connect(memory.DATABASE_FILE)) as connection:
        assert [
            row[1] for row in connection.execute("PRAGMA table_info(study_plans)")
        ] == ["project", "minutes", "date"]


def test_save_multiple_plans_and_update_only_same_project_date():
    first = memory.save_plan(" Python ", 60, "2026-10-29")
    second = memory.save_plan("English", 30, "2026-10-29")
    third = memory.save_plan("Python", 45, "2026-10-30")
    assert first == {"project": "Python", "minutes": 60, "date": "2026-10-29"}
    assert memory.load_plans() == [first, second, third]
    updated = memory.save_plan("Python", 90, "2026-10-29")
    assert memory.load_plans() == [updated, second, third]
    assert all(
        set(plan) == {"project", "minutes", "date"} for plan in memory.load_plans()
    )


@pytest.mark.parametrize("deleted", [False, True])
def test_new_process_reads_committed_plans(deleted):
    saved = memory.save_plan("Python", 60, "2026-10-29")
    if deleted:
        assert memory.delete_plan("Python", "2026-10-29")
    assert read_in_new_process() == ([] if deleted else [saved])


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("project", " ", ValueError),
        ("project", 123, TypeError),
        ("minutes", 0, ValueError),
        ("minutes", -1, ValueError),
        ("minutes", 1441, ValueError),
        ("minutes", 30.5, TypeError),
        ("minutes", "30", TypeError),
        ("minutes", True, TypeError),
        ("date", "2026-02-30", ValueError),
        ("date", "20261029", ValueError),
        ("date", "2026-W44-4", ValueError),
        ("date", "2026-2-3", ValueError),
        ("date", "", ValueError),
        ("date", 20261029, TypeError),
    ],
)
def test_invalid_save_keeps_existing_plans(field, value, error):
    saved = memory.save_plan("Python", 60, "2026-10-29")
    args = {"project": "English", "minutes": 30, "date": "2026-10-30"}
    args[field] = value
    with pytest.raises(error):
        memory.save_plan(args["project"], args["minutes"], args["date"])
    assert memory.load_plans() == [saved]


def test_delete_only_matches_both_project_and_date():
    memory.save_plan("Python", 60, "2026-10-29")
    same_project = memory.save_plan("Python", 45, "2026-10-30")
    same_date = memory.save_plan("English", 30, "2026-10-29")
    assert memory.delete_plan(" Python ", "2026-10-29") is True
    assert memory.load_plans() == [same_project, same_date]
    assert memory.delete_plan("Python", "2026-10-29") is False
    assert memory.load_plans() == [same_project, same_date]


def test_delete_missing_plan_returns_false():
    assert memory.delete_plan("Python", "2026-10-29") is False
    assert memory.load_plans() == []


@pytest.mark.parametrize(
    ("project", "planned_date", "error"),
    [
        (" ", "2026-10-29", ValueError),
        (None, "2026-10-29", TypeError),
        ("Python", "2026-02-30", ValueError),
        ("Python", "20261029", ValueError),
        ("Python", None, TypeError),
    ],
)
def test_invalid_delete_preserves_plans(project, planned_date, error):
    saved = memory.save_plan("Python", 60, "2026-10-29")
    with pytest.raises(error):
        memory.delete_plan(project, planned_date)
    assert memory.load_plans() == [saved]


def test_concurrent_first_saves_keep_every_plan():
    with ThreadPoolExecutor(max_workers=4) as pool:
        saved = list(
            pool.map(
                lambda index: memory.save_plan(f"Project{index}", 30, "2026-10-29"),
                range(12),
            )
        )
    assert sorted(memory.load_plans(), key=lambda plan: plan["project"]) == sorted(
        saved, key=lambda plan: plan["project"]
    )


def test_concurrent_save_and_delete_do_not_lose_other_plan():
    memory.save_plan("Python", 60, "2026-10-29")
    with ThreadPoolExecutor(max_workers=2) as pool:
        saved = pool.submit(memory.save_plan, "English", 30, "2026-10-29")
        deleted = pool.submit(memory.delete_plan, "Python", "2026-10-29")
        saved_plan = saved.result()
        assert deleted.result() is True
    assert memory.load_plans() == [saved_plan]


def test_sql_parameters_preserve_project_with_quotes():
    project = "Python's 基础'; DROP TABLE study_plans; --"
    saved = memory.save_plan(project, 60, "2026-10-29")
    assert memory.load_plans() == [saved]
    assert memory.delete_plan(project, "2026-10-29") is True
    assert memory.load_plans() == []


def test_transaction_rolls_back_and_connection_closes():
    saved = memory.save_plan("Python", 60, "2026-10-29")
    with pytest.raises(sqlite3.IntegrityError), memory._connect() as connection:
        connection.execute("UPDATE study_plans SET minutes = 90")
        connection.execute(
            "INSERT INTO study_plans VALUES (?, ?, ?)", ("English", 0, "2026-10-29")
        )
    assert memory.load_plans() == [saved]
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")


@pytest.mark.parametrize("operation", ["save", "delete"])
def test_failed_write_preserves_plans(operation):
    saved = memory.save_plan("Python", 60, "2026-10-29")
    event = "INSERT" if operation == "save" else "DELETE"
    with closing(sqlite3.connect(memory.DATABASE_FILE)) as connection:
        connection.execute(f"""CREATE TRIGGER fail_write AFTER {event} ON study_plans
            BEGIN SELECT RAISE(ABORT, 'Simulated write failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="Simulated write failure"):
        if operation == "save":
            memory.save_plan("English", 30, "2026-10-29")
        else:
            memory.delete_plan("Python", "2026-10-29")
    assert memory.load_plans() == [saved]


@pytest.mark.parametrize(
    "old_contents",
    [
        '[{"project": "Old plan", "minutes": 60, "date": "2026-10-29"}]',
        "Invalid old JSON",
    ],
)
def test_old_json_is_ignored(old_contents):
    old_file = memory.DATABASE_FILE.with_suffix(".json")
    old_file.parent.mkdir(parents=True)
    old_file.write_text(old_contents, encoding="utf-8")
    assert memory.load_plans() == []
    saved = memory.save_plan("New plan", 30, "2026-10-30")
    assert read_in_new_process() == [saved]
    assert old_file.read_text(encoding="utf-8") == old_contents


def test_corrupted_database_is_reported_without_overwrite():
    memory.DATABASE_FILE.parent.mkdir(parents=True)
    memory.DATABASE_FILE.write_bytes(b"invalid database")
    with pytest.raises(sqlite3.DatabaseError):
        memory.load_plans()
    assert memory.DATABASE_FILE.read_bytes() == b"invalid database"
