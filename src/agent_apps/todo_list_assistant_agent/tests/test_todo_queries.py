"""Validate todo queries while the console prints only the final assistant reply."""

import json
from unittest.mock import Mock

import httpx
import pytest
from groq import APIConnectionError
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import ValidationError

from agent_apps.todo_list_assistant_agent import console
from agent_apps.todo_list_assistant_agent.agent import memory
from agent_apps.todo_list_assistant_agent.agent.graph import build_graph
from agent_apps.todo_list_assistant_agent.agent.schemas import TodoView
from agent_apps.todo_list_assistant_agent.agent.tools import list_todos


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DATABASE_FILE", tmp_path / "todos.sqlite")


def make_model(*responses):
    model = Mock(spec=BaseChatModel)
    model.bind_tools.return_value = model
    model.invoke.side_effect = responses
    return model


def query(**args):
    return {"name": "list_todos", "args": args, "id": "query", "type": "tool_call"}


@pytest.mark.parametrize(
    "change",
    [
        {"project": " "},
        {"project": 1},
        {"minutes": True},
        {"minutes": "30"},
        {"minutes": 1.5},
        {"minutes": 0},
        {"minutes": 1441},
        {"date": "2026-02-30"},
        {"date": "20261106"},
        {"completed": True},
    ],
)
def test_todo_view_validates_record_fields(change):
    with pytest.raises(ValidationError):
        TodoView.model_validate(
            {"project": "Read", "minutes": 30, "date": "2026-11-06", **change}
        )


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"project": "Read"},
        {"date": "2026-11-06"},
        {"project": "Read", "date": "2026-11-06"},
        {"project": "Missing"},
    ],
)
def test_query_returns_validated_plain_records_without_writes(args):
    records = [
        memory.save_todo("Read", 30, "2026-11-06"),
        memory.save_todo("Walk", 20, "2026-11-07"),
    ]
    output = list_todos.invoke(query(**args))
    assert isinstance(output, ToolMessage)
    expected = [r for r in records if all(r[k] == v for k, v in args.items())]
    assert output.artifact is None
    assert json.loads(output.text) == expected
    assert memory.load_todos() == records


@pytest.mark.parametrize(
    "args", [{"project": " "}, {"date": "2026-02-30"}, {"date": "20261106"}]
)
def test_query_rejects_invalid_filters(args):
    with pytest.raises(ValueError):
        list_todos.invoke(query(**args))


def test_empty_query():
    output = list_todos.invoke(query())
    assert isinstance(output, ToolMessage)
    assert output.artifact is None
    assert json.loads(output.text) == []


def test_ordinary_reply_has_no_schema_or_second_model_call():
    model = make_model(AIMessage("Hello, how can I help?", id="reply"))
    result = build_graph(model).invoke({"messages": [HumanMessage("Hi.")]})
    assert result["messages"][-1].text == "Hello, how can I help?"
    assert result["messages"][-1].id == "reply"
    assert len(result["messages"]) == 2
    assert "response" not in result
    model.invoke.assert_called_once()
    model.with_structured_output.assert_not_called()


def test_query_reply_is_displayed_once_without_separate_rendering(
    tmp_path, monkeypatch, capsys
):
    todo = memory.save_todo("Read", 30, "2026-11-06")
    model = make_model(
        AIMessage("", tool_calls=[query()]),
        AIMessage("Read: 30 minutes on 2026-11-06."),
        AIMessage("You are welcome."),
    )
    inputs = iter(["List my todos.", "Thanks.", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    config: RunnableConfig = {"configurable": {"thread_id": "display"}}
    database = str(tmp_path / "checkpoints.sqlite")
    with SqliteSaver.from_conn_string(database) as saver:
        console.chat(build_graph(model, saver), "display")
    output = capsys.readouterr().out
    assert output.count("Read: 30 minutes on 2026-11-06.") == 1
    assert "Todos:" not in output
    assert "Assistant: You are welcome." in output
    with SqliteSaver.from_conn_string(database) as saver:
        state = build_graph(make_model(), saver).get_state(config)
        message = next(
            m for m in state.values["messages"] if isinstance(m, ToolMessage)
        )
        assert json.loads(message.text) == [todo]
        assert message.artifact is None
    model.with_structured_output.assert_not_called()


def test_query_then_approval_prints_only_final_reply(tmp_path, monkeypatch, capsys):
    memory.save_todo("Read", 30, "2026-11-06")
    model = make_model(
        AIMessage("", tool_calls=[query()]),
        AIMessage(
            "",
            tool_calls=[
                {
                    "name": "delete_todo",
                    "args": {"project": "Read", "date": "2026-11-06"},
                    "id": "delete",
                }
            ],
        ),
        AIMessage("The deletion was declined."),
    )
    inputs = iter(["Show the list, then delete Read.", "n", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        console.chat(build_graph(model, saver))
    output = capsys.readouterr().out
    assert "Todos:" not in output
    assert "Assistant: The deletion was declined." in output
    assert len(memory.load_todos()) == 1


def test_saved_query_resumes_after_model_failure_without_requery(
    tmp_path, monkeypatch, capsys
):
    memory.save_todo("Read", 30, "2026-11-06")
    model = make_model(
        AIMessage("", tool_calls=[query()]),
        APIConnectionError(request=httpx.Request("POST", "https://example.test")),
    )
    monkeypatch.setattr("builtins.input", lambda _: "Show todos.")
    database = str(tmp_path / "checkpoints.sqlite")
    with SqliteSaver.from_conn_string(database) as saver:
        console.chat(build_graph(model, saver))
    capsys.readouterr()
    recovered = make_model(AIMessage("Here are your saved todos."))
    monkeypatch.setattr("builtins.input", lambda _: "exit")
    with SqliteSaver.from_conn_string(database) as saver:
        console.chat(build_graph(recovered, saver))
        state = saver.get_tuple({"configurable": {"thread_id": "default"}})
        assert state is not None
        assert len(state.checkpoint["channel_values"]["tool_history"]) == 1
    output = capsys.readouterr().out
    assert "Todos:" not in output
    assert "Assistant: Here are your saved todos." in output


def test_natural_reply_finishes_turn_and_is_checkpointed(tmp_path):
    config: RunnableConfig = {"configurable": {"thread_id": "natural-reply"}}
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        model = make_model(AIMessage("Natural reply."))
        graph = build_graph(model, saver)
        result = graph.invoke({"messages": [HumanMessage("Hello.")]}, config)
        assert result["messages"][-1].text == "Natural reply."
        snapshot = graph.get_state(config)
        assert snapshot.next == ()
        assert snapshot.values["messages"][-1].text == "Natural reply."
        model.invoke.assert_called_once()
        model.with_structured_output.assert_not_called()
