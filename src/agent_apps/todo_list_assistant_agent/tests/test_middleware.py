"""Verify tool observation preserves execution, errors, and checkpointed history."""

import json
from unittest.mock import Mock

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from agent_apps.todo_list_assistant_agent.agent import memory, middleware
from agent_apps.todo_list_assistant_agent.agent.graph import build_graph
from agent_apps.todo_list_assistant_agent.agent.prompts import TOOL_ERROR_MESSAGE


@pytest.mark.parametrize(
    ("result", "status"),
    [
        (ToolMessage(content="Done.", tool_call_id="observed"), "success"),
        (
            ToolMessage(content="Failed.", tool_call_id="observed", status="error"),
            "error",
        ),
        (Command(update={"summary": "Unchanged by the wrapper."}), "command"),
    ],
)
def test_observer_passes_request_and_result_through_once(
    result, status, monkeypatch, capsys
):
    request = ToolCallRequest(
        tool_call={"name": "example", "args": {}, "id": "observed"},
        tool=None,
        state={"summary": "Original."},
        runtime=Mock(),
    )
    execute = Mock(return_value=result)
    monkeypatch.setattr(middleware, "perf_counter", Mock(side_effect=[10, 10.125]))

    assert middleware.observe_tool_call(request, execute) is result

    execute.assert_called_once_with(request)
    assert request.state == {"summary": "Original."}
    output = capsys.readouterr().out
    assert "Tool call started: name=example, id=observed" in output
    assert f"status={status}, elapsed=0.125s" in output


def test_observer_reports_exception_and_preserves_it(monkeypatch, capsys):
    request = ToolCallRequest(
        tool_call={"name": "example", "args": {}, "id": "failed"},
        tool=None,
        state={},
        runtime=Mock(),
    )
    error = RuntimeError("Execution failed.")
    execute = Mock(side_effect=error)
    monkeypatch.setattr(middleware, "perf_counter", Mock(side_effect=[10, 10.25]))

    with pytest.raises(RuntimeError) as caught:
        middleware.observe_tool_call(request, execute)

    assert caught.value is error
    execute.assert_called_once_with(request)
    assert "status=exception, elapsed=0.250s" in capsys.readouterr().out


def test_graph_observes_each_call_and_preserves_history(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(memory, "DATABASE_FILE", tmp_path / "todos.sqlite")
    calls = [
        {
            "name": "calculate",
            "args": {"a": 2, "b": 1, "operation": "add"},
            "id": "normal",
        },
        {
            "name": "calculate",
            "args": {"a": 2, "b": 1, "operation": "invalid"},
            "id": "invalid",
        },
        {
            "name": "calculate",
            "args": {"a": 2, "b": 0, "operation": "divide"},
            "id": "business-error",
        },
    ]
    model = Mock(spec=BaseChatModel)

    model.bind_tools.return_value = model
    model.invoke.side_effect = [
        AIMessage(content="", tool_calls=calls),
        AIMessage(
            content="",
            tool_calls=[{"name": "get_tool_history", "args": {}, "id": "lookup"}],
        ),
        AIMessage(content="Done."),
    ]
    config: RunnableConfig = {"configurable": {"thread_id": "observed"}}
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        graph = build_graph(model, saver)
        result = graph.invoke(
            {"messages": [HumanMessage("Calculate and show history.")]},
            config,
        )
        history = result["tool_history"]
        assert len(history) == 3
        assert history[0]["result"] == "3.0"
        assert history[1]["result"] == TOOL_ERROR_MESSAGE
        assert "divisor must not be zero" in history[2]["result"]
        assert all(
            set(record) == {"tool_name", "tool_args", "result", "timestamp"}
            for record in history
        )
        assert json.loads(result["messages"][-2].text) == history
        assert graph.get_state(config).values["tool_history"] == history
        assert set(graph.get_graph().nodes) == {
            "__start__",
            "summarize",
            "model",
            "tools",
            "draft",
            "__end__",
        }

    output = capsys.readouterr().out
    for call_id, status in (
        ("normal", "success"),
        ("invalid", "error"),
        ("business-error", "success"),
        ("lookup", "success"),
    ):
        assert output.count(f"id={call_id}, status={status}, elapsed=") == 1
