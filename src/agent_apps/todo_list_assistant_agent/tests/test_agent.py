"""Check tools, ReAct, and chat history offline without model API access."""

import json
import re
import sqlite3
from unittest.mock import Mock

import httpx
import pytest
from groq import APIConnectionError
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.errors import GraphRecursionError

from agent_apps.todo_list_assistant_agent import config, console
from agent_apps.todo_list_assistant_agent import main as app
from agent_apps.todo_list_assistant_agent.agent import checkpoints, memory
from agent_apps.todo_list_assistant_agent.agent.graph import build_graph
from agent_apps.todo_list_assistant_agent.agent.tools import (
    calculate,
    delete_todo,
    get_current_time,
)
from agent_apps.todo_list_assistant_agent.config import app as app_config


@pytest.fixture(autouse=True)
def isolate_todos(tmp_path, monkeypatch):
    """Use a temporary database without reading or changing personal todos."""
    monkeypatch.setattr(memory, "DATABASE_FILE", tmp_path / "data" / "todos.sqlite")
    monkeypatch.setattr(
        checkpoints, "CHECKPOINTS_FILE", tmp_path / "data" / "todo_checkpoints.sqlite"
    )
    monkeypatch.setattr(app_config, "ENV_FILE", tmp_path / ".env")


@pytest.fixture
def checkpointer(tmp_path):
    with SqliteSaver.from_conn_string(
        str(tmp_path / "todo_checkpoints.sqlite")
    ) as saver:
        yield saver


def make_idle_graph():
    graph = Mock()
    graph.get_state.return_value.next = ()
    graph.get_state.return_value.values = {}
    return graph


def make_model(*responses):
    """Mock only model replies; run the real graph, routing, and tools."""
    model = Mock(spec=BaseChatModel)
    model.bind_tools.return_value = model
    model.invoke.side_effect = responses
    return model


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        ("add", "52.0"),
        ("subtract", "38.0"),
        ("multiply", "315.0"),
        ("divide", str(45 / 7)),
    ],
)
def test_calculate(operation, expected):
    assert calculate.invoke({"a": 45, "b": 7, "operation": operation}) == expected


def test_invalid_numbers_and_zero_division():
    assert "divisor must not be zero" in calculate.invoke(
        {"a": 1, "b": 0, "operation": "divide"}
    )
    assert "finite numbers" in calculate.invoke(
        {"a": float("inf"), "b": 1, "operation": "add"}
    )
    assert "outside" in calculate.invoke(
        {"a": 1e308, "b": 1e308, "operation": "multiply"}
    )


def test_current_time():
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", get_current_time.invoke({})
    )


def test_multistep_react():
    model = make_model(
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "calculate",
                    "args": {"a": 45, "b": 7, "operation": "multiply"},
                    "id": "first",
                }
            ],
        ),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "calculate",
                    "args": {"a": 315, "b": 60, "operation": "divide"},
                    "id": "second",
                }
            ],
        ),
        AIMessage(content="That is 315 minutes, or 5.25 hours."),
    )
    result = build_graph(model).invoke(
        {"messages": [HumanMessage("How many hours is 45 minutes a day for 7 days?")]}
    )
    messages = result["messages"]
    assert len(messages) == 6
    assert [
        (m.tool_call_id, m.content) for m in messages if isinstance(m, ToolMessage)
    ] == [
        ("first", "315.0"),
        ("second", "5.25"),
    ]
    # Verify that the next model request contains the actual previous tool result.
    assert model.invoke.call_args_list[1].args[0][-1].content == "315.0"
    assert model.invoke.call_args_list[2].args[0][-1].content == "5.25"
    assert isinstance(model.invoke.call_args_list[0].args[0][0], SystemMessage)
    assert not any(isinstance(m, SystemMessage) for m in messages)


def test_tool_validation_error_returns_to_model():
    model = make_model(
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "calculate",
                    "args": {"a": 1, "b": 2, "operation": "unknown"},
                    "id": "bad",
                }
            ],
        ),
        AIMessage(
            content="The tool arguments are invalid, so I cannot calculate this yet."
        ),
    )
    result = build_graph(model).invoke(
        {"messages": [HumanMessage("Please calculate this.")]}
    )
    tool_result = result["messages"][2]
    assert isinstance(tool_result, ToolMessage)
    assert tool_result.status == "error"
    assert "Tool execution failed" in tool_result.content
    assert model.invoke.call_count == 2


def test_console_keeps_history_without_duplicates(monkeypatch, capsys, checkpointer):
    model = make_model(
        AIMessage(content="Got it."), AIMessage(content="That is 210 minutes per week.")
    )
    inputs = iter(["", "I study 30 minutes per day", "What about a week?", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    console.chat(build_graph(model, checkpointer=checkpointer))
    second_request = model.invoke.call_args_list[1].args[0]
    assert [m.content for m in second_request[1:]] == [
        "I study 30 minutes per day",
        "Got it.",
        "What about a week?",
    ]
    assert "210 minutes per week" in capsys.readouterr().out


def test_console_keeps_failed_turn_and_resumes_before_new_input(
    monkeypatch, capsys, checkpointer
):
    model = make_model(
        AIMessage(content="Got it."),
        APIConnectionError(
            message="Simulated connection failure",
            request=httpx.Request("POST", "https://example.test"),
        ),
        AIMessage(content="Let us continue."),
    )
    inputs = iter(["First turn", "Failed turn"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    graph = build_graph(model, checkpointer=checkpointer)
    console.chat(graph)
    assert model.invoke.call_count == 2
    config: RunnableConfig = {"configurable": {"thread_id": "default"}}
    assert graph.get_state(config).next == ("model",)

    # Restarting the console finishes the saved turn before asking for new input.
    monkeypatch.setattr("builtins.input", lambda _: "exit")
    console.chat(graph)
    third_request = model.invoke.call_args_list[2].args[0]
    assert [m.content for m in third_request[1:]] == [
        "First turn",
        "Got it.",
        "Failed turn",
    ]
    assert graph.get_state(config).next == ()
    output = capsys.readouterr().out
    assert "This turn failed" in output
    assert "Resuming the unfinished turn" in output


@pytest.mark.parametrize(
    "error",
    [
        OSError("Read failed"),
        ValueError("Invalid todo value"),
        TypeError("Invalid todo type"),
    ],
)
def test_console_handles_expected_data_errors(monkeypatch, capsys, error):
    graph = make_idle_graph()
    graph.invoke.side_effect = error
    inputs = iter(["Please read my todos", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    console.chat(graph)
    assert "Check the todo storage or your input" in capsys.readouterr().out


def test_console_propagates_unexpected_error(monkeypatch):
    graph = make_idle_graph()
    graph.invoke.side_effect = RuntimeError("Simulated programming error")
    monkeypatch.setattr("builtins.input", lambda _: "Hello")
    with pytest.raises(RuntimeError, match="programming error"):
        console.chat(graph)


def test_startup_explains_configuration_error(monkeypatch):
    monkeypatch.setattr(app, "select_thread", lambda _: "test")
    monkeypatch.setattr(
        app, "load_config", Mock(side_effect=ValueError("Missing API key"))
    )
    with pytest.raises(SystemExit, match="Startup failed: Missing API key"):
        app.main()


def test_startup_propagates_graph_construction_error(monkeypatch):
    app_config.ENV_FILE.write_text("GROQ_API_KEY=isolated-test-key\n", encoding="utf-8")
    monkeypatch.setattr(app, "select_thread", lambda _: "test")
    monkeypatch.setattr(app, "create_model", Mock(return_value=Mock()))
    monkeypatch.setattr(
        app, "build_graph", Mock(side_effect=ValueError("Simulated graph wiring error"))
    )
    with pytest.raises(ValueError, match="graph wiring error"):
        app.main()


def test_console_explains_step_limit(monkeypatch, capsys):
    graph = make_idle_graph()
    graph.invoke.side_effect = GraphRecursionError("Simulated step limit")
    inputs = iter(["Repeated calls", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    console.chat(graph)
    assert "Too many tool steps" in capsys.readouterr().out


def test_missing_api_key_has_english_error(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(ValueError, match="Set GROQ_API_KEY"):
        config.load_config()


def test_save_tool_refreshes_prompt_and_survives_new_graph():
    todo = {"project": "Python", "minutes": 60, "date": "2026-10-29"}
    first_model = make_model(
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "save_todo",
                    "args": todo,
                    "id": "save",
                }
            ],
        ),
        AIMessage(content="Saved a 60-minute Python todo for October 29."),
    )
    build_graph(first_model).invoke(
        {"messages": [HumanMessage("Save a 60-minute Python todo for 2026-10-29.")]}
    )
    assert memory.load_todos() == [todo]
    # The next model call in the same turn must see the newly saved todo.
    assert (
        json.dumps([todo], ensure_ascii=False, indent=2)
        in first_model.invoke.call_args_list[1].args[0][0].content
    )

    second_model = make_model(
        AIMessage(content="Your Python todo on October 29 is 60 minutes.")
    )
    result = build_graph(second_model).invoke(
        {"messages": [HumanMessage("What todos do I have?")]}
    )
    # A new graph with no chat history still receives persisted todos in its prompt.
    assert (
        json.dumps([todo], ensure_ascii=False, indent=2)
        in second_model.invoke.call_args.args[0][0].content
    )
    assert len(result["messages"]) == 2


def test_updated_todo_reaches_next_model_request():
    memory.save_todo("Python", 30, "2026-10-29")
    updated = {"project": "Python", "minutes": 45, "date": "2026-10-29"}
    model = make_model(
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "save_todo",
                    "args": updated,
                    "id": "update",
                }
            ],
        ),
        AIMessage(content="Updated to 45 minutes."),
    )
    build_graph(model).invoke(
        {
            "messages": [
                HumanMessage(
                    "Update the Python todo on 2026-10-29 to 45 minutes and save it."
                )
            ]
        }
    )
    assert '"minutes": 30' in model.invoke.call_args_list[0].args[0][0].content
    assert '"minutes": 45' in model.invoke.call_args_list[1].args[0][0].content
    assert memory.load_todos() == [updated]


def test_temporary_calculation_keeps_saved_todos():
    saved = memory.save_todo("Python", 45, "2026-10-29")
    model = make_model(
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "calculate",
                    "args": {"a": 20, "b": 3, "operation": "multiply"},
                    "id": "temporary",
                }
            ],
        ),
        AIMessage(
            content="At a temporary 20 minutes per day, three days is 60 minutes."
        ),
    )
    result = build_graph(model).invoke(
        {
            "messages": [
                HumanMessage(
                    "Temporarily use 20 minutes per day. How much is three days?"
                )
            ]
        }
    )
    assert result["messages"][2].content == "60.0"
    assert memory.load_todos() == [saved]


def test_failed_save_does_not_report_success(monkeypatch, capsys):
    def fail_save(project, minutes, scheduled_date):
        raise OSError("Simulated disk write failure")

    monkeypatch.setattr(memory, "save_todo", fail_save)
    model = make_model(
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "save_todo",
                    "args": {"project": "Python", "minutes": 30, "date": "2026-10-29"},
                    "id": "save-failed",
                }
            ],
        ),
        AIMessage(content="Saving failed. Please try again later."),
    )
    result = build_graph(model).invoke(
        {"messages": [HumanMessage("Save a 30-minute Python todo for 2026-10-29.")]}
    )
    assert result["messages"][2].status == "error"
    assert "Saved" not in capsys.readouterr().out
    assert memory.load_todos() == []


def test_one_batch_can_save_multiple_todos():
    todos = [
        {"project": "Python", "minutes": 60, "date": "2026-10-29"},
        {"project": "English", "minutes": 30, "date": "2026-10-29"},
    ]
    model = make_model(
        AIMessage(
            content="",
            tool_calls=[
                {"name": "save_todo", "args": todo, "id": f"save-{index}"}
                for index, todo in enumerate(todos)
            ],
        ),
        AIMessage(content="Saved two todos."),
    )
    result = build_graph(model).invoke(
        {"messages": [HumanMessage("Please save both todos.")]}
    )
    assert sorted(memory.load_todos(), key=lambda todo: todo["project"]) == sorted(
        todos, key=lambda todo: todo["project"]
    )
    assert (
        len(
            [
                message
                for message in result["messages"]
                if isinstance(message, ToolMessage)
            ]
        )
        == 2
    )


def test_delete_tool_refreshes_prompt_and_survives_new_graph():
    memory.save_todo("Python", 60, "2026-10-29")
    remaining = memory.save_todo("English", 30, "2026-10-29")
    model = make_model(
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "delete_todo",
                    "args": {"project": "Python", "date": "2026-10-29"},
                    "id": "delete",
                }
            ],
        ),
        AIMessage(content="Deleted the Python todo."),
    )
    result = build_graph(model).invoke(
        {"messages": [HumanMessage("Delete the Python todo for 2026-10-29.")]}
    )
    assert "Deleted todo" in result["messages"][2].content
    assert memory.load_todos() == [remaining]
    expected = json.dumps([remaining], ensure_ascii=False, indent=2)
    assert expected in model.invoke.call_args_list[1].args[0][0].content

    # A fresh graph sees only the todos remaining after deletion.
    restarted_model = make_model(AIMessage(content="Only the English todo remains."))
    build_graph(restarted_model).invoke({"messages": [HumanMessage("List my todos.")]})
    assert expected in restarted_model.invoke.call_args.args[0][0].content


def test_delete_tool_reports_missing_todo(capsys):
    result = delete_todo.invoke({"project": "Python", "date": "2026-10-29"})
    assert "not found" in result
    assert "Deleted" not in capsys.readouterr().out
    assert memory.load_todos() == []


def test_console_explains_database_error(monkeypatch, capsys):
    graph = make_idle_graph()
    graph.invoke.side_effect = sqlite3.OperationalError("Simulated unwritable database")
    inputs = iter(["Query todos", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    console.chat(graph)
    assert "Database operation failed" in capsys.readouterr().out


@pytest.mark.parametrize("missing_date", [True, False])
def test_delete_errors_do_not_report_success(monkeypatch, capsys, missing_date):
    saved = memory.save_todo("Python", 60, "2026-10-29")
    args = {"project": "Python"}
    if not missing_date:
        args["date"] = "2026-10-29"
        monkeypatch.setattr(
            memory,
            "delete_todo",
            Mock(side_effect=OSError("Simulated delete write failure")),
        )
    model = make_model(
        AIMessage(
            content="",
            tool_calls=[{"name": "delete_todo", "args": args, "id": "delete-error"}],
        ),
        AIMessage(content="Deletion did not succeed."),
    )
    result = build_graph(model).invoke(
        {"messages": [HumanMessage("Delete this todo.")]}
    )
    assert result["messages"][2].status == "error"
    assert "Deleted" not in capsys.readouterr().out
    assert memory.load_todos() == [saved]
