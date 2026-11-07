"""Exercise human approval, middleware order, and durable console recovery offline."""

import json
import subprocess
import sys
from unittest.mock import Mock

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.messages.tool import ToolCall
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.errors import GraphInterrupt
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command, Interrupt

from agent_apps.todo_list_assistant_agent import console
from agent_apps.todo_list_assistant_agent import main as app
from agent_apps.todo_list_assistant_agent.agent import checkpoints, memory, middleware
from agent_apps.todo_list_assistant_agent.agent.graph import build_graph
from agent_apps.todo_list_assistant_agent.agent.prompts import TOOL_ERROR_MESSAGE
from agent_apps.todo_list_assistant_agent.config import AgentConfig
from agent_apps.todo_list_assistant_agent.config import agent as agent_settings
from agent_apps.todo_list_assistant_agent.config import app as app_config


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DATABASE_FILE", tmp_path / "todos.sqlite")


def make_model(*responses):
    model = Mock(spec=BaseChatModel)

    model.bind_tools.return_value = model
    model.invoke.side_effect = responses
    return model


def deletion(project="Clean room", call_id="delete") -> ToolCall:
    return {
        "name": "delete_todo",
        "args": {"project": project, "date": "2026-11-06"},
        "id": call_id,
    }


def resume(paused, approved):
    return Command(resume={paused["__interrupt__"][0].id: {"approved": approved}})


@pytest.mark.parametrize("approved", [True, False])
def test_pause_then_approve_or_reject_without_premature_execution(
    approved, tmp_path, monkeypatch, capsys
):
    todo = memory.save_todo("Clean room", 30, "2026-11-06")
    delete = Mock(wraps=memory.delete_todo)
    monkeypatch.setattr(memory, "delete_todo", delete)
    model = make_model(
        AIMessage(content="", tool_calls=[deletion()]), AIMessage(content="Done.")
    )
    config: RunnableConfig = {"configurable": {"thread_id": "approval"}}
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        graph = build_graph(model, saver)
        paused = graph.invoke({"messages": [HumanMessage("Delete the todo.")]}, config)
        pending = paused["__interrupt__"][0]
        assert pending.value == {
            "kind": "tool_approval",
            "tool_name": "delete_todo",
            "tool_call_id": "delete",
            "args": deletion()["args"],
        }
        assert graph.get_state(config).interrupts[0].id == pending.id
        assert len(paused["messages"]) == 2
        assert not paused.get("tool_history")
        delete.assert_not_called()
        assert memory.load_todos() == [todo]
        assert "Tool call started" not in capsys.readouterr().out

        result = graph.invoke(resume(paused, approved), config)
        output = result["messages"][2]
        assert isinstance(output, ToolMessage)
        assert output.tool_call_id == "delete"
        assert output.status == ("success" if approved else "error")
        assert delete.call_count == int(approved)
        assert memory.load_todos() == ([] if approved else [todo])
        assert result["tool_history"][0]["result"] == output.text
        assert graph.get_state(config).next == ()
        assert not graph.get_state(config).interrupts
        assert model.invoke.call_count == 2
        if not approved:
            assert "not executed" in output.text
        logs = capsys.readouterr().out
        assert ("Tool call started" in logs) is approved


def test_approval_wraps_observation_and_executor_in_order(monkeypatch):
    order = []
    request = ToolCallRequest(tool_call=deletion(), tool=None, state={}, runtime=Mock())
    result = ToolMessage(content="Deleted.", tool_call_id="delete")

    def approve(payload):
        order.append("approval")
        return {"approved": True}

    def observe(request, execute):
        order.append("observation-before")
        output = execute(request)
        order.append("observation-after")
        return output

    def execute(request):
        order.append("execute")
        return result

    monkeypatch.setattr(middleware, "interrupt", approve)
    monkeypatch.setattr(middleware, "observe_tool_call", observe)
    assert middleware.tool_call_middleware(request, execute) is result
    assert order == ["approval", "observation-before", "execute", "observation-after"]


@pytest.mark.parametrize("decision", [True, {"approved": "yes"}, {"approved": 1}, {}])
def test_non_boolean_approval_fails_closed(decision, monkeypatch):
    request = ToolCallRequest(tool_call=deletion(), tool=None, state={}, runtime=Mock())
    execute = Mock()
    monkeypatch.setattr(middleware, "interrupt", Mock(return_value=decision))
    with pytest.raises(ValueError, match="explicit boolean"):
        middleware.tool_call_middleware(request, execute)
    execute.assert_not_called()


def test_tool_error_handler_preserves_interrupts():
    signal = GraphInterrupt(())
    with pytest.raises(GraphInterrupt) as caught:
        middleware.handle_tool_error(signal)
    assert caught.value is signal
    assert middleware.handle_tool_error(OSError("Disk failure")) == TOOL_ERROR_MESSAGE


def test_approval_can_be_explicitly_disabled_in_shared_config(monkeypatch):
    monkeypatch.setattr(agent_settings, "AGENT_CONFIG", AgentConfig(approval_tools=()))
    ask = Mock(side_effect=AssertionError("Approval is disabled"))
    monkeypatch.setattr(middleware, "interrupt", ask)
    request = ToolCallRequest(tool_call=deletion(), tool=None, state={}, runtime=Mock())
    result = ToolMessage(content="Deleted.", tool_call_id="delete")
    execute = Mock(return_value=result)
    assert middleware.tool_call_middleware(request, execute) is result
    execute.assert_called_once_with(request)
    ask.assert_not_called()


def test_multiple_approvals_reuse_completed_calls_after_restart(tmp_path, monkeypatch):
    first_todo = memory.save_todo("First", 20, "2026-11-06")
    second_todo = memory.save_todo("Second", 30, "2026-11-06")
    save = Mock(wraps=memory.save_todo)
    delete = Mock(wraps=memory.delete_todo)
    monkeypatch.setattr(memory, "save_todo", save)
    monkeypatch.setattr(memory, "delete_todo", delete)
    save_call = {
        "name": "save_todo",
        "args": {"project": "New", "minutes": 40, "date": "2026-11-06"},
        "id": "save",
    }
    calls = [save_call, deletion("First", "first"), deletion("Second", "second")]
    model = make_model(
        AIMessage(content="", tool_calls=calls), AIMessage(content="Finished.")
    )
    database = str(tmp_path / "checkpoints.sqlite")
    config: RunnableConfig = {"configurable": {"thread_id": "batch"}}
    with SqliteSaver.from_conn_string(database) as saver:
        graph = build_graph(model, saver)
        first_pause = graph.invoke(
            {"messages": [HumanMessage("Save and delete both.")]},
            config,
        )
        assert first_pause["__interrupt__"][0].value["tool_call_id"] == "first"
        assert save.call_count == 1
        delete.assert_not_called()
        second_pause = graph.invoke(resume(first_pause, True), config)
        assert second_pause["__interrupt__"][0].value["tool_call_id"] == "second"
        assert save.call_count == 1
        delete.assert_called_once_with("First", "2026-11-06")
        assert model.invoke.call_count == 1
        assert first_todo not in memory.load_todos()

    with SqliteSaver.from_conn_string(database) as saver:
        graph = build_graph(model, saver)
        pending = graph.get_state(config).interrupts[0]
        assert pending.id == second_pause["__interrupt__"][0].id
        result = graph.invoke(resume(second_pause, False), config)
        assert save.call_count == 1
        assert delete.call_count == 1
        assert second_todo in memory.load_todos()
        assert [
            m.tool_call_id for m in result["messages"] if isinstance(m, ToolMessage)
        ] == ["save", "first", "second"]
        assert len(result["tool_history"]) == 3
        assert "rejected" in result["tool_history"][-1]["result"]
        assert graph.get_state(config).next == ()


def test_approval_and_completed_task_survive_a_new_process(tmp_path):
    memory.save_todo("Clean room", 30, "2026-11-06")
    calls = [
        {
            "name": "save_todo",
            "args": {"project": "Keep", "minutes": 20, "date": "2026-11-06"},
            "id": "save",
        },
        deletion(),
    ]
    config: RunnableConfig = {"configurable": {"thread_id": "process"}}
    database = str(tmp_path / "checkpoints.sqlite")
    with SqliteSaver.from_conn_string(database) as saver:
        graph = build_graph(make_model(AIMessage(content="", tool_calls=calls)), saver)
        graph.invoke({"messages": [HumanMessage("Save and delete.")]}, config)
        assert graph.get_state(config).interrupts
    script = """
import json
import sys
from pathlib import Path
from unittest.mock import Mock
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from agent_apps.todo_list_assistant_agent.agent import memory
from agent_apps.todo_list_assistant_agent.agent.graph import build_graph
folder = Path(sys.argv[1])
memory.DATABASE_FILE = folder / "todos.sqlite"
memory.save_todo = Mock(side_effect=AssertionError("A completed save must not repeat"))
model = Mock(spec=BaseChatModel)

model.bind_tools.return_value = model
model.invoke.return_value = AIMessage(content="Done.")
config = {"configurable": {"thread_id": "process"}}
with SqliteSaver.from_conn_string(str(folder / "checkpoints.sqlite")) as saver:
    graph = build_graph(model, saver)
    pending = graph.get_state(config).interrupts[0]
    result = graph.invoke(Command(resume={pending.id: {"approved": True}}), config)
    assert len(result["tool_history"]) == 2
    assert not graph.get_state(config).next
    memory.save_todo.assert_not_called()
    print(json.dumps(memory.load_todos()))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    assert json.loads(result.stdout.splitlines()[-1]) == [
        {"project": "Keep", "minutes": 20, "date": "2026-11-06"}
    ]


def test_console_exit_then_restart_continues_approval(tmp_path, monkeypatch, capsys):
    todo = memory.save_todo("Clean room", 30, "2026-11-06")
    config: RunnableConfig = {"configurable": {"thread_id": "console"}}
    database = str(tmp_path / "checkpoints.sqlite")
    first = make_model(AIMessage(content="", tool_calls=[deletion()]))
    inputs = iter(["Delete the todo.", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    with SqliteSaver.from_conn_string(database) as saver:
        graph = build_graph(first, saver)
        console.chat(graph, "console")
        pending_id = graph.get_state(config).interrupts[0].id
        assert memory.load_todos() == [todo]
    output = capsys.readouterr().out
    assert "Approval is still pending" in output
    assert "Human approval required" in output
    assert '"project": "Clean room"' in output
    assert "Assistant: \n" not in output

    model = make_model(AIMessage(content="Deleted."))
    inputs = iter([" Y ", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    with SqliteSaver.from_conn_string(database) as saver:
        graph = build_graph(model, saver)
        assert graph.get_state(config).interrupts[0].id == pending_id
        console.chat(graph, "console")
        snapshot = graph.get_state(config)
        assert not snapshot.next
        assert (
            sum(isinstance(m, HumanMessage) for m in snapshot.values["messages"]) == 1
        )
        assert memory.load_todos() == []
    assert "Assistant: Deleted." in capsys.readouterr().out


@pytest.mark.parametrize("error", [EOFError, KeyboardInterrupt])
def test_console_terminal_exit_preserves_pending_approval(error, tmp_path, monkeypatch):
    todo = memory.save_todo("Clean room", 30, "2026-11-06")
    model = make_model(AIMessage(content="", tool_calls=[deletion()]))
    monkeypatch.setattr("builtins.input", Mock(side_effect=["Delete.", error]))
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        graph = build_graph(model, saver)
        console.chat(graph)
        assert graph.get_state({"configurable": {"thread_id": "default"}}).interrupts
        assert memory.load_todos() == [todo]


def test_console_rejects_after_invalid_choice(tmp_path, monkeypatch, capsys):
    todo = memory.save_todo("Clean room", 30, "2026-11-06")
    model = make_model(
        AIMessage(content="", tool_calls=[deletion()]),
        AIMessage(content="Not deleted."),
    )
    inputs = iter(["Delete.", "", "maybe", "NO", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        graph = build_graph(model, saver)
        console.chat(graph)
        assert memory.load_todos() == [todo]
        assert not graph.get_state({"configurable": {"thread_id": "default"}}).next
    output = capsys.readouterr().out
    assert output.count("Enter y to approve") == 2
    assert "Assistant: Not deleted." in output


def test_approval_choices_are_mapped_to_interrupt_ids(monkeypatch):
    pending = [
        Interrupt(
            value={
                "kind": "tool_approval",
                "tool_name": "delete_todo",
                "tool_call_id": "delete",
                "args": {},
            },
            id="specific-interrupt",
        )
    ]
    monkeypatch.setattr("builtins.input", lambda _: "yes")
    assert console.review_approvals(pending) == {
        "specific-interrupt": {"approved": True}
    }


def test_main_menu_reopens_saved_approval_without_new_user_turn(tmp_path, monkeypatch):
    todo = memory.save_todo("Clean room", 30, "2026-11-06")
    monkeypatch.setattr(
        checkpoints, "CHECKPOINTS_FILE", tmp_path / "checkpoints.sqlite"
    )
    monkeypatch.setattr(app_config, "ENV_FILE", tmp_path / ".env")
    app_config.ENV_FILE.write_text("GROQ_API_KEY=isolated-test-key\n", encoding="utf-8")
    first = make_model(AIMessage(content="", tool_calls=[deletion()]))
    second = make_model(AIMessage(content="Not deleted."))
    monkeypatch.setattr(app, "create_model", Mock(side_effect=[first, second]))
    inputs = iter(["0", "inbox", "Delete this todo.", "exit", "1", "n", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    app.main()
    app.main()
    with SqliteSaver.from_conn_string(str(checkpoints.CHECKPOINTS_FILE)) as saver:
        assert checkpoints.list_threads(saver) == ["inbox"]
        snapshot = build_graph(Mock(spec=BaseChatModel), saver).get_state(
            {"configurable": {"thread_id": "inbox"}}
        )
        assert not snapshot.next
        assert len(snapshot.values["tool_history"]) == 1
        assert "not executed" in snapshot.values["tool_history"][0]["result"]
    assert memory.load_todos() == [todo]


def test_console_reports_summary_once_when_turn_pauses_for_approval(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(
        agent_settings, "AGENT_CONFIG", AgentConfig(summary_trigger_tokens=1)
    )
    memory.save_todo("Clean room", 30, "2026-11-06")
    model = Mock(spec=BaseChatModel)

    bound = Mock()
    model.bind_tools.return_value = bound
    model.invoke.return_value = AIMessage(
        content="The user is organizing household tasks."
    )
    bound.invoke.side_effect = [
        *(AIMessage(content="Detailed planning advice. " * 30) for _ in range(3)),
        AIMessage(content="", tool_calls=[deletion()]),
        AIMessage(content="Deleted."),
    ]
    inputs = iter(
        [
            *("Discuss my household tasks. " * 30 for _ in range(3)),
            "Delete the todo.",
            "y",
            "exit",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        graph = build_graph(model, saver)
        console.chat(graph)
        snapshot = graph.get_state({"configurable": {"thread_id": "default"}})
        assert snapshot.values["summary"] == "The user is organizing household tasks."
        assert not snapshot.next
        assert memory.load_todos() == []
    output = capsys.readouterr().out
    notice = "Context: Earlier conversation summarized; recent turns kept."
    assert output.count(notice) == 1
    assert output.index(notice) < output.index("Human approval required")
    assert output.index("Human approval required") < output.index("Assistant: Deleted.")
