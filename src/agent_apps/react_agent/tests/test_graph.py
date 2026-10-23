"""Offline tests for the graph mechanics: ReAct loop, HITL, loop engineering, memory.

They use a scripted model plus the REAL MCP workspace server (spawned over stdio) and an
in-memory checkpointer/store. Run:  python -m pytest -q

📘 LEARN — each test scripts a "trajectory": the responder looks at the messages so far
and returns what a model would say at that point (a tool call, an answer, a verdict).
Then we assert on the final state. The `drive()` helper mirrors main.run_turn: it loops,
answering each interrupt via `resume_with`, exactly like a human at the console would.

🧪 TRY:  python -m pytest -q -k reject      (run one test)
         python -m pytest -q -s             (see prints)
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from agent_apps.react_agent.agent.config import settings
from agent_apps.react_agent.agent.graph import build_graph
from agent_apps.react_agent.agent.mcp_client import load_mcp_tools
from agent_apps.react_agent.agent.state import AgentContext
from agent_apps.react_agent.agent.tools import LOCAL_TOOLS
from .fake_model import ScriptedChatModel, tool_call

CTX = AgentContext(user_id="tester")


# ----------------------------------------------------------------------------- fixtures / helpers

def set_setting(name, value):
    object.__setattr__(settings, name, value)


@pytest.fixture(autouse=True)
def default_settings(tmp_path, monkeypatch):
    saved = {k: getattr(settings, k) for k in
             ("max_iterations", "enable_reflection", "context_token_budget", "keep_recent_messages")}
    set_setting("enable_reflection", False)
    yield
    for k, v in saved.items():
        set_setting(k, v)


@pytest.fixture(scope="session")
def mcp_tools():
    tools, report = asyncio.run(load_mcp_tools())
    assert "workspace" in report and "write_file" in report["workspace"]
    return tools


def kind(messages) -> str:
    first = messages[0]
    if isinstance(first, SystemMessage):
        return "agent"
    text = str(first.content)
    if text.startswith("Compress the conversation"):
        return "summarize"
    if text.startswith("You are a strict reviewer"):
        return "critic"
    return "other"


def turn_tool_msgs(messages):
    out = []
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            break
        if isinstance(m, ToolMessage):
            out.append(m)
    return list(reversed(out))


async def drive(graph, text, thread, resume_with=None):
    """Run a turn; `resume_with(payload)` answers each interrupt."""
    config = {"configurable": {"thread_id": thread}, "recursion_limit": 60}
    payload = {"messages": [HumanMessage(text)]}
    interrupts = []
    while True:
        await graph.ainvoke(payload, config, context=CTX)
        snap = await graph.aget_state(config)
        if not snap.interrupts:
            return snap.values, interrupts
        value = snap.interrupts[0].value
        interrupts.append(value)
        payload = Command(resume=resume_with(value))


def make_graph(responder, tools, store=None):
    model = ScriptedChatModel(responder=responder)
    return build_graph(model, tools, checkpointer=InMemorySaver(), store=store or InMemoryStore()), model


# ----------------------------------------------------------------------------- tests

def test_react_loop_with_local_tool():
    def responder(msgs, tools_bound):
        if not turn_tool_msgs(msgs):
            return AIMessage("", tool_calls=[tool_call("calculator", {"expression": "(3+4)*6"})])
        return AIMessage(f"The answer is {turn_tool_msgs(msgs)[-1].content}.")

    graph, _ = make_graph(responder, LOCAL_TOOLS)
    values, interrupts = asyncio.run(drive(graph, "what is (3+4)*6", "t1"))
    assert interrupts == []
    assert values["messages"][-1].content == "The answer is 42."
    assert values["iterations"] == 2  # reason→act, then reason→answer


def test_mcp_write_requires_approval_and_runs(mcp_tools):
    fname = f"note-{uuid.uuid4().hex[:6]}.md"

    def responder(msgs, tools_bound):
        if not turn_tool_msgs(msgs):
            return AIMessage("", tool_calls=[tool_call("write_file", {"path": fname, "content": "hello"})])
        return AIMessage("Done.")

    graph, _ = make_graph(responder, [*LOCAL_TOOLS, *mcp_tools])
    values, interrupts = asyncio.run(drive(
        graph, "write a note", "t2", lambda p: {"decisions": {p["calls"][0]["id"]: {"action": "approve"}}}))
    path = settings.workspace_dir / fname
    try:
        assert interrupts[0]["type"] == "approval"
        assert interrupts[0]["calls"][0]["name"] == "write_file"
        assert path.read_text() == "hello"
        assert values["messages"][-1].content == "Done."
    finally:
        path.unlink(missing_ok=True)


def test_hitl_edit_changes_args(mcp_tools):
    fname = f"edit-{uuid.uuid4().hex[:6]}.md"

    def responder(msgs, tools_bound):
        if not turn_tool_msgs(msgs):
            return AIMessage("", tool_calls=[tool_call("write_file", {"path": fname, "content": "draft"})])
        return AIMessage("ok")

    def resume(p):
        cid = p["calls"][0]["id"]
        return {"decisions": {cid: {"action": "edit", "args": {"path": fname, "content": "edited by human"}}}}

    graph, _ = make_graph(responder, [*LOCAL_TOOLS, *mcp_tools])
    values, _ = asyncio.run(drive(graph, "write", "t3", resume))
    path = settings.workspace_dir / fname
    try:
        assert path.read_text() == "edited by human"
        ai_with_call = next(m for m in values["messages"] if isinstance(m, AIMessage) and m.tool_calls)
        assert ai_with_call.tool_calls[0]["args"]["content"] == "edited by human"  # history rewritten
    finally:
        path.unlink(missing_ok=True)


def test_hitl_reject_short_circuits_tool():
    marker = settings.workspace_dir / f"should-not-exist-{uuid.uuid4().hex[:6]}"

    def responder(msgs, tools_bound):
        if not turn_tool_msgs(msgs):
            return AIMessage("", tool_calls=[tool_call("run_shell", {"command": f"touch {marker.name}"})])
        return AIMessage("Understood, I did not run it.")

    graph, _ = make_graph(responder, LOCAL_TOOLS)
    values, _ = asyncio.run(drive(graph, "touch a file", "t4",
                                  lambda p: {"decisions": {p["calls"][0]["id"]: {"action": "reject", "reason": "no"}}}))
    tm = turn_tool_msgs(values["messages"])[0]
    assert tm.status == "error" and tm.content.startswith("REJECTED by human")
    assert not marker.exists()


def test_ask_human_tool_interrupts_and_resumes():
    def responder(msgs, tools_bound):
        tms = turn_tool_msgs(msgs)
        if not tms:
            return AIMessage("", tool_calls=[tool_call("ask_human", {"question": "Which city?"})])
        return AIMessage(f"Got it: {tms[-1].content}")

    graph, _ = make_graph(responder, LOCAL_TOOLS)
    values, interrupts = asyncio.run(drive(graph, "weather?", "t5", lambda p: "San Jose"))
    assert interrupts == [{"type": "question", "question": "Which city?"}]
    assert values["messages"][-1].content == "Got it: User answered: San Jose"


def test_ask_human_checkpoint_resumes_in_rebuilt_graph():
    def responder(msgs, tools_bound):
        tms = turn_tool_msgs(msgs)
        if not tms:
            return AIMessage("", tool_calls=[tool_call(
                "ask_human", {"question": "Which city?"}, call_id="city-question",
            )])
        return AIMessage(f"Got it: {tms[-1].content}")

    saver = InMemorySaver()
    store = InMemoryStore()
    config = {"configurable": {"thread_id": "resume-question"}}

    def new_graph():
        return build_graph(ScriptedChatModel(responder=responder), LOCAL_TOOLS,
                           checkpointer=saver, store=store)

    async def run():
        graph = new_graph()
        await graph.ainvoke({"messages": [HumanMessage("weather?")]}, config, context=CTX)
        paused = await graph.aget_state(config)
        assert paused.next == ("tools",)
        assert [item.value for item in paused.interrupts] == [
            {"type": "question", "question": "Which city?"},
        ]
        assert not turn_tool_msgs(paused.values["messages"])

        # Restore the checkpoint into a new graph instance, as a resumed caller would.
        restored = new_graph()
        await restored.ainvoke(Command(resume="San Jose"), config, context=CTX)
        finished = await restored.aget_state(config)
        assert finished.interrupts == ()
        assert finished.next == ()
        results = turn_tool_msgs(finished.values["messages"])
        assert len(results) == 1
        assert results[0].tool_call_id == "city-question"
        assert results[0].status == "success"
        assert results[0].content == "User answered: San Jose"
        assert finished.values["messages"][-1].content == "Got it: User answered: San Jose"

    asyncio.run(run())


def test_tool_error_remains_an_observation():
    def responder(msgs, tools_bound):
        tms = turn_tool_msgs(msgs)
        if not tms:
            return AIMessage("", tool_calls=[tool_call("calculator", {"expression": "1/0"})])
        assert tms[-1].status == "error"
        assert "ZeroDivisionError" in tms[-1].content
        return AIMessage("Cannot divide by zero.")

    graph, _ = make_graph(responder, LOCAL_TOOLS)
    values, interrupts = asyncio.run(drive(graph, "calculate 1/0", "tool-error"))
    assert interrupts == []
    assert values["messages"][-1].content == "Cannot divide by zero."


def test_iteration_budget_forces_final_answer():
    set_setting("max_iterations", 3)

    def responder(msgs, tools_bound):
        if tools_bound:  # a stubborn model that would loop forever
            return AIMessage("", tool_calls=[tool_call("get_current_time", {})])
        assert "Step budget exhausted" in msgs[0].content
        return AIMessage("Final answer under budget.")

    graph, model = make_graph(responder, LOCAL_TOOLS)
    values, _ = asyncio.run(drive(graph, "loop please", "t6"))
    assert values["iterations"] == 3
    assert values["messages"][-1].content == "Final answer under budget."
    assert model.calls[-1][1] is False  # last call had no tools bound


def test_loop_guard_detects_repeated_calls():
    set_setting("max_iterations", 6)
    seen_warning = []

    def responder(msgs, tools_bound):
        if "Loop guard" in msgs[0].content:
            seen_warning.append(True)
            return AIMessage("Stopping the loop.")
        return AIMessage("", tool_calls=[tool_call("calculator", {"expression": "1+1"})])

    graph, _ = make_graph(responder, LOCAL_TOOLS)
    values, _ = asyncio.run(drive(graph, "1+1", "t7"))
    assert seen_warning and "calculator" in values["loop_warning"]
    assert values["messages"][-1].content == "Stopping the loop."


def test_context_compaction_summarises_old_turns():
    set_setting("context_token_budget", 50)
    set_setting("keep_recent_messages", 2)

    def responder(msgs, tools_bound):
        if kind(msgs) == "summarize":
            return AIMessage("SUMMARY: user said several long things.")
        return AIMessage("ack " + "x" * 200)

    graph, _ = make_graph(responder, LOCAL_TOOLS)

    async def run():
        for i in range(3):
            await drive(graph, f"message {i} " + "y" * 200, "t8")
        return (await graph.aget_state({"configurable": {"thread_id": "t8"}})).values

    values = asyncio.run(run())
    assert values["summary"].startswith("SUMMARY")
    contents = [m.content for m in values["messages"]]
    assert not any(c.startswith("message 0") for c in contents)  # oldest turn folded away
    assert contents[-2].startswith("message 2")                   # recent turn kept intact


def test_long_term_memory_across_threads():
    store = InMemoryStore()

    def responder(msgs, tools_bound):
        human = next(m for m in reversed(msgs) if isinstance(m, HumanMessage)).content
        if "remember" in human and not turn_tool_msgs(msgs):
            return AIMessage("", tool_calls=[tool_call("save_memory", {"content": "Harry prefers tea over coffee"})])
        if "drink" in human:
            return AIMessage("You prefer tea." if "prefers tea" in msgs[0].content else "No idea.")
        return AIMessage("Noted.")

    graph, _ = make_graph(responder, LOCAL_TOOLS, store=store)

    async def run():
        await drive(graph, "please remember I prefer tea", "thread-a")
        return await drive(graph, "what should I drink? tea or coffee", "thread-b")  # new thread

    (values, _) = asyncio.run(run())
    assert values["memories"] and "tea" in values["memories"][0]
    assert values["messages"][-1].content == "You prefer tea."


@pytest.mark.filterwarnings("error:Pydantic serializer warnings:UserWarning")
def test_memory_tools_preserve_context_without_serialization_warnings():
    store = InMemoryStore()

    def responder(msgs, tools_bound):
        results = turn_tool_msgs(msgs)
        assert all(result.status == "success" for result in results)
        if not results:
            call = tool_call("save_memory", {"content": "Prefers tea"})
        elif len(results) == 1:
            call = tool_call("search_memory", {"query": "tea"})
        elif len(results) == 2:
            assert "Prefers tea" in results[-1].content
            assert "Another user's tea" not in results[-1].content
            key = results[0].content.split("[", 1)[1].split("]", 1)[0]
            call = tool_call("delete_memory", {"memory_id": key})
        else:
            assert results[-1].content.startswith("Deleted memory")
            return AIMessage("Memory saved, found, and deleted.")
        return AIMessage("", tool_calls=[call])

    graph, _ = make_graph(responder, LOCAL_TOOLS, store=store)

    async def run():
        await store.aput(("memories", "other-user"), "other", {"content": "Another user's tea"})
        values, interrupts = await drive(graph, "exercise memory tools", "memory-tools")
        assert interrupts == []
        assert values["messages"][-1].content == "Memory saved, found, and deleted."
        assert await store.asearch(("memories", CTX.user_id)) == []
        assert await store.aget(("memories", "other-user"), "other") is not None

    asyncio.run(run())


def test_reflection_revises_draft_once():
    set_setting("enable_reflection", True)

    def responder(msgs, tools_bound):
        k = kind(msgs)
        if k == "critic":
            return AIMessage(json.dumps({"verdict": "revise", "feedback": "Show the arithmetic."}))
        if not turn_tool_msgs(msgs):
            return AIMessage("", tool_calls=[tool_call("calculator", {"expression": "2*21"})])
        if "Revision requested" in msgs[0].content:
            return AIMessage("2*21 = 42")
        return AIMessage("42")

    graph, _ = make_graph(responder, LOCAL_TOOLS)
    values, _ = asyncio.run(drive(graph, "2*21?", "t9"))
    finals = [m.content for m in values["messages"] if isinstance(m, AIMessage) and not m.tool_calls]
    assert finals == ["2*21 = 42"]  # the draft "42" was removed and replaced
    assert values["reflections"] == 1


def test_graph_shape():
    graph, _ = make_graph(lambda m, t: AIMessage("hi"), LOCAL_TOOLS)
    nodes = set(graph.get_graph().nodes)
    assert {"prepare_turn", "compact_context", "agent", "approval_gate", "tools", "loop_guard", "reflect"} <= nodes
    assert Path(settings.mcp_config).exists()
