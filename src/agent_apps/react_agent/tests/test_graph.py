"""Offline tests for the graph mechanics: ReAct loop, HITL, loop engineering, memory.

They use a scripted model plus the REAL MCP expense server (spawned over stdio) and an
in-memory checkpointer/store. Run:  python -m pytest -q

📘 LEARN — each test scripts a "trajectory": the responder looks at the messages so far
and returns what a model would say at that point (a tool call, an answer, a verdict).
Then we assert on the final state. The `drive()` helper mirrors main.run_turn: it loops,
answering each interrupt via `resume_with`, exactly like a human at the console would.

🧪 TRY:  python -m pytest -q -k reject      (run one test)
         python -m pytest -q -s             (see prints)

离线验证图的 ReAct、人工介入、循环工程和记忆机制。
使用脚本模型、真实 stdio 记账 MCP 服务以及内存 Checkpointer/Store；
持久化恢复测试会真正关闭并重新打开 SQLite。
每个 responder 描述一条确定轨迹，drive 模拟控制台处理审批和恢复。
🧪 TRY：使用 -k reject 只运行拒绝测试，或用 -s 查看输出。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from agent_apps.react_agent.agent.config import settings, user_data_dir
from agent_apps.react_agent.agent.graph import build_graph
from agent_apps.react_agent.agent.mcp_client import load_mcp_tools
from agent_apps.react_agent.agent.state import AgentContext
from agent_apps.react_agent.agent.tools import LOCAL_TOOLS
from .fake_model import ScriptedChatModel, tool_call

CTX = AgentContext(user_id="tester")


# Fixtures and helpers
# 测试夹具与辅助函数

def set_setting(name, value):
    object.__setattr__(settings, name, value)


@pytest.fixture(autouse=True)
def default_settings(tmp_path, monkeypatch):
    saved = {k: getattr(settings, k) for k in
             ("max_iterations", "max_reflections", "enable_reflection", "context_token_budget", "keep_recent_messages",
              "data_dir", "risky_tools", "tool_timeout_seconds")}
    set_setting("enable_reflection", False)
    set_setting("data_dir", tmp_path)
    set_setting("risky_tools", frozenset({"add_expense", "update_expense", "delete_expense"}))
    yield
    for k, v in saved.items():
        set_setting(k, v)


@pytest.fixture
def mcp_tools():
    tools, report = asyncio.run(load_mcp_tools(user_id=CTX.user_id))
    assert "expenses" in report and "add_expense" in report["expenses"]
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
    """Run a turn; resume_with(payload) answers each interrupt.

    运行一轮，由 resume_with(payload) 回答每次中断。
    """
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
        if len(interrupts) > 10:
            raise AssertionError("Interrupt did not resume / 中断没有恢复")
        payload = Command(resume=resume_with(value))


def make_graph(responder, tools, store=None):
    model = ScriptedChatModel(responder=responder)
    return build_graph(model, tools, checkpointer=InMemorySaver(), store=store or InMemoryStore()), model


# Graph behavior tests
# 图行为测试

def test_react_loop_with_local_tool():
    def responder(msgs, tools_bound):
        if not turn_tool_msgs(msgs):
            return AIMessage("", tool_calls=[tool_call("calculate_share", {"part": "42", "total": "100"})])
        return AIMessage(f"The answer is {turn_tool_msgs(msgs)[-1].content}.")

    graph, _ = make_graph(responder, LOCAL_TOOLS)
    values, interrupts = asyncio.run(drive(graph, "What percentage is $42 of $100?", "t1"))
    assert interrupts == []
    assert values["messages"][-1].content == "The answer is 42.00%."
    assert values["iterations"] == 2  # reason → act, then reason → answer
    # 先决策并执行，再决策并回答。


def ledger_rows():
    path = user_data_dir(CTX.user_id) / "expenses.sqlite"
    if not path.exists():
        return []
    with sqlite3.connect(path) as db:
        return db.execute("SELECT amount_cents, note FROM expenses").fetchall()


EXPENSE = {"amount": "28.00", "spent_on": "2026-10-25", "category": "餐饮", "note": "Lunch / 午餐"}


def test_mcp_write_requires_approval_and_runs(mcp_tools):
    def responder(msgs, tools_bound):
        if not turn_tool_msgs(msgs):
            return AIMessage("", tool_calls=[tool_call("add_expense", EXPENSE)])
        return AIMessage("Recorded / 已记录。")

    graph, _ = make_graph(responder, [*LOCAL_TOOLS, *mcp_tools])
    def approve(p):
        assert ledger_rows() == []
        return {"decisions": {p["calls"][0]["id"]: {"action": "approve"}}}
    values, interrupts = asyncio.run(drive(graph, "Record lunch / 记录午餐", "t2", approve))
    assert interrupts[0]["calls"][0]["name"] == "add_expense"
    assert ledger_rows() == [(2800, "Lunch / 午餐")]
    assert values["messages"][-1].content == "Recorded / 已记录。"


def test_hitl_edit_changes_args(mcp_tools):
    def responder(msgs, tools_bound):
        if not turn_tool_msgs(msgs):
            return AIMessage("", tool_calls=[tool_call("add_expense", EXPENSE)])
        return AIMessage("ok")

    def resume(p):
        cid = p["calls"][0]["id"]
        return {"decisions": {cid: {"action": "edit", "args": {**EXPENSE, "amount": "26.50"}}}}

    graph, _ = make_graph(responder, [*LOCAL_TOOLS, *mcp_tools])
    values, _ = asyncio.run(drive(graph, "Record lunch / 记录午餐", "t3", resume))
    assert ledger_rows() == [(2650, "Lunch / 午餐")]
    ai = next(m for m in values["messages"] if isinstance(m, AIMessage) and m.tool_calls)
    assert ai.tool_calls[0]["args"]["amount"] == "26.50"


@pytest.mark.parametrize("decision", ["reject", "missing", "invalid_edit"])
def test_hitl_reject_short_circuits_tool(mcp_tools, decision):
    def responder(msgs, tools_bound):
        if not turn_tool_msgs(msgs):
            return AIMessage("", tool_calls=[tool_call("add_expense", EXPENSE)])
        return AIMessage("Not recorded / 未记账。")

    def resume(p):
        if decision == "missing":
            return {"decisions": {}}
        d = {"action": "reject", "reason": "Duplicate / 重复了"} if decision == "reject" else {"action": "edit", "args": []}
        return {"decisions": {p["calls"][0]["id"]: d}}

    graph, _ = make_graph(responder, [*LOCAL_TOOLS, *mcp_tools])
    values, _ = asyncio.run(drive(graph, "Record lunch / 记录午餐", "t4", resume))
    tm = turn_tool_msgs(values["messages"])[0]
    assert tm.status == "error" and tm.content.startswith("REJECTED by human")
    assert ledger_rows() == []


def test_ask_human_tool_interrupts_and_resumes():
    def responder(msgs, tools_bound):
        tms = turn_tool_msgs(msgs)
        if not tms:
            return AIMessage("", tool_calls=[tool_call("ask_human", {"question": "Which category? / 哪个分类？"})])
        return AIMessage(f"Got it: {tms[-1].content}")

    graph, _ = make_graph(responder, LOCAL_TOOLS)
    values, interrupts = asyncio.run(drive(graph, "Record this expense / 记录这笔支出", "t5", lambda p: "餐饮"))
    assert interrupts == [{"type": "question", "question": "Which category? / 哪个分类？"}]
    assert values["messages"][-1].content == "Got it: User answered: 餐饮"


def test_ask_human_checkpoint_resumes_in_rebuilt_graph():
    def responder(msgs, tools_bound):
        tms = turn_tool_msgs(msgs)
        if not tms:
            return AIMessage("", tool_calls=[tool_call(
                "ask_human", {"question": "Which category? / 哪个分类？"}, call_id="category-question",
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
        await graph.ainvoke({"messages": [HumanMessage("Record this expense / 记录这笔支出")]}, config, context=CTX)
        paused = await graph.aget_state(config)
        assert paused.next == ("tools",)
        assert [item.value for item in paused.interrupts] == [
            {"type": "question", "question": "Which category? / 哪个分类？"},
        ]
        assert not turn_tool_msgs(paused.values["messages"])

        # Restore the checkpoint into a new graph instance, as a resumed caller would.
        # 在新图实例中恢复检查点，模拟调用方恢复运行。
        restored = new_graph()
        await restored.ainvoke(Command(resume="餐饮"), config, context=CTX)
        finished = await restored.aget_state(config)
        assert finished.interrupts == ()
        assert finished.next == ()
        results = turn_tool_msgs(finished.values["messages"])
        assert len(results) == 1
        assert results[0].tool_call_id == "category-question"
        assert results[0].status == "success"
        assert results[0].content == "User answered: 餐饮"
        assert finished.values["messages"][-1].content == "Got it: User answered: 餐饮"

    asyncio.run(run())


def test_tool_error_remains_an_observation():
    def responder(msgs, tools_bound):
        tms = turn_tool_msgs(msgs)
        if not tms:
            return AIMessage("", tool_calls=[tool_call("calculate_share", {"part": "0", "total": "0"})])
        assert tms[-1].status == "error"
        assert "ValueError" in tms[-1].content
        return AIMessage("Cannot divide by zero.")

    graph, _ = make_graph(responder, LOCAL_TOOLS)
    values, interrupts = asyncio.run(drive(graph, "What share of zero?", "tool-error"))
    assert interrupts == []
    assert values["messages"][-1].content == "Cannot divide by zero."


def test_iteration_budget_forces_final_answer():
    set_setting("max_iterations", 3)

    def responder(msgs, tools_bound):
        if tools_bound:  # A stubborn model would keep calling tools.
            # 固执的模型会一直调用工具。
            return AIMessage("", tool_calls=[tool_call("get_current_time", {})])
        assert "Step budget exhausted" in msgs[0].content
        return AIMessage("Final answer under budget.")

    graph, model = make_graph(responder, LOCAL_TOOLS)
    values, _ = asyncio.run(drive(graph, "loop please", "t6"))
    assert values["iterations"] == 3
    assert values["messages"][-1].content == "Final answer under budget."
    assert model.calls[-1][1] is False  # The last call has no tools bound.
    # 最后一次模型调用不绑定工具。


@pytest.mark.parametrize("budget", [2, 3, 4])
def test_reflection_revisions_respect_agent_budget(budget):
    """A critic requesting endless revisions cannot exceed the per-turn agent budget.

    反思模型不断要求修改时，也不能突破每轮 Agent 步数预算。
    """
    set_setting("max_iterations", budget)
    set_setting("max_reflections", 10)
    set_setting("enable_reflection", True)

    def responder(msgs, tools_bound):
        if kind(msgs) == "critic":
            return AIMessage(json.dumps({"verdict": "revise", "feedback": "Mention USD / 补充美元单位"}))
        if not turn_tool_msgs(msgs):
            return AIMessage("", tool_calls=[tool_call("calculate_share", {"part": "25", "total": "100"})])
        return AIMessage("25.00% of the USD total / 美元总支出的 25.00%。")

    graph, model = make_graph(responder, LOCAL_TOOLS)
    values, _ = asyncio.run(drive(graph, "Share of expenses / 支出占比", f"budget-{budget}"))
    assert values["iterations"] == budget
    assert values["reflections"] == budget - 2
    finals = [m for m in values["messages"] if isinstance(m, AIMessage) and not m.tool_calls]
    assert len(finals) == 1
    assert model.calls[-1][1] is False


@pytest.mark.parametrize("tool_name,args", [
    ("add_expense", EXPENSE),
    ("update_expense", {"expense_id": "000000000000", "amount": "10.00"}),
    ("delete_expense", {"expense_id": "000000000000"}),
])
def test_example_configuration_requires_approval(mcp_tools, monkeypatch, tool_name, args):
    """Load the supplied example configuration and verify writes pause before execution.

    加载项目自带的示例配置，验证写操作在执行前确实暂停。
    """
    from dotenv import dotenv_values
    from agent_apps.react_agent.agent.config import ROOT, Settings

    example = dotenv_values(ROOT / ".env.example")
    monkeypatch.setenv("AGENT_RISKY_TOOLS", example["AGENT_RISKY_TOOLS"])
    set_setting("risky_tools", Settings().risky_tools)

    def responder(msgs, tools_bound):
        if not turn_tool_msgs(msgs):
            return AIMessage("", tool_calls=[tool_call(tool_name, args)])
        return AIMessage("Finished / 已完成。")

    graph, _ = make_graph(responder, [*LOCAL_TOOLS, *mcp_tools])

    async def run():
        config = {"configurable": {"thread_id": f"example-{tool_name}"}}
        await graph.ainvoke({"messages": [HumanMessage("Change the ledger / 修改账本")]}, config, context=CTX)
        state = await graph.aget_state(config)
        assert state.interrupts[0].value["calls"][0]["name"] == tool_name
        assert not turn_tool_msgs(state.values["messages"])
        assert ledger_rows() == []

    asyncio.run(run())


def test_loop_guard_detects_repeated_calls():
    set_setting("max_iterations", 6)
    seen_warning = []

    def responder(msgs, tools_bound):
        if "Loop guard" in msgs[0].content:
            seen_warning.append(True)
            return AIMessage("Stopping the loop.")
        return AIMessage("", tool_calls=[tool_call("calculate_share", {"part": "28", "total": "100"})])

    graph, _ = make_graph(responder, LOCAL_TOOLS)
    values, _ = asyncio.run(drive(graph, "Lunch share", "t7"))
    assert seen_warning and "calculate_share" in values["loop_warning"]
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
    assert not any(c.startswith("message 0") for c in contents)  # The oldest turn was folded into a summary.
    # 最早的轮次已压缩为摘要。
    assert contents[-2].startswith("message 2")                   # Keep the recent turn intact.
    # 保留近期轮次的完整消息。


def test_long_term_memory_across_threads():
    store = InMemoryStore()

    def responder(msgs, tools_bound):
        human = next(m for m in reversed(msgs) if isinstance(m, HumanMessage)).content
        if "remember" in human and not turn_tool_msgs(msgs):
            return AIMessage("", tool_calls=[tool_call("save_memory", {"content": "Harry prefers category summaries"})])
        if "report" in human:
            return AIMessage("You prefer category summaries." if "prefers category summaries" in msgs[0].content else "No idea.")
        return AIMessage("Noted.")

    graph, _ = make_graph(responder, LOCAL_TOOLS, store=store)

    async def run():
        await drive(graph, "please remember I prefer category summaries", "thread-a")
        return await drive(graph, "how should you report my expenses? category summaries?", "thread-b")  # A new thread.
        # 新建另一个会话。

    (values, _) = asyncio.run(run())
    assert values["memories"] and "category" in values["memories"][0]
    assert values["messages"][-1].content == "You prefer category summaries."


@pytest.mark.filterwarnings("error:Pydantic serializer warnings:UserWarning")
def test_memory_tools_preserve_context_without_serialization_warnings():
    store = InMemoryStore()

    def responder(msgs, tools_bound):
        results = turn_tool_msgs(msgs)
        assert all(result.status == "success" for result in results)
        if not results:
            call = tool_call("save_memory", {"content": "Prefers category summaries"})
        elif len(results) == 1:
            call = tool_call("search_memory", {"query": "category"})
        elif len(results) == 2:
            assert "Prefers category summaries" in results[-1].content
            assert "Another user's category preference" not in results[-1].content
            key = results[0].content.split("[", 1)[1].split("]", 1)[0]
            call = tool_call("delete_memory", {"memory_id": key})
        else:
            assert results[-1].content.startswith("Deleted memory")
            return AIMessage("Memory saved, found, and deleted.")
        return AIMessage("", tool_calls=[call])

    graph, _ = make_graph(responder, LOCAL_TOOLS, store=store)

    async def run():
        await store.aput(("memories", "other-user"), "other", {"content": "Another user's category preference"})
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
            return AIMessage(json.dumps({"verdict": "revise", "feedback": "Include the percentage and scope / 补充百分比和统计范围。"}))
        if not turn_tool_msgs(msgs):
            return AIMessage("", tool_calls=[tool_call("calculate_share", {"part": "42", "total": "100"})])
        if "Revision requested" in msgs[0].content:
            return AIMessage("Lunch is 42.00% of USD 100 / 午餐占 100 美元的 42.00%。")
        return AIMessage("42")

    graph, _ = make_graph(responder, LOCAL_TOOLS)
    values, _ = asyncio.run(drive(graph, "What share is lunch? / 午餐占比？", "t9"))
    finals = [m.content for m in values["messages"] if isinstance(m, AIMessage) and not m.tool_calls]
    assert finals == ["Lunch is 42.00% of USD 100 / 午餐占 100 美元的 42.00%。"]  # Remove and replace the old draft.
    # 删除并替换旧草稿。
    assert values["reflections"] == 1


def test_graph_shape():
    graph, _ = make_graph(lambda m, t: AIMessage("hi"), LOCAL_TOOLS)
    nodes = set(graph.get_graph().nodes)
    assert {"prepare_turn", "compact_context", "agent", "approval_gate", "tools", "loop_guard", "reflect"} <= nodes
    assert Path(settings.mcp_config).exists()


def test_console_resumes_approval_after_sqlite_reopen(mcp_tools, tmp_path, monkeypatch):
    """Resume a persisted approval once, before accepting a new message.
    接受新消息前恢复落盘的审批，且只执行一次写入。
    """
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from agent_apps.react_agent import main as console

    def responder(msgs, tools_bound):
        if not turn_tool_msgs(msgs):
            return AIMessage("", tool_calls=[tool_call("add_expense", EXPENSE)])
        return AIMessage("Recorded / 已记录。")

    prompts = []
    async def approve(payload):
        prompts.append(payload)
        return {"decisions": {payload["calls"][0]["id"]: {"action": "approve"}}}
    monkeypatch.setattr(console, "handle_interrupt", approve)
    config = {"configurable": {"thread_id": "durable-approval"}}
    store = InMemoryStore()

    def build(saver):
        return build_graph(ScriptedChatModel(responder=responder), [*LOCAL_TOOLS, *mcp_tools], checkpointer=saver, store=store)

    async def run():
        path = str(tmp_path / "checkpoints.sqlite")
        async with AsyncSqliteSaver.from_conn_string(path) as saver:
            graph = build(saver)
            await graph.ainvoke({"messages": [HumanMessage("记一笔午餐 / Record lunch")]}, config, context=CTX)
            assert (await graph.aget_state(config)).interrupts
            assert ledger_rows() == []
        async with AsyncSqliteSaver.from_conn_string(path) as saver:
            graph = build(saver)
            assert await console.resume_pending(graph, config, CTX)
            assert not await console.resume_pending(graph, config, CTX)
            assert ledger_rows() == [(2800, "Lunch / 午餐")]
            assert len(prompts) == 1

    asyncio.run(run())


def test_mixed_parallel_batch_rejects_only_write(mcp_tools):
    def responder(msgs, tools_bound):
        if not turn_tool_msgs(msgs):
            return AIMessage("", tool_calls=[
                tool_call("add_expense", EXPENSE),
                tool_call("calculate_share", {"part": "28", "total": "100"}),
            ])
        return AIMessage("28.00%; expense not saved / 未保存支出。")
    graph, _ = make_graph(responder, [*LOCAL_TOOLS, *mcp_tools])
    values, _ = asyncio.run(drive(graph, "record and calculate / 记录并计算", "mixed",
        lambda p: {"decisions": {p["calls"][0]["id"]: {"action": "reject"}}}))
    results = {m.name: m for m in turn_tool_msgs(values["messages"])}
    assert results["calculate_share"].content == "28.00%"
    assert results["add_expense"].status == "error"
    assert not values["loop_warning"] and ledger_rows() == []


def test_error_streak_warns_without_identical_calls():
    def responder(msgs, tools_bound):
        if "Loop guard" in msgs[0].content:
            return AIMessage("Stop retrying / 停止重试。")
        n = len(turn_tool_msgs(msgs))
        return AIMessage("", tool_calls=[tool_call("calculate_share", {"part": str(n), "total": "0"})])
    graph, _ = make_graph(responder, LOCAL_TOOLS)
    values, _ = asyncio.run(drive(graph, "invalid shares / 无效占比", "errors"))
    assert "last 3 tool calls failed" in values["loop_warning"]
    assert values["iterations"] == 4


def test_tool_timeout_becomes_observation():
    from langchain_core.tools import tool

    @tool
    async def slow_lookup() -> str:
        """Simulate a slow service.

        模拟响应缓慢的服务。
        """
        await asyncio.sleep(1)
        return "unused"

    set_setting("tool_timeout_seconds", 0.01)
    def responder(msgs, tools_bound):
        if not turn_tool_msgs(msgs):
            return AIMessage("", tool_calls=[tool_call("slow_lookup", {})])
        return AIMessage("Service timed out / 服务超时。")
    graph, _ = make_graph(responder, [slow_lookup])
    values, _ = asyncio.run(drive(graph, "slow query / 慢查询", "timeout"))
    result = turn_tool_msgs(values["messages"])[0]
    assert result.status == "error" and "TimeoutError" in result.content


def test_recursion_limit_is_hard_fuse():
    from langgraph.errors import GraphRecursionError
    graph, _ = make_graph(lambda msgs, bound: AIMessage("", tool_calls=[tool_call("get_current_time", {})]), LOCAL_TOOLS)
    async def run():
        await graph.ainvoke({"messages": [HumanMessage("loop / 循环")]},
                            {"configurable": {"thread_id": "fuse"}, "recursion_limit": 2}, context=CTX)
    with pytest.raises(GraphRecursionError):
        asyncio.run(run())


def test_mcp_error_returns_to_model(mcp_tools):
    """A real MCP failure becomes an observation without modifying the ledger.

    真实 MCP 错误成为模型可见的观察结果，不修改账本。
    """
    def responder(msgs, tools_bound):
        if not turn_tool_msgs(msgs):
            return AIMessage("", tool_calls=[tool_call("delete_expense", {"expense_id": "000000000000"})])
        return AIMessage("Record not found / 记录不存在。")
    graph, _ = make_graph(responder, [*LOCAL_TOOLS, *mcp_tools])
    values, _ = asyncio.run(drive(graph, "delete missing record / 删除不存在的记录", "mcp-error",
        lambda p: {"decisions": {p["calls"][0]["id"]: {"action": "approve"}}}))
    result = turn_tool_msgs(values["messages"])[0]
    assert result.status == "error" and "000000000000" in result.content
    assert ledger_rows() == []


def test_parallel_questions_recover_with_one_combined_interrupt(monkeypatch):
    """Reject ambiguous parallel interruptions, then resume one combined question.

    拒绝有歧义的并行中断，再恢复合并后的一次提问。
    """
    from agent_apps.react_agent import main as console
    questions = ["Amount? / 金额？", "Category? / 分类？"]
    combined = "Amount and category? / 金额和分类？"

    async def answer(payload):
        assert payload["question"] == combined
        return "12.50; 餐饮"
    monkeypatch.setattr(console, "handle_interrupt", answer)

    def responder(msgs, tools_bound):
        results = turn_tool_msgs(msgs)
        if not results:
            return AIMessage("", tool_calls=[
                tool_call("ask_human", {"question": question}, call_id=str(i))
                for i, question in enumerate(questions)
            ])
        if len(results) == 2:
            assert all(m.status == "error" and "Call ask_human alone" in m.content for m in results)
            return AIMessage("", tool_calls=[tool_call("ask_human", {"question": combined}, call_id="combined")])
        return AIMessage("Got both answers / 已收到两个回答。")

    graph, _ = make_graph(responder, LOCAL_TOOLS)
    config = {"configurable": {"thread_id": "parallel-questions"}}

    async def run():
        await graph.ainvoke({"messages": [HumanMessage("Ask details / 询问详情")]}, config, context=CTX)
        pending = (await graph.aget_state(config)).interrupts
        assert len(pending) == 1 and pending[0].value["question"] == combined
        assert await console.resume_pending(graph, config, CTX)
        state = await graph.aget_state(config)
        results = turn_tool_msgs(state.values["messages"])
        assert results[-1].tool_call_id == "combined"
        assert results[-1].content == "User answered: 12.50; 餐饮"
        assert not state.interrupts
    asyncio.run(run())
