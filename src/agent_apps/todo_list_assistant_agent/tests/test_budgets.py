"""Check completed-call limits, protocol pairing, new turns, and checkpoint replay."""

import json
from unittest.mock import Mock

import httpx
import pytest
from groq import APIConnectionError
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from agent_apps.todo_list_assistant_agent import console
from agent_apps.todo_list_assistant_agent.agent import memory
from agent_apps.todo_list_assistant_agent.agent.graph import build_graph
from agent_apps.todo_list_assistant_agent.agent.state import AgentState
from agent_apps.todo_list_assistant_agent.config import AgentConfig
from agent_apps.todo_list_assistant_agent.config import agent as agent_settings


@pytest.fixture(autouse=True)
def isolate_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DATABASE_FILE", tmp_path / "todos.sqlite")


def make_model(*responses):
    model = Mock(spec=BaseChatModel)
    model.bind_tools.return_value = model
    model.invoke.side_effect = responses
    return model


def new_turn(text: str) -> AgentState:
    return {
        "messages": [HumanMessage(text)],
        "model_calls_this_turn": 0,
        "tool_calls_this_turn": 0,
    }


def calculate(call_id="calc"):
    return {
        "name": "calculate",
        "args": {"a": 2, "b": 3, "operation": "add"},
        "id": call_id,
    }


def assert_paired(messages):
    pending = set()
    for message in messages:
        if isinstance(message, AIMessage):
            assert not pending
            pending = {call["id"] for call in message.tool_calls}
        elif isinstance(message, ToolMessage):
            assert message.tool_call_id in pending
            pending.remove(message.tool_call_id)
        elif isinstance(message, HumanMessage):
            assert not pending
    assert not pending


@pytest.mark.parametrize("limit", [1, 2])
def test_model_limit_boundary_finishes_without_extra_generation(
    tmp_path, monkeypatch, limit
):
    monkeypatch.setattr(
        agent_settings, "AGENT_CONFIG", AgentConfig(max_model_calls_per_turn=limit)
    )
    model = make_model(AIMessage("", tool_calls=[calculate()]), AIMessage("Five."))
    config: RunnableConfig = {"configurable": {"thread_id": "model-budget"}}
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        graph = build_graph(model, saver)
        result = graph.invoke(new_turn("Calculate."), config)
        assert graph.get_state(config).next == ()
        assert result["model_calls_this_turn"] == limit
        assert result["tool_calls_this_turn"] == 1
        assert_paired(result["messages"])
    assert model.invoke.call_count == limit
    if limit == 1:
        assert "model-call limit" in result["messages"][-1].text
    else:
        assert result["messages"][-1].text == "Five."


def test_tool_overflow_rejects_entire_batch_before_effects_or_approval(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(
        agent_settings, "AGENT_CONFIG", AgentConfig(max_tool_calls_per_turn=2)
    )
    memory.save_todo("Keep", 20, "2026-11-09")
    calls = [
        {
            "name": "save_todo",
            "args": {"project": "New", "minutes": 10, "date": "2026-11-09"},
            "id": "save",
        },
        {
            "name": "delete_todo",
            "args": {"project": "Keep", "date": "2026-11-09"},
            "id": "delete",
        },
    ]
    model = make_model(
        AIMessage("", tool_calls=[calculate()]), AIMessage("", tool_calls=calls)
    )
    config: RunnableConfig = {"configurable": {"thread_id": "tool-budget"}}
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        graph = build_graph(model, saver)
        result = graph.invoke(new_turn("Calculate, save, then delete."), config)
        assert not result.get("__interrupt__")
        assert graph.get_state(config).next == ()
        assert result["tool_calls_this_turn"] == 1
        assert result["model_calls_this_turn"] == 2
        assert_paired(result["messages"])
    assert len(memory.load_todos()) == 1
    assert memory.load_todos()[0]["project"] == "Keep"
    declined = [
        m
        for m in result["messages"]
        if isinstance(m, ToolMessage) and m.tool_call_id in {"save", "delete"}
    ]
    assert len(declined) == 2
    assert all(m.status == "error" and "Not executed" in m.text for m in declined)
    assert "remaining tool-call budget" in result["messages"][-1].text
    assert [record["tool_name"] for record in result["tool_history"]] == [
        "calculate",
        "save_todo",
        "delete_todo",
    ]
    output = capsys.readouterr().out
    assert "name=save_todo" not in output and "name=delete_todo" not in output
    assert model.invoke.call_count == 2


def test_exact_tool_allowance_includes_history_lookup_and_handled_errors(monkeypatch):
    monkeypatch.setattr(
        agent_settings, "AGENT_CONFIG", AgentConfig(max_tool_calls_per_turn=2)
    )
    invalid = {
        "name": "calculate",
        "args": {"a": 1, "b": 2, "operation": "invalid"},
        "id": "invalid",
    }
    lookup = {"name": "get_tool_history", "args": {}, "id": "lookup"}
    model = make_model(AIMessage("", tool_calls=[invalid, lookup]), AIMessage("Done."))
    result = build_graph(model).invoke(new_turn("Try a calculation and show history."))
    assert result["tool_calls_this_turn"] == 2
    assert result["messages"][-1].text == "Done."
    assert len(result["tool_history"]) == 1
    assert result["tool_history"][0]["tool_name"] == "calculate"
    assert_paired(result["messages"])


def test_console_new_input_resets_usage_and_keeps_history(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(
        agent_settings,
        "AGENT_CONFIG",
        AgentConfig(max_model_calls_per_turn=1, max_tool_calls_per_turn=1),
    )
    model = make_model(
        AIMessage("", tool_calls=[calculate("first")]),
        AIMessage("", tool_calls=[calculate("second")]),
    )
    inputs = iter(["First calculation.", "Second calculation.", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    config: RunnableConfig = {"configurable": {"thread_id": "console-reset"}}
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        graph = build_graph(model, saver)
        console.chat(graph, "console-reset")
        state = graph.get_state(config)
        assert state.next == ()
        assert state.values["model_calls_this_turn"] == 1
        assert state.values["tool_calls_this_turn"] == 1
        assert len(state.values["tool_history"]) == 2
        assert_paired(state.values["messages"])
    assert model.invoke.call_count == 2
    assert (
        capsys.readouterr().out.count(
            "Assistant: This turn reached the model-call limit"
        )
        == 2
    )


@pytest.mark.parametrize("approved", [True, False])
def test_approval_resume_keeps_model_count_and_counts_completed_batch_once(
    tmp_path, monkeypatch, approved
):
    monkeypatch.setattr(
        agent_settings,
        "AGENT_CONFIG",
        AgentConfig(
            max_model_calls_per_turn=1,
            max_tool_calls_per_turn=2,
            approval_tools=("save_todo",),
        ),
    )
    todo = {"project": "Walk", "minutes": 20, "date": "2026-11-09"}
    calls = [calculate(), {"name": "save_todo", "args": todo, "id": "save"}]
    config: RunnableConfig = {"configurable": {"thread_id": "approval"}}
    database = str(tmp_path / "checkpoints.sqlite")
    model = make_model(AIMessage("", tool_calls=calls))
    with SqliteSaver.from_conn_string(database) as saver:
        graph = build_graph(model, saver)
        paused = graph.invoke(new_turn("Calculate, then save Walk."), config)
        assert paused["__interrupt__"]
        assert paused["model_calls_this_turn"] == 1
        assert paused["tool_calls_this_turn"] == 0
    recovered_model = make_model()
    with SqliteSaver.from_conn_string(database) as saver:
        graph = build_graph(recovered_model, saver)
        pending = graph.get_state(config)
        result = graph.invoke(
            Command(resume={pending.interrupts[0].id: {"approved": approved}}), config
        )
        assert result["tool_calls_this_turn"] == 2
        assert result["model_calls_this_turn"] == 1
        assert len(result["tool_history"]) == 2
        assert graph.get_state(config).next == ()
        assert_paired(result["messages"])
    assert memory.load_todos() == ([todo] if approved else [])
    recovered_model.invoke.assert_not_called()
    assert "model-call limit" in result["messages"][-1].text


def test_failed_model_call_is_not_counted_until_completed_on_resume(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        agent_settings, "AGENT_CONFIG", AgentConfig(max_model_calls_per_turn=1)
    )
    config: RunnableConfig = {"configurable": {"thread_id": "failure"}}
    database = str(tmp_path / "checkpoints.sqlite")
    failing = make_model(
        APIConnectionError(request=httpx.Request("POST", "https://example.test"))
    )
    with SqliteSaver.from_conn_string(database) as saver:
        graph = build_graph(failing, saver)
        with pytest.raises(APIConnectionError):
            graph.invoke(new_turn("Hello."), config)
        assert graph.get_state(config).values["model_calls_this_turn"] == 0
        assert graph.get_state(config).next == ("model",)
    recovered = make_model(AIMessage("Hello."))
    with SqliteSaver.from_conn_string(database) as saver:
        graph = build_graph(recovered, saver)
        result = graph.invoke(None, config)
        assert result["model_calls_this_turn"] == 1
        assert result["messages"][-1].text == "Hello."
        assert graph.get_state(config).next == ()


def test_direct_callers_explicitly_reset_allowance_for_new_turns(tmp_path, monkeypatch):
    monkeypatch.setattr(
        agent_settings, "AGENT_CONFIG", AgentConfig(max_model_calls_per_turn=1)
    )
    model = make_model(AIMessage("First answer."), AIMessage("New allowance."))
    config: RunnableConfig = {"configurable": {"thread_id": "direct-reset"}}
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        graph = build_graph(model, saver)
        graph.invoke(new_turn("First input."), config)
        inherited = graph.invoke(
            {"messages": [HumanMessage("No reset supplied.")]}, config
        )
        assert "model-call limit" in inherited["messages"][-1].text
        model.invoke.assert_called_once()
        reset = graph.invoke(new_turn("New input with reset."), config)
        assert reset["messages"][-1].text == "New allowance."
        assert reset["model_calls_this_turn"] == 1
        assert graph.get_state(config).next == ()


def test_draft_model_call_is_outside_react_budget(monkeypatch):
    monkeypatch.setattr(
        agent_settings,
        "AGENT_CONFIG",
        AgentConfig(max_model_calls_per_turn=1, max_tool_calls_per_turn=1),
    )
    call = {
        "name": "generate_todo_draft",
        "args": {"projects": ["Walk"], "date": "2026-11-09", "max_minutes": 30},
        "id": "draft",
    }
    model = make_model(AIMessage("", tool_calls=[call]))
    candidate = {"todos": [{"project": "Walk", "minutes": 20, "date": "2026-11-09"}]}
    model.with_structured_output.return_value.invoke.return_value = {
        "raw": AIMessage(json.dumps(candidate)),
        "parsed": candidate,
        "parsing_error": None,
    }
    result = build_graph(model).invoke(new_turn("Propose a draft."))
    assert result["todo_draft"] == candidate
    assert result["model_calls_this_turn"] == 1
    assert result["tool_calls_this_turn"] == 1
    model.invoke.assert_called_once()
    model.with_structured_output.return_value.invoke.assert_called_once()
    assert memory.load_todos() == []


def test_summary_call_is_outside_react_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(
        agent_settings,
        "AGENT_CONFIG",
        AgentConfig(
            max_model_calls_per_turn=1, summary_trigger_tokens=1, summary_keep_turns=1
        ),
    )
    model = make_model(AIMessage("Old discussion."))
    business = Mock()
    business.invoke.return_value = AIMessage("Current answer.")
    model.bind_tools.return_value = business
    history = [
        HumanMessage("An earlier lengthy discussion about tasks and available time."),
        AIMessage(
            "A completed earlier answer with details about possible arrangements."
        ),
        HumanMessage("Another question."),
        AIMessage("Another completed answer."),
        HumanMessage("Current question."),
    ]
    result = build_graph(model).invoke(
        {"messages": history, "model_calls_this_turn": 0, "tool_calls_this_turn": 0}
    )
    assert result["summary"] == "Old discussion."
    assert result["model_calls_this_turn"] == 1
    assert result["messages"][-1].text == "Current answer."
    model.invoke.assert_called_once()
    business.invoke.assert_called_once()


def test_rejected_draft_batch_clears_candidate_without_generating(monkeypatch):
    monkeypatch.setattr(
        agent_settings, "AGENT_CONFIG", AgentConfig(max_tool_calls_per_turn=1)
    )
    call = {
        "name": "generate_todo_draft",
        "args": {"projects": ["Walk"], "date": "2026-11-09", "max_minutes": 30},
        "id": "draft",
    }
    model = make_model(
        AIMessage("", tool_calls=[calculate()]), AIMessage("", tool_calls=[call])
    )
    initial: AgentState = {
        **new_turn("Calculate, then propose a draft."),
        "todo_draft": {
            "todos": [{"project": "Old", "minutes": 10, "date": "2026-11-09"}]
        },
    }
    result = build_graph(model).invoke(initial)
    assert result["todo_draft"] is None
    assert result["tool_calls_this_turn"] == 1
    assert "remaining tool-call budget" in result["messages"][-1].text
    assert_paired(result["messages"])
    model.with_structured_output.assert_not_called()
