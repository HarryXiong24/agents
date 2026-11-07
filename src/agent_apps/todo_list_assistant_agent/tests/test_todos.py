"""Exercise todo prompts, tool contracts, persistence, and restart recovery offline."""

import json
import sqlite3
from contextlib import closing
from unittest.mock import Mock, patch

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from agent_apps.todo_list_assistant_agent import main as app
from agent_apps.todo_list_assistant_agent.agent import checkpoints, memory
from agent_apps.todo_list_assistant_agent.agent.graph import build_graph
from agent_apps.todo_list_assistant_agent.agent.state import AgentState
from agent_apps.todo_list_assistant_agent.agent.tools import (
    TOOLS,
    delete_todo,
    save_todo,
)
from agent_apps.todo_list_assistant_agent.config import AgentConfig


@pytest.fixture(autouse=True)
def isolate_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DATABASE_FILE", tmp_path / memory.DATABASE_FILE.name)


def make_model():
    model = Mock(spec=BaseChatModel)

    model.bind_tools.return_value = model
    model.invoke.side_effect = lambda _: AIMessage(content="Here are your todos.")
    return model


def test_new_databases_start_empty_and_ignore_previous_files(tmp_path, monkeypatch):
    previous_todos = tmp_path / "study_plans.sqlite"
    previous_checkpoints = tmp_path / "checkpoints.sqlite"
    with closing(sqlite3.connect(previous_todos)) as connection, connection:
        connection.execute(
            "CREATE TABLE study_plans (project TEXT, minutes INTEGER, date TEXT)"
        )
        connection.execute(
            "INSERT INTO study_plans VALUES (?, ?, ?)",
            ("Previous record", 60, "2026-10-29"),
        )
    with closing(sqlite3.connect(previous_checkpoints)) as connection, connection:
        connection.execute("CREATE TABLE checkpoints (thread_id TEXT)")
        connection.execute("INSERT INTO checkpoints VALUES ('previous-conversation')")
    previous_contents = {
        path: path.read_bytes() for path in (previous_todos, previous_checkpoints)
    }
    monkeypatch.setattr(
        checkpoints, "CHECKPOINTS_FILE", tmp_path / checkpoints.CHECKPOINTS_FILE.name
    )
    menu = Mock(return_value=None)
    model = Mock()
    monkeypatch.setattr(app, "select_thread", menu)
    monkeypatch.setattr(app, "create_model", model)

    app.main()

    menu.assert_called_once_with([])
    model.assert_not_called()
    assert memory.load_todos() == []
    assert memory.DATABASE_FILE.name == "todos.sqlite"
    assert checkpoints.CHECKPOINTS_FILE.name == "todo_checkpoints.sqlite"
    assert checkpoints.CHECKPOINTS_FILE.exists()
    for path, content in previous_contents.items():
        assert path.read_bytes() == content


def test_todo_prompt_reads_saved_record_without_changing_it():
    existing = memory.save_todo("Python", 60, "2026-10-29")
    model = make_model()
    result = build_graph(model).invoke({"messages": [HumanMessage("List my todos.")]})
    system = model.invoke.call_args.args[0][0].content
    assert "You are Todo List Assistant Agent" in system
    assert "# Current todo list" in system
    assert json.dumps([existing], ensure_ascii=False, indent=2) in system
    assert memory.load_todos() == [existing]
    assert len(result["messages"]) == 2


def test_todo_tools_expose_todo_names_and_three_record_fields():
    existing = memory.save_todo("Python", 60, "2026-10-29")
    arguments = {"project": "Clean room", "minutes": 30, "date": "2026-11-04"}
    assert save_todo.name == "save_todo"
    assert delete_todo.name == "delete_todo"
    assert set(save_todo.args) == {
        "project",
        "minutes",
        "date",
    }
    assert "Saved todo: Clean room, estimated 30 minutes" in save_todo.invoke(arguments)
    assert memory.load_todos() == [existing, arguments]
    assert "estimated 45 minutes" in save_todo.invoke({**arguments, "minutes": 45})
    assert memory.load_todos() == [existing, {**arguments, "minutes": 45}]
    assert "Deleted todo" in delete_todo.invoke(
        {"project": "Clean room", "date": "2026-11-04"}
    )
    assert memory.load_todos() == [existing]
    assert "No todos were deleted" in delete_todo.invoke(
        {"project": "Clean room", "date": "2026-11-04"}
    )
    assert memory.load_todos() == [existing]


@patch(
    "agent_apps.todo_list_assistant_agent.config.agent.AGENT_CONFIG",
    AgentConfig(summary_trigger_tokens=100_000),
)
def test_pending_todo_tool_call_resumes_after_restart(tmp_path, monkeypatch):
    existing = memory.save_todo("Python", 60, "2026-10-29")
    saved_messages = [
        HumanMessage(content="Save my Python todo.", id="old-user"),
        AIMessage(
            content="",
            id="old-request",
            tool_calls=[
                {
                    "name": "save_todo",
                    "args": existing,
                    "id": "old-save",
                }
            ],
        ),
        ToolMessage(
            content="Saved todo: Python, estimated 60 minutes, scheduled for 2026-10-29.",
            tool_call_id="old-save",
            id="old-result",
        ),
        AIMessage(content="Your todo was saved.", id="old-answer"),
        HumanMessage(
            content="Save a Clean room task for tomorrow, 30 minutes.",
            id="pending-user",
        ),
    ]
    summary = "The user previously discussed a Python todo and decorators."
    config: RunnableConfig = {"configurable": {"thread_id": "home-todos"}}
    database = str(tmp_path / "todo_checkpoints.sqlite")
    pending_args = {"project": "Clean room", "minutes": 30, "date": "2026-11-04"}

    def request_todo(state: AgentState):
        return {
            "messages": [
                AIMessage(
                    content="",
                    id="pending-request",
                    tool_calls=[
                        {
                            "name": "save_todo",
                            "args": pending_args,
                            "id": "pending-save",
                        }
                    ],
                )
            ]
        }

    with SqliteSaver.from_conn_string(database) as saver:
        initial = StateGraph(AgentState)
        initial.add_node("model", request_todo)
        initial.add_node("tools", ToolNode(TOOLS))
        initial.add_edge(START, "model")
        initial.add_edge("model", "tools")
        initial.add_edge("tools", END)
        initial_graph = initial.compile(checkpointer=saver, interrupt_before=["tools"])
        initial_graph.invoke(
            {"messages": saved_messages, "summary": summary}, config=config
        )
        before = initial_graph.get_state(config)
        assert before.next == ("tools",)
        saved_dump = [m.model_dump() for m in before.values["messages"]]

    save = Mock(wraps=memory.save_todo)
    monkeypatch.setattr(memory, "save_todo", save)
    model = make_model()
    with SqliteSaver.from_conn_string(database) as saver:
        graph = build_graph(model, saver)
        # Reopening restores the pending tool request and summary before resuming.
        reopened = graph.get_state(config)
        assert reopened.next == ("tools",)
        assert reopened.values["summary"] == summary
        assert [m.model_dump() for m in reopened.values["messages"]] == saved_dump
        assert memory.load_todos() == [existing]

        result = graph.invoke(None, config=config)
        assert graph.get_state(config).next == ()
        assert result["summary"] == summary
        assert [
            m.model_dump() for m in result["messages"][: len(saved_dump)]
        ] == saved_dump
        assert "Saved todo: Clean room" in result["messages"][-2].content
    save.assert_called_once_with("Clean room", 30, "2026-11-04")
    assert memory.load_todos() == [existing, pending_args]
    request = model.invoke.call_args.args[0]
    assert "Todo List Assistant Agent" in request[0].content
    assert summary in request[0].content
