"""Exercise tool-history recording and queries with isolated graphs and storage."""

import json
from datetime import datetime
from unittest.mock import Mock, patch

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.errors import GraphRecursionError

from agent_apps.todo_list_assistant_agent.agent import memory
from agent_apps.todo_list_assistant_agent.agent.graph import build_graph
from agent_apps.todo_list_assistant_agent.agent.tools import get_tool_history
from agent_apps.todo_list_assistant_agent.config import AgentConfig


@pytest.fixture(autouse=True)
def isolate_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DATABASE_FILE", tmp_path / "todos.sqlite")


def make_model(*responses):
    model = Mock(spec=BaseChatModel)

    model.bind_tools.return_value = model
    model.invoke.side_effect = responses
    return model


def calculator_request(number: int):
    return {
        "name": "calculate",
        "args": {"a": number, "b": 1, "operation": "add"},
        "id": f"calculation-{number}",
    }


@patch(
    "agent_apps.todo_list_assistant_agent.config.agent.AGENT_CONFIG",
    AgentConfig(tool_history_limit=2),
)
def test_shared_history_limit_is_used_and_persisted(tmp_path):
    model = make_model(
        AIMessage(content="", tool_calls=[calculator_request(i) for i in range(5)]),
        AIMessage(content="Done."),
    )
    config: RunnableConfig = {"configurable": {"thread_id": "custom-limit"}}
    database = str(tmp_path / "custom.sqlite")
    with SqliteSaver.from_conn_string(database) as saver:
        graph = build_graph(model, saver)
        result = graph.invoke({"messages": [HumanMessage("Calculate.")]}, config)
        assert [record["tool_args"]["a"] for record in result["tool_history"]] == [3, 4]
        assert graph.get_state(config).values["tool_history"] == result["tool_history"]
    with SqliteSaver.from_conn_string(database) as saver:
        restored = build_graph(model, saver)
        assert len(restored.get_state(config).values["tool_history"]) == 2


@patch(
    "agent_apps.todo_list_assistant_agent.config.agent.AGENT_CONFIG",
    AgentConfig(recursion_limit=3),
)
def test_graph_uses_configured_recursion_limit_with_thread_config(tmp_path):
    request = AIMessage(content="", tool_calls=[calculator_request(1)])
    model = Mock(spec=BaseChatModel)

    model.bind_tools.return_value = model
    model.invoke.return_value = request
    config: RunnableConfig = {"configurable": {"thread_id": "loop"}}
    with SqliteSaver.from_conn_string(str(tmp_path / "loop.sqlite")) as saver:
        graph = build_graph(model, saver)
        with pytest.raises(GraphRecursionError):
            graph.invoke(
                {"messages": [HumanMessage("Keep calculating.")]},
                config,
            )
        # summary -> model -> tools exhausts three steps before a second model call.
        assert model.invoke.call_count == 1
        assert len(graph.get_state(config).values["tool_history"]) == 1


def history_request(call_id: str):
    return AIMessage(
        content="",
        tool_calls=[{"name": "get_tool_history", "args": {}, "id": call_id}],
    )


def test_history_lookup_injects_runtime_and_returns_empty_history():
    schema = convert_to_openai_tool(get_tool_history)["function"]["parameters"]
    assert schema["properties"] == {}
    model = make_model(
        history_request("empty-history"), AIMessage(content="No history.")
    )
    result = build_graph(model).invoke(
        {"messages": [HumanMessage("Show tool history.")]},
    )
    output = result["messages"][-2]
    assert isinstance(output, ToolMessage)
    assert output.status == "success"
    assert json.loads(output.text) == []
    assert not result.get("tool_history")
    # The actual lookup result reaches the model so it can answer the user.
    assert model.invoke.call_args.args[0][-1].text == output.text


def test_batch_records_match_each_call_and_keep_actual_results():
    calls = [calculator_request(2), calculator_request(8)]
    model = make_model(
        AIMessage(content="", tool_calls=calls), AIMessage(content="Done.")
    )
    result = build_graph(model).invoke({"messages": [HumanMessage("Calculate both.")]})
    history = result["tool_history"]
    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(history) == 2
    for record, call, message in zip(history, calls, tool_messages, strict=True):
        assert record["tool_name"] == call["name"]
        assert record["tool_args"] == call["args"]
        assert record["result"] == message.text
        assert datetime.fromisoformat(record["timestamp"]).utcoffset() is not None
    assert [record["result"] for record in history] == ["3.0", "9.0"]


@pytest.mark.parametrize("failure", ["validation", "execution", "returned_error"])
def test_error_records_keep_the_tool_result(failure, monkeypatch):
    call = calculator_request(1)
    expected = "operation"
    if failure == "validation":
        call["args"]["operation"] = "invalid"
    elif failure == "execution":
        call = {
            "name": "save_todo",
            "args": {"project": "Clean room", "minutes": 30, "date": "2026-11-05"},
            "id": "failed-save",
        }
        monkeypatch.setattr(
            memory, "save_todo", Mock(side_effect=OSError("Disk error"))
        )
    else:
        call["args"].update(b=0, operation="divide")
        expected = "divisor must not be zero"
    model = make_model(
        AIMessage(content="", tool_calls=[call]), AIMessage(content="Cannot proceed.")
    )
    if failure == "execution":
        with pytest.raises(OSError, match="Disk error"):
            build_graph(model).invoke({"messages": [HumanMessage("Run this tool.")]})
        model.invoke.assert_called_once()
        return
    result = build_graph(model).invoke({"messages": [HumanMessage("Run this tool.")]})
    assert result["tool_history"][0]["tool_args"] == call["args"]
    assert expected in result["tool_history"][0]["result"]
    assert result["messages"][2].status == "error"
    assert result["tool_history"][0]["result"] == result["messages"][2].text
    assert memory.load_todos() == []


@patch(
    "agent_apps.todo_list_assistant_agent.config.agent.AGENT_CONFIG",
    AgentConfig(summary_trigger_tokens=100_000),
)
def test_history_appends_across_turns_and_keeps_only_latest_ten(tmp_path):
    first_batch = [calculator_request(i) for i in range(8)]
    second_batch = [calculator_request(i) for i in range(8, 13)]
    model = make_model(
        AIMessage(content="", tool_calls=first_batch),
        AIMessage(content="First batch done."),
        AIMessage(content="", tool_calls=second_batch),
        AIMessage(content="Second batch done."),
        history_request("full-history"),
        AIMessage(content="Here are the latest ten executions."),
    )
    config: RunnableConfig = {"configurable": {"thread_id": "history-limit"}}
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        graph = build_graph(model, saver)
        first = graph.invoke(
            {
                "messages": [HumanMessage("First batch.")],
                "model_calls_this_turn": 0,
                "tool_calls_this_turn": 0,
            },
            config,
        )
        assert len(first["tool_history"]) == 8
        result = graph.invoke(
            {
                "messages": [HumanMessage("Second batch.")],
                "model_calls_this_turn": 0,
                "tool_calls_this_turn": 0,
            },
            config,
        )
        assert [record["tool_args"]["a"] for record in result["tool_history"]] == list(
            range(3, 13)
        )
        assert graph.get_state(config).values["tool_history"] == result["tool_history"]
        assert len(first["tool_history"]) == 8
        queried = graph.invoke(
            {
                "messages": [HumanMessage("Show history.")],
                "model_calls_this_turn": 0,
                "tool_calls_this_turn": 0,
            },
            config,
        )
        assert json.loads(queried["messages"][-2].text) == result["tool_history"]
        # Looking up a full history does not consume one of its ten slots.
        assert queried["tool_history"] == result["tool_history"]


def test_history_survives_restart_without_repeating_completed_tools(tmp_path):
    database = str(tmp_path / "checkpoints.sqlite")
    config: RunnableConfig = {"configurable": {"thread_id": "resume"}}
    model = make_model(
        AIMessage(content="", tool_calls=[calculator_request(5)]),
        RuntimeError("Model failed after tool completion"),
    )
    with SqliteSaver.from_conn_string(database) as saver:
        graph = build_graph(model, saver)
        with pytest.raises(RuntimeError, match="after tool completion"):
            graph.invoke({"messages": [HumanMessage("Calculate.")]}, config)
        snapshot = graph.get_state(config)
        assert snapshot.next == ("model",)
        saved = snapshot.values["tool_history"]
        assert len(saved) == 1

    model = make_model(AIMessage(content="Six."), AIMessage(content="Hello."))
    with SqliteSaver.from_conn_string(database) as saver:
        graph = build_graph(model, saver)
        assert graph.get_state(config).values["tool_history"] == saved
        result = graph.invoke(None, config)
        assert result["tool_history"] == saved
        assert graph.get_state(config).next == ()
        other = graph.invoke(
            {"messages": [HumanMessage("Hello.")]},
            {"configurable": {"thread_id": "separate"}},
        )
        assert not other.get("tool_history")


@patch(
    "agent_apps.todo_list_assistant_agent.config.agent.AGENT_CONFIG",
    AgentConfig(summary_trigger_tokens=1),
)
def test_summary_compression_preserves_tool_history(tmp_path):
    model = Mock(spec=BaseChatModel)

    bound = Mock()
    model.bind_tools.return_value = bound
    model.invoke.return_value = AIMessage(content="The user requested a calculation.")
    bound.invoke.side_effect = [
        AIMessage(content="", tool_calls=[calculator_request(2)]),
        *(AIMessage(content="Understood.") for _ in range(4)),
    ]
    config: RunnableConfig = {"configurable": {"thread_id": "summary"}}
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        graph = build_graph(model, saver)
        first = graph.invoke(
            {"messages": [HumanMessage("Please calculate this value. " * 30)]},
            config,
        )
        result = first
        for number in range(3):
            result = graph.invoke(
                {"messages": [HumanMessage(f"Continue the conversation {number}.")]},
                config,
            )
        assert result["summary"] == "The user requested a calculation."
        assert not any(isinstance(m, ToolMessage) for m in result["messages"])
        assert result["tool_history"] == first["tool_history"]
        # The query reads the custom field even after original tool messages are removed.
        bound.invoke.side_effect = [
            history_request("summarized-history"),
            AIMessage(content="Here is your earlier calculation."),
        ]
        queried = graph.invoke(
            {"messages": [HumanMessage("Show tool history.")]}, config
        )
        assert json.loads(queried["messages"][-2].text) == first["tool_history"]
        assert queried["tool_history"] == first["tool_history"]


@patch(
    "agent_apps.todo_list_assistant_agent.config.agent.AGENT_CONFIG",
    AgentConfig(summary_trigger_tokens=100_000),
)
def test_history_lookup_restores_records_and_keeps_them_unchanged(tmp_path):
    database = str(tmp_path / "checkpoints.sqlite")
    config: RunnableConfig = {"configurable": {"thread_id": "saved-history"}}
    todo = {"project": "整理房间", "minutes": 30, "date": "2026-11-05"}
    model = make_model(
        AIMessage(
            content="", tool_calls=[{"name": "save_todo", "args": todo, "id": "save"}]
        ),
        AIMessage(content="Saved."),
    )
    with SqliteSaver.from_conn_string(database) as saver:
        graph = build_graph(model, saver)
        saved = graph.invoke({"messages": [HumanMessage("Save my todo.")]}, config)
        history = saved["tool_history"]
        assert len(history) == 1

    model = make_model(
        history_request("first-lookup"),
        AIMessage(content="Here is the saved execution."),
        history_request("second-lookup"),
        AIMessage(content="The records are unchanged."),
        history_request("other-lookup"),
        AIMessage(content="This conversation has no history."),
    )
    with SqliteSaver.from_conn_string(database) as saver:
        graph = build_graph(model, saver)
        for _ in range(2):
            queried = graph.invoke(
                {"messages": [HumanMessage("Show tool history.")]},
                config,
            )
            assert json.loads(queried["messages"][-2].text) == history
            assert queried["tool_history"] == history
            assert graph.get_state(config).values["tool_history"] == history
        separate = graph.invoke(
            {"messages": [HumanMessage("Show tool history.")]},
            {"configurable": {"thread_id": "another-conversation"}},
        )
        assert json.loads(separate["messages"][-2].text) == []
        assert not separate.get("tool_history")
    assert memory.load_todos() == [todo]


@patch(
    "agent_apps.todo_list_assistant_agent.config.agent.AGENT_CONFIG",
    AgentConfig(summary_trigger_tokens=100_000),
)
def test_history_lookup_uses_state_before_other_tools_in_the_same_batch(tmp_path):
    lookup = history_request("same-batch")
    model = make_model(
        AIMessage(content="", tool_calls=[calculator_request(2), *lookup.tool_calls]),
        AIMessage(content="The batch is complete."),
        history_request("next-step"),
        AIMessage(content="Now the history includes the calculation."),
    )
    config: RunnableConfig = {"configurable": {"thread_id": "batch-history"}}
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        graph = build_graph(model, saver)
        first = graph.invoke({"messages": [HumanMessage("Run both tools.")]}, config)
        lookup_result = next(
            message
            for message in first["messages"]
            if isinstance(message, ToolMessage) and message.tool_call_id == "same-batch"
        )
        assert json.loads(lookup_result.text) == []
        assert len(first["tool_history"]) == 1
        assert first["tool_history"][0]["tool_name"] == "calculate"
        queried = graph.invoke(
            {"messages": [HumanMessage("Show updated history.")]},
            config,
        )
        assert json.loads(queried["messages"][-2].text) == first["tool_history"]
        assert queried["tool_history"] == first["tool_history"]
