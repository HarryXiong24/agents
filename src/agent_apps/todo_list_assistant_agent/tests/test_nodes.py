"""Verify fixed node dependencies, conversation isolation, and task serialization."""

import json
from unittest.mock import Mock

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.prebuilt import ToolNode

from agent_apps.todo_list_assistant_agent.agent import graph as graph_module
from agent_apps.todo_list_assistant_agent.agent import memory
from agent_apps.todo_list_assistant_agent.agent.graph import build_graph
from agent_apps.todo_list_assistant_agent.agent.tools import TOOLS


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DATABASE_FILE", tmp_path / "todos.sqlite")


def make_model(*responses):
    model = Mock(spec=BaseChatModel)

    model.bind_tools.return_value = model
    model.invoke.side_effect = responses
    return model


def test_build_prepares_fixed_dependencies_once_without_model_requests():
    model = make_model()
    build_graph(model)
    model.bind_tools.assert_called_once_with(TOOLS)
    model.with_structured_output.assert_not_called()
    model.invoke.assert_not_called()


def test_shared_node_objects_keep_conversations_isolated(tmp_path):
    model = make_model(
        AIMessage("First conversation."),
        AIMessage("Second conversation."),
        AIMessage("Continuing the first."),
    )
    first: RunnableConfig = {"configurable": {"thread_id": "first"}}
    second: RunnableConfig = {"configurable": {"thread_id": "second"}}
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        graph = build_graph(model, saver)
        graph.invoke({"messages": [HumanMessage("First input.")]}, first)
        graph.invoke({"messages": [HumanMessage("Second input.")]}, second)
        result = graph.invoke({"messages": [HumanMessage("Continue.")]}, first)
        assert result["messages"][-1].text == "Continuing the first."
        inputs = model.invoke.call_args_list
        assert "First input." not in [m.text for m in inputs[1].args[0]]
        assert "First input." in [m.text for m in inputs[2].args[0]]
        assert "Second input." not in [m.text for m in inputs[2].args[0]]
        assert len(graph.get_state(first).values["messages"]) == 4
        assert len(graph.get_state(second).values["messages"]) == 2
    model.bind_tools.assert_called_once()
    model.with_structured_output.assert_not_called()


def test_tool_runtime_and_checkpoints_do_not_contain_node_dependencies(
    tmp_path, monkeypatch
):
    model = make_model(
        AIMessage(
            "",
            tool_calls=[
                {
                    "name": "calculate",
                    "args": {"a": 2, "b": 3, "operation": "add"},
                    "id": "calculate",
                }
            ],
        ),
        AIMessage(
            "", tool_calls=[{"name": "get_tool_history", "args": {}, "id": "history"}]
        ),
        AIMessage("Done."),
    )
    contexts = []

    def create_executor(tools, **kwargs):
        middleware = kwargs.pop("wrap_tool_call")

        def inspect(request, execute):
            contexts.append(request.runtime.context)
            return middleware(request, execute)

        return ToolNode(tools, wrap_tool_call=inspect, **kwargs)

    monkeypatch.setattr(graph_module, "ToolNode", create_executor)
    config: RunnableConfig = {"configurable": {"thread_id": "dependencies"}}
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        graph = build_graph(model, saver)
        result = graph.invoke(
            {"messages": [HumanMessage("Calculate and show history.")]}, config
        )
        assert contexts == [None, None]
        assert set(graph.get_state(config).values) <= {
            "messages",
            "summary",
            "tool_history",
        }
        lookup = next(
            message
            for message in result["messages"]
            if isinstance(message, ToolMessage) and message.tool_call_id == "history"
        )
        assert lookup.status == "success"
        assert json.loads(lookup.text) == result["tool_history"]
        saved = saver.get_tuple(config)
        assert saved is not None
        for name in ("ModelNode", "ToolsNode", "SummarizeNode", "DraftNode"):
            assert name not in repr(saved.checkpoint)
