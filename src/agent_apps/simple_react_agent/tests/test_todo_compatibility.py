"""Exercise todo copy and legacy record/checkpoint compatibility offline."""

import json
from unittest.mock import Mock

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from agent_apps.simple_react_agent import memory
from agent_apps.simple_react_agent.config import SummaryConfig
from agent_apps.simple_react_agent.graph import build_graph
from agent_apps.simple_react_agent.state import AgentState
from agent_apps.simple_react_agent.tools import (
    TOOLS,
    delete_study_plan,
    save_study_plan,
)


@pytest.fixture(autouse=True)
def isolate_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DATABASE_FILE", tmp_path / "study_plans.sqlite")


def make_model():
    model = Mock(spec=BaseChatModel)
    model.bind_tools.return_value = model
    model.invoke.side_effect = lambda _: AIMessage(content="Here are your todos.")
    return model


def test_todo_prompt_reads_legacy_record_without_changing_it():
    existing = memory.save_plan("Python", 60, "2026-10-29")
    model = make_model()
    result = build_graph(model).invoke({"messages": [HumanMessage("List my todos.")]})
    system = model.invoke.call_args.args[0][0].content
    assert "You are Todo List Assistant" in system
    assert "# Current todo list" in system
    assert json.dumps([existing], ensure_ascii=False, indent=2) in system
    assert memory.load_plans() == [existing]
    assert len(result["messages"]) == 2


def test_todo_crud_keeps_legacy_tool_names_and_record_fields():
    existing = memory.save_plan("Python", 60, "2026-10-29")
    arguments = {"project": "Clean room", "minutes": 30, "date": "2026-11-04"}
    assert save_study_plan.name == "save_study_plan"
    assert delete_study_plan.name == "delete_study_plan"
    assert set(save_study_plan.args) == {
        "project",
        "minutes",
        "date",
    }
    assert "Saved todo: Clean room, estimated 30 minutes" in save_study_plan.invoke(
        arguments
    )
    assert memory.load_plans() == [existing, arguments]
    assert "estimated 45 minutes" in save_study_plan.invoke(
        {**arguments, "minutes": 45}
    )
    assert memory.load_plans() == [existing, {**arguments, "minutes": 45}]
    assert "Deleted todo" in delete_study_plan.invoke(
        {"project": "Clean room", "date": "2026-11-04"}
    )
    assert memory.load_plans() == [existing]
    assert "No todos were deleted" in delete_study_plan.invoke(
        {"project": "Clean room", "date": "2026-11-04"}
    )
    assert memory.load_plans() == [existing]


def test_old_messages_summary_and_pending_tool_call_survive_new_theme(
    tmp_path, monkeypatch
):
    existing = memory.save_plan("Python", 60, "2026-10-29")
    old_messages = [
        HumanMessage(content="Save my Python study plan.", id="old-user"),
        AIMessage(
            content="",
            id="old-request",
            tool_calls=[
                {
                    "name": "save_study_plan",
                    "args": existing,
                    "id": "old-save",
                }
            ],
        ),
        ToolMessage(
            content="Saved study plan: Python, 60 minutes, 2026-10-29.",
            tool_call_id="old-save",
            id="old-result",
        ),
        AIMessage(content="Your study plan was saved.", id="old-answer"),
        HumanMessage(
            content="Save a Clean room task for tomorrow, 30 minutes.",
            id="pending-user",
        ),
    ]
    summary = "The user previously discussed a Python study plan and decorators."
    config: RunnableConfig = {"configurable": {"thread_id": "legacy-conversation"}}
    database = str(tmp_path / "checkpoints.sqlite")
    pending_args = {"project": "Clean room", "minutes": 30, "date": "2026-11-04"}

    def old_model(state: AgentState):
        return {
            "messages": [
                AIMessage(
                    content="",
                    id="pending-request",
                    tool_calls=[
                        {
                            "name": "save_study_plan",
                            "args": pending_args,
                            "id": "pending-save",
                        }
                    ],
                )
            ]
        }

    with SqliteSaver.from_conn_string(database) as saver:
        old = StateGraph(AgentState)
        old.add_node("model", old_model)
        old.add_node("tools", ToolNode(TOOLS))
        old.add_edge(START, "model")
        old.add_edge("model", "tools")
        old.add_edge("tools", END)
        old_graph = old.compile(checkpointer=saver, interrupt_before=["tools"])
        old_graph.invoke({"messages": old_messages, "summary": summary}, config=config)
        before = old_graph.get_state(config)
        assert before.next == ("tools",)
        old_dump = [m.model_dump() for m in before.values["messages"]]

    save = Mock(wraps=memory.save_plan)
    monkeypatch.setattr(memory, "save_plan", save)
    model = make_model()
    with SqliteSaver.from_conn_string(database) as saver:
        graph = build_graph(model, saver, SummaryConfig(trigger_tokens=100_000))
        # Merely opening/building the new graph does not rewrite historical state.
        reopened = graph.get_state(config)
        assert reopened.next == ("tools",)
        assert reopened.values["summary"] == summary
        assert [m.model_dump() for m in reopened.values["messages"]] == old_dump
        assert memory.load_plans() == [existing]

        result = graph.invoke(None, config=config)
        assert graph.get_state(config).next == ()
        assert result["summary"] == summary
        assert [m.model_dump() for m in result["messages"][: len(old_dump)]] == old_dump
        assert "Saved todo: Clean room" in result["messages"][-2].content
    save.assert_called_once_with("Clean room", 30, "2026-11-04")
    assert memory.load_plans() == [existing, pending_args]
    request = model.invoke.call_args.args[0]
    assert "Todo List Assistant" in request[0].content
    assert summary in request[0].content
