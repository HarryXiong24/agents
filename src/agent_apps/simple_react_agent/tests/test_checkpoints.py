"""Exercise SQLite conversation persistence with real graphs and offline models."""

import json
import sqlite3
import subprocess
import sys
from unittest.mock import Mock

import httpx
import pytest
from groq import APIConnectionError
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver

from agent_apps.simple_react_agent import checkpoints, console, memory
from agent_apps.simple_react_agent import main as app
from agent_apps.simple_react_agent.graph import build_graph


@pytest.fixture(autouse=True)
def isolate_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DATABASE_FILE", tmp_path / "study_plans.sqlite")
    monkeypatch.setattr(
        checkpoints, "CHECKPOINTS_FILE", tmp_path / "data" / "checkpoints.sqlite"
    )


def make_model(*responses):
    model = Mock(spec=BaseChatModel)
    model.bind_tools.return_value = model
    model.invoke.side_effect = responses
    return model


def test_restart_restores_messages_and_tool_results_in_another_process(tmp_path):
    code = """
import json
import sys
from pathlib import Path
from unittest.mock import Mock
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from agent_apps.simple_react_agent import memory
from agent_apps.simple_react_agent.graph import build_graph

memory.DATABASE_FILE = Path(sys.argv[1]) / "plans.sqlite"
model = Mock(spec=BaseChatModel)
model.bind_tools.return_value = model
if sys.argv[2] == "write":
    model.invoke.side_effect = [
        AIMessage(content="", tool_calls=[{
            "name": "calculate", "args": {"a": 2, "b": 60, "operation": "multiply"},
            "id": "minutes",
        }]),
        AIMessage(content="That is 120 minutes."),
    ]
    text = "I want to study Python for two hours. Convert that to minutes."
else:
    model.invoke.return_value = AIMessage(content="You mentioned Python.")
    text = "What subject did I mention?"

with SqliteSaver.from_conn_string(str(Path(sys.argv[1]) / "checkpoints.sqlite")) as saver:
    graph = build_graph(model, checkpointer=saver)
    result = graph.invoke(
        {"messages": [HumanMessage(text)]},
        config={"configurable": {"thread_id": sys.argv[3]}},
    )
    print(json.dumps([{"type": m.type, "content": m.content} for m in result["messages"]]))
"""

    def run(phase, thread):
        result = subprocess.run(
            [sys.executable, "-c", code, str(tmp_path), phase, thread],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return json.loads(result.stdout.splitlines()[-1])

    first = run("write", "python")
    assert [m["type"] for m in first] == ["human", "ai", "tool", "ai"]
    assert first[2]["content"] == "120.0"
    resumed = run("read", "python")
    assert resumed[:4] == first
    assert len(resumed) == 6
    # A different conversation has no inherited messages, even in the same file.
    separate = run("read", "english")
    assert len(separate) == 2
    assert separate[0]["content"] == "What subject did I mention?"


def test_plan_records_are_shared_but_conversation_history_is_separate(tmp_path):
    plan = memory.save_plan("Python", 60, "2026-10-29")
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        model = make_model(AIMessage(content="Hello."), AIMessage(content="Your plan."))
        graph = build_graph(model, checkpointer=saver)
        graph.invoke(
            {"messages": [HumanMessage("Private conversation A")]},
            config={"configurable": {"thread_id": "a"}},
        )
        graph.invoke(
            {"messages": [HumanMessage("List my plans")]},
            config={"configurable": {"thread_id": "b"}},
        )
        request = model.invoke.call_args.args[0]
        assert json.dumps([plan], ensure_ascii=False, indent=2) in request[0].content
        assert [m.content for m in request[1:]] == ["List my plans"]


def test_restart_after_model_failure_does_not_repeat_completed_save(
    tmp_path, monkeypatch
):
    database = str(tmp_path / "checkpoints.sqlite")
    config: RunnableConfig = {"configurable": {"thread_id": "save-plan"}}
    original_save = memory.save_plan
    save = Mock(wraps=original_save)
    monkeypatch.setattr(memory, "save_plan", save)
    first = make_model(
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "save_study_plan",
                    "args": {"project": "Python", "minutes": 60, "date": "2026-10-29"},
                    "id": "save",
                }
            ],
        ),
        APIConnectionError(
            message="Simulated model failure after saving",
            request=httpx.Request("POST", "https://example.test"),
        ),
    )
    with SqliteSaver.from_conn_string(database) as saver:
        graph = build_graph(first, checkpointer=saver)
        with pytest.raises(APIConnectionError):
            graph.invoke({"messages": [HumanMessage("Save my plan")]}, config=config)
        assert graph.get_state(config).next == ("model",)
    assert save.call_count == 1

    resumed = make_model(AIMessage(content="Your plan was saved."))
    with SqliteSaver.from_conn_string(database) as saver:
        graph = build_graph(resumed, checkpointer=saver)
        result = graph.invoke(None, config=config)
        assert graph.get_state(config).next == ()
    assert save.call_count == 1
    assert len(result["messages"]) == 4
    assert "Saved study plan" in resumed.invoke.call_args.args[0][-1].content


def test_main_opens_saver_for_chat_then_closes_it(monkeypatch):
    model = make_model(AIMessage(content="Remembered."), AIMessage(content="Python."))
    monkeypatch.setattr(app, "create_model", lambda: model)
    inputs = iter(
        [
            "0",
            "python",
            "I want to study Python",
            "exit",
            "1",
            "What subject?",
            "exit",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    app.main()
    app.main()
    assert [m.content for m in model.invoke.call_args.args[0][1:]] == [
        "I want to study Python",
        "Remembered.",
        "What subject?",
    ]
    # Reopening the file after both exits must still recover the finished state.
    with SqliteSaver.from_conn_string(str(checkpoints.CHECKPOINTS_FILE)) as saver:
        state = build_graph(model, checkpointer=saver).get_state(
            {"configurable": {"thread_id": "python"}}
        )
        assert len(state.values["messages"]) == 4
        connection = saver.conn
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")


def test_checkpoint_storage_error_is_readable(monkeypatch):
    monkeypatch.setattr(app, "create_model", Mock(return_value=Mock()))
    checkpoints.CHECKPOINTS_FILE.parent.mkdir(parents=True)
    checkpoints.CHECKPOINTS_FILE.write_bytes(b"not a SQLite database")
    with pytest.raises(SystemExit, match="Checkpoint storage failed"):
        app.main()
    assert checkpoints.CHECKPOINTS_FILE.read_bytes() == b"not a SQLite database"


def test_menu_lists_each_saved_thread_once_and_keeps_old_default(tmp_path):
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        assert checkpoints.list_threads(saver) == []
        model = make_model(*(AIMessage(content="Hello") for _ in range(3)))
        graph = build_graph(model, checkpointer=saver)
        for thread in ["python", "default", "python"]:
            graph.invoke(
                {"messages": [HumanMessage("Hello")]},
                config={"configurable": {"thread_id": thread}},
            )
        assert checkpoints.list_threads(saver) == ["default", "python"]


def test_menu_validates_choices_and_new_names_without_storage(monkeypatch, capsys):
    inputs = iter(["", "wrong", "-1", "99", "0", "  ", "0", "python", "1"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    assert console.select_thread(["python"]) == "python"
    output = capsys.readouterr().out
    assert "1. python" in output
    assert "Enter a listed number" in output
    assert "must not be empty" in output
    assert "already exists" in output


def test_new_conversation_name_is_trimmed_and_saved_only_after_first_message(
    tmp_path, monkeypatch
):
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        inputs = iter(["0", "  New conversation  "])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))
        name = console.select_thread(checkpoints.list_threads(saver))
        assert name == "New conversation"
        assert checkpoints.list_threads(saver) == []
        graph = build_graph(make_model(AIMessage(content="Hello")), checkpointer=saver)
        graph.invoke(
            {"messages": [HumanMessage("Hello")]},
            config={"configurable": {"thread_id": name}},
        )
        assert checkpoints.list_threads(saver) == [name]


@pytest.mark.parametrize("inputs", [["exit"], ["QUIT"], ["0", "exit"]])
def test_quit_from_menu_needs_no_model_or_api_key(monkeypatch, capsys, inputs):
    create_model = Mock(side_effect=AssertionError("The menu must not create a model"))
    monkeypatch.setattr(app, "create_model", create_model)
    values = iter(inputs)
    monkeypatch.setattr("builtins.input", lambda _: next(values))
    app.main()
    create_model.assert_not_called()
    output = capsys.readouterr().out
    assert "No saved conversations yet" in output
    assert "Goodbye!" in output


@pytest.mark.parametrize("error", [EOFError, KeyboardInterrupt])
def test_menu_handles_terminal_exit(monkeypatch, capsys, error):
    monkeypatch.setattr("builtins.input", Mock(side_effect=error))
    create_model = Mock()
    monkeypatch.setattr(app, "create_model", create_model)
    app.main()
    create_model.assert_not_called()
    assert "Goodbye!" in capsys.readouterr().out
