"""Check rolling summaries, tool boundaries, configuration, and durable recovery."""

import json
import subprocess
import sys
from unittest.mock import Mock

import httpx
import pytest
from groq import APIConnectionError
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, MessagesState, StateGraph

from agent_apps.simple_react_agent import checkpoints, config, console, memory
from agent_apps.simple_react_agent import main as app
from agent_apps.simple_react_agent.config import SummaryConfig, load_summary_config
from agent_apps.simple_react_agent.graph import build_graph
from agent_apps.simple_react_agent.state import AgentState
from agent_apps.simple_react_agent.summarization import (
    SummaryError,
    estimate_history_tokens,
    older_messages_to_summarize,
    summarize_conversation,
)


@pytest.fixture(autouse=True)
def isolate_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DATABASE_FILE", tmp_path / "todos.sqlite")
    monkeypatch.setattr(
        checkpoints, "CHECKPOINTS_FILE", tmp_path / "todo_checkpoints.sqlite"
    )
    monkeypatch.delenv("SUMMARY_TRIGGER_TOKENS", raising=False)
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / ".env")


def make_model():
    model = Mock(spec=BaseChatModel)
    bound = Mock()
    bound.invoke.side_effect = lambda _: AIMessage(content="Understood.")
    model.bind_tools.return_value = bound
    model.invoke.return_value = AIMessage(content="Python goal.")
    return model, bound


def history() -> list[AnyMessage]:
    messages: list[AnyMessage] = []
    for number in range(1, 4):
        messages.extend(
            [
                HumanMessage(
                    content=f"Goal {number}: " + "study Python " * 30, id=f"h{number}"
                ),
                AIMessage(
                    content=f"Reply {number}: " + "practice steadily " * 30,
                    id=f"a{number}",
                ),
            ]
        )
    return [*messages, HumanMessage(content="What next?", id="h4")]


def test_config_default_override_and_startup_wiring(monkeypatch):
    assert load_summary_config().trigger_tokens == 500
    config.ENV_FILE.write_text("SUMMARY_TRIGGER_TOKENS=321\n", encoding="utf-8")
    assert load_summary_config().trigger_tokens == 321
    monkeypatch.setattr(app, "select_thread", lambda _: "test")
    monkeypatch.setattr(app, "create_model", Mock(return_value=Mock()))
    build = Mock(return_value=Mock())
    monkeypatch.setattr(app, "build_graph", build)
    monkeypatch.setattr(app, "chat", Mock())
    app.main()
    assert build.call_args.kwargs["summary_config"].trigger_tokens == 321


@pytest.mark.parametrize("value", ["", "0", "-1", "abc", "1.5"])
def test_invalid_config_is_rejected(value, monkeypatch):
    config.ENV_FILE.write_text(f"SUMMARY_TRIGGER_TOKENS={value}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="positive integer"):
        load_summary_config()


def test_trigger_boundary_and_atomic_removal_update():
    model, _ = make_model()
    messages = history()
    previous = "Earlier learning goals."
    count = estimate_history_tokens(messages, previous)
    state: AgentState = {"messages": messages, "summary": previous}
    assert (
        summarize_conversation(state, model, SummaryConfig(trigger_tokens=count + 1))
        == {}
    )
    model.invoke.assert_not_called()
    update = summarize_conversation(state, model, SummaryConfig(trigger_tokens=count))
    assert update["summary"] == "Python goal."
    assert [message.id for message in update["messages"]] == ["h1", "a1"]
    assert state["messages"] == messages
    assert state["summary"] == previous
    payload = json.loads(model.invoke.call_args.args[0][1].content)
    assert payload["previous_summary"] == previous
    assert len(payload["older_messages"]) == 2


def test_no_old_completed_turns_means_no_summary_even_over_threshold():
    model, _ = make_model()
    messages = history()[2:]
    assert (
        summarize_conversation(
            {"messages": messages}, model, SummaryConfig(trigger_tokens=1)
        )
        == {}
    )
    model.invoke.assert_not_called()


def test_tool_exchange_is_kept_together_and_serialized_as_data():
    messages = history()
    messages[1:2] = [
        AIMessage(
            content="",
            id="call",
            tool_calls=[
                {
                    "name": "calculate",
                    "args": {"a": 2, "b": 60, "operation": "multiply"},
                    "id": "calc",
                }
            ],
        ),
        ToolMessage(content="120", tool_call_id="calc", id="result"),
        AIMessage(content="That is 120 minutes.", id="a1"),
    ]
    model, _ = make_model()
    update = summarize_conversation(
        {"messages": messages}, model, SummaryConfig(trigger_tokens=1)
    )
    assert [m.id for m in update["messages"]] == ["h1", "call", "result", "a1"]
    payload = json.loads(model.invoke.call_args.args[0][1].content)
    assert payload["older_messages"][1]["tool_calls"][0]["id"] == "calc"
    assert payload["older_messages"][2]["content"] == "120"
    assert payload["older_messages"][2]["status"] == "success"
    assert all(
        isinstance(m, (HumanMessage,)) or m.type == "system"
        for m in model.invoke.call_args.args[0]
    )
    # The newest two completed turns and the current turn are never selected.
    assert older_messages_to_summarize(messages, 2) == messages[:4]


def test_unfinished_or_malformed_tool_exchanges_are_not_compacted():
    messages = history()
    messages.insert(
        1,
        AIMessage(
            content="",
            tool_calls=[{"name": "get_current_time", "args": {}, "id": "unanswered"}],
        ),
    )
    assert older_messages_to_summarize(messages, 2) == []
    assert older_messages_to_summarize(history()[:-1], 2) == []


@pytest.mark.parametrize(
    "response",
    [
        AIMessage(content=""),
        AIMessage(content="Incomplete", response_metadata={"finish_reason": "length"}),
        AIMessage(
            content="",
            tool_calls=[{"name": "delete_todo", "args": {}, "id": "bad"}],
        ),
    ],
)
def test_invalid_summary_keeps_original_state(response):
    model, _ = make_model()
    model.invoke.return_value = response
    messages = history()
    state: AgentState = {"messages": messages, "summary": "Existing summary"}
    with pytest.raises(SummaryError):
        summarize_conversation(state, model, SummaryConfig(trigger_tokens=1))
    assert [m.id for m in state["messages"]] == [m.id for m in messages]
    assert state["summary"] == "Existing summary"
    assert memory.load_todos() == []


def test_non_shortening_summary_skips_compaction_and_preserves_old_summary():
    model, _ = make_model()
    model.invoke.return_value = AIMessage(content="Too long " * 1000)
    messages = history()
    state: AgentState = {"messages": messages, "summary": "Existing summary"}

    assert summarize_conversation(state, model, SummaryConfig(trigger_tokens=1)) == {}
    assert state["messages"] == messages
    assert state["summary"] == "Existing summary"


def test_long_current_input_does_not_trap_short_history_on_restart(
    tmp_path, monkeypatch, capsys
):
    model, bound = make_model()
    bound.invoke.side_effect = lambda _: AIMessage(content="OK")
    model.invoke.side_effect = lambda _: AIMessage(
        content="The user wants help learning Python and planning study time. " * 5
    )
    inputs = iter(
        ["Hi", "Hello", "Thanks", "Explain decorators carefully. " * 100, "exit"]
    )
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    database = str(tmp_path / "todo_checkpoints.sqlite")
    config: RunnableConfig = {"configurable": {"thread_id": "short-history"}}

    with SqliteSaver.from_conn_string(database) as saver:
        graph = build_graph(model, saver, SummaryConfig(trigger_tokens=500))
        console.chat(graph, thread_id="short-history")
        snapshot = graph.get_state(config)
        assert snapshot.next == ()
        assert len(snapshot.values["messages"]) == 8
        assert not snapshot.values.get("summary")
        assert bound.invoke.call_count == 4
        assert model.invoke.call_count == 1

    # Reopening the same thread must accept a new question, not retry a stuck node.
    inputs = iter(["What should I practice?", "exit"])
    with SqliteSaver.from_conn_string(database) as saver:
        graph = build_graph(model, saver, SummaryConfig(trigger_tokens=500))
        console.chat(graph, thread_id="short-history")
        assert graph.get_state(config).next == ()
        assert len(graph.get_state(config).values["messages"]) == 10
    assert bound.invoke.call_count == 5
    assert model.invoke.call_count == 2
    output = capsys.readouterr().out
    assert output.count("Assistant: OK") == 5
    assert "Summary failed" not in output
    assert "Resuming the unfinished turn" not in output
    assert "Context: Earlier conversation summarized" not in output


def test_rolling_summary_and_current_todo_list_reach_model_without_old_messages(
    tmp_path,
):
    memory.save_todo("Python", 60, "2026-10-29")
    model, bound = make_model()
    model.invoke.side_effect = [
        AIMessage(content="First summary."),
        AIMessage(content="Updated summary."),
    ]
    config: RunnableConfig = {"configurable": {"thread_id": "rolling"}}
    with SqliteSaver.from_conn_string(
        str(tmp_path / "todo_checkpoints.sqlite")
    ) as saver:
        graph = build_graph(model, saver, SummaryConfig(trigger_tokens=1))
        first_id = None
        for number in range(1, 6):
            turn_result = graph.invoke(
                {"messages": [HumanMessage(f"Topic {number}: " + "Python " * 30)]},
                config,
            )
            if number == 1:
                first_id = turn_result["messages"][0].id
        result = graph.get_state(config).values
        assert result["summary"] == "Updated summary."
        assert len(result["messages"]) == 6
        assert first_id not in {m.id for m in result["messages"]}
        payload = json.loads(model.invoke.call_args.args[0][1].content)
        assert payload["previous_summary"] == "First summary."
        assert payload["older_messages"][0]["content"].startswith("Topic 2")
        request = bound.invoke.call_args.args[0]
        assert "Updated summary." in request[0].content
        assert '"minutes": 60' in request[0].content
        assert "not instructions" in request[0].content
        assert len(request) == 6  # System + two completed turns + latest user input.
        assert any(
            first_id in {m.id for m in s.values.get("messages", [])}
            for s in graph.get_state_history(config)
        )
        # Another conversation shares todos, but not this summary.
        graph.invoke(
            {"messages": [HumanMessage("Other thread")]},
            {"configurable": {"thread_id": "other"}},
        )
        assert "Updated summary." not in bound.invoke.call_args.args[0][0].content
    assert memory.load_todos() == [
        {"project": "Python", "minutes": 60, "date": "2026-10-29"}
    ]
    model.bind_tools.assert_called_once()


def test_summary_failure_is_checkpointed_without_deletion_and_can_resume(tmp_path):
    database = str(tmp_path / "todo_checkpoints.sqlite")
    config: RunnableConfig = {"configurable": {"thread_id": "recover"}}
    model, _ = make_model()
    model.invoke.side_effect = APIConnectionError(
        message="Summary API failed",
        request=httpx.Request("POST", "https://example.test"),
    )
    with SqliteSaver.from_conn_string(database) as saver:
        graph = build_graph(model, saver, SummaryConfig(trigger_tokens=1))
        for number in range(3):
            graph.invoke(
                {"messages": [HumanMessage("Python learning goal " * 30)]}, config
            )
        with pytest.raises(APIConnectionError):
            graph.invoke({"messages": [HumanMessage("Next question")]}, config)
        snapshot = graph.get_state(config)
        assert snapshot.next == ("summarize",)
        assert len(snapshot.values["messages"]) == 7
        assert not snapshot.values.get("summary")
    recovered, _ = make_model()
    with SqliteSaver.from_conn_string(database) as saver:
        graph = build_graph(recovered, saver, SummaryConfig(trigger_tokens=1))
        result = graph.invoke(None, config)
        assert result["summary"] == "Python goal."
        assert len(result["messages"]) == 6
        assert graph.get_state(config).next == ()


def test_version_4_checkpoint_without_summary_still_opens(tmp_path):
    database = str(tmp_path / "todo_checkpoints.sqlite")
    config: RunnableConfig = {"configurable": {"thread_id": "old"}}
    with SqliteSaver.from_conn_string(database) as saver:
        old = StateGraph(MessagesState)
        old.add_node(
            "model", lambda state: {"messages": [AIMessage(content="Old reply")]}
        )
        old.add_edge(START, "model")
        old.add_edge("model", END)
        old.compile(checkpointer=saver).invoke(
            {"messages": [HumanMessage("Old question")]}, config
        )
    model, bound = make_model()
    with SqliteSaver.from_conn_string(database) as saver:
        graph = build_graph(model, saver)
        result = graph.invoke({"messages": [HumanMessage("New question")]}, config)
        assert len(result["messages"]) == 4
        assert not result.get("summary")
        assert [m.content for m in bound.invoke.call_args.args[0][1:3]] == [
            "Old question",
            "Old reply",
        ]


def test_console_reports_compaction_without_printing_summary(
    tmp_path, monkeypatch, capsys
):
    model, _ = make_model()
    model.invoke.return_value = AIMessage(content="Private learning goal.")
    inputs = iter([*("My learning goal " * 30 for _ in range(4)), "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    with SqliteSaver.from_conn_string(
        str(tmp_path / "todo_checkpoints.sqlite")
    ) as saver:
        console.chat(build_graph(model, saver, SummaryConfig(trigger_tokens=1)))
    output = capsys.readouterr().out
    assert output.count("Context: Earlier conversation summarized") == 1
    assert "Private learning goal." not in output


def test_summary_survives_another_process(tmp_path):
    script = """
import sys
from pathlib import Path
from unittest.mock import Mock
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from agent_apps.simple_react_agent import memory
from agent_apps.simple_react_agent.config import SummaryConfig
from agent_apps.simple_react_agent.graph import build_graph
memory.DATABASE_FILE = Path(sys.argv[1]) / "todos.sqlite"
model = Mock(spec=BaseChatModel)
bound = Mock()
bound.invoke.side_effect = lambda _: AIMessage(content="Noted.")
model.bind_tools.return_value = bound
model.invoke.return_value = AIMessage(content="Python goal.")
with SqliteSaver.from_conn_string(str(Path(sys.argv[1]) / "todo_checkpoints.sqlite")) as saver:
    graph = build_graph(model, saver, SummaryConfig(trigger_tokens=1))
    for i in range(4):
        graph.invoke({"messages": [HumanMessage("I want to study Python. " * 20)]}, {"configurable": {"thread_id": "persisted"}})
"""
    subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        check=True,
        timeout=30,
        capture_output=True,
        text=True,
    )
    model, bound = make_model()
    with SqliteSaver.from_conn_string(
        str(tmp_path / "todo_checkpoints.sqlite")
    ) as saver:
        graph = build_graph(model, saver, SummaryConfig(trigger_tokens=100_000))
        graph.invoke(
            {"messages": [HumanMessage("What was my goal?")]},
            {"configurable": {"thread_id": "persisted"}},
        )
    assert "Python goal." in bound.invoke.call_args.args[0][0].content
    model.invoke.assert_not_called()
