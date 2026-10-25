"""A hand-wired ReAct graph with explicit engineering seams.
START → prepare_turn → compact_context → agent → tools → loop_guard → compact_context.
Risky calls visit approval_gate before tools; tool-based final answers visit reflect.
📘 LEARN: nodes return partial state updates; reducers merge them. Conditional edges
choose the next node. A super-step is a round of execution, checkpointed by LangGraph.
The hand-built graph makes approval, compaction, budgets and reflection inspectable.

显式编排的 ReAct 图，把工程机制拆成可观察的节点。
START → prepare_turn → compact_context → agent → tools → loop_guard → compact_context。
有副作用的调用先经过 approval_gate；使用过工具的最终回答进入 reflect。
📘 LEARN：节点返回局部状态更新，由 reducer 合并；条件边选择下一个节点。
super-step 是一轮执行，LangGraph 会保存检查点。手写图便于观察审批、压缩、预算和反思。
"""

from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.messages.utils import count_tokens_approximately
from langchain_core.tools import BaseTool
from langgraph.errors import GraphBubbleUp
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt

from . import memory
from .config import settings
from .prompts import CRITIC_PROMPT, SUMMARIZE_PROMPT, build_system_prompt
from .state import AgentContext, AgentState


REJECT_PREFIX = "REJECTED by human"


def _current_turn(messages: list[AnyMessage]) -> list[AnyMessage]:
    """Return messages since the latest HumanMessage.
    Loop detection, reflection and tool-use checks are scoped to this turn, not all history.

    返回最后一条 HumanMessage 开始的消息。
    循环检测、反思和是否使用工具的判断只检查当前轮，避免把历史调用算进来。
    """
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            return messages[i:]
    return list(messages)


def _text(msg: AnyMessage) -> str:
    """Normalize a message’s string or content-block list to plain text.
    MCP commonly returns blocks; never assume content is already a string.

    将字符串或内容块列表统一为纯文本。
    MCP 常返回内容块，不能假设 content 一定是字符串。
    """
    c = msg.content
    if isinstance(c, list):
        c = "\n".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in c)
    return str(c)


def _render(messages: list[AnyMessage], limit: int = 600) -> str:
    """Render a bounded transcript for secondary summary/critic calls.
    Long fields are clipped, so this log is not a full-fidelity database audit.

    为摘要和反思模型生成有长度上限的记录。
    长字段会被截断，因此该日志不是完整的数据库审计记录。
    """
    lines = []
    for m in messages:
        if isinstance(m, HumanMessage):
            lines.append(f"USER: {_text(m)[:limit]}")
        elif isinstance(m, AIMessage):
            if _text(m):
                lines.append(f"ASSISTANT: {_text(m)[:limit]}")
            for tc in m.tool_calls:
                lines.append(f"TOOL CALL: {tc['name']}({json.dumps(tc['args'], ensure_ascii=False)[:200]})")
        elif isinstance(m, ToolMessage):
            lines.append(f"TOOL RESULT [{m.name}]: {_text(m)[:limit]}")
    return "\n".join(lines)


def _parse_json(text: str) -> dict:
    """Extract JSON from model prose/code fences; malformed JSON returns an empty result.
    The critic fails open on parse errors: a quality check, never an authorization check.

    从模型说明文字或代码块中提取 JSON；格式错误时返回空结果。
    反思解析失败时放行：它是质量检查，不能充当授权检查。
    """
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}


MAX_TOOL_OUTPUT = 4000


def _handle_tool_error(error: Exception) -> str:
    """Turn recoverable tool failures into observations while propagating GraphBubbleUp.
    ⚠ PITFALL: swallowing GraphInterrupt would break checkpointed ask_human/resume.

    将可恢复的工具错误转为观察结果，同时继续抛出 GraphBubbleUp。
    ⚠ PITFALL：吞掉 GraphInterrupt 会破坏 ask_human 的暂停和恢复。
    """
    if isinstance(error, GraphBubbleUp):
        raise error
    return f"Error: {error!r}\n Please fix your mistakes."


def _normalize_tool_result(result):
    """Flatten MCP blocks and cap output at one common interception point.
    Use pagination/aggregation at the source; truncation is only a final guard.

    在统一拦截点将 MCP 内容块转为文本并限制输出长度。
    应优先在数据源分页或汇总，截断只是最后一道保护。
    """
    if isinstance(result, ToolMessage):
        text = _text(result)
        if len(text) > MAX_TOOL_OUTPUT:
            text = text[:MAX_TOOL_OUTPUT] + f"\n... [truncated {len(text) - MAX_TOOL_OUTPUT} chars]"
        if text != result.content:
            result = result.model_copy(update={"content": text})
    return result


def build_graph(
    model: BaseChatModel,
    tools: list[BaseTool],
    *,
    checkpointer=None,
    store=None,
    critic_model: BaseChatModel | None = None,
):
    """Inject the model, tools, checkpointer, Store and optional critic model.
    📘 LEARN: closures capture these dependencies. Tests replace them with scripted models
    and in-memory storage while exercising the same production graph.

    注入模型、工具、Checkpointer、Store 和可选的反思模型。
    📘 LEARN：内部函数通过闭包访问这些依赖。测试替换为脚本模型和内存存储，
    但执行的仍是同一张实际运行的图。
    """
    critic_model = critic_model or model

    # 📘 LEARN: bind_tools adds function schemas to each request; AIMessage carries structured calls.
    # 📘 LEARN：bind_tools 把函数 schema 加入每次请求，AIMessage 携带结构化工具调用。
    model_with_tools = model.bind_tools(tools)

    async def prepare_turn(state: AgentState, runtime: Runtime[AgentContext]):
        """Reset per-turn budgets/decisions and recall user memories via injected Runtime.
        Recall enters the system prompt, not the message history. Context must be passed on resume.

        通过注入的 Runtime 召回用户记忆，重置本轮预算与审批决策。
        召回结果进入系统提示词，不加入消息历史；恢复时仍需传入 Context。
        """
        turn = _current_turn(state["messages"])
        query = _text(turn[0]) if turn else ""

        memories = await memory.recall(runtime.store, runtime.context.user_id, query)
        return {
            "iterations": 0,
            "reflections": 0,
            "loop_warning": "",
            "critique": None,
            "hitl_decisions": {},
            "memories": memories,
        }

    async def compact_context(state: AgentState):
        """Summarize old turns when the approximate token budget is exceeded.
        📘 LEARN: merge the previous summary with old messages, then RemoveMessage those messages.
        Keep recent turns verbatim. Move the cut to a HumanMessage boundary so AI tool calls
        and their ToolMessages stay together. Return {} when compaction is unnecessary.
        Trimming, summarizing and retrieving history are distinct context-management strategies.

        估算的 token 数超过预算时压缩旧轮次。
        📘 LEARN：旧摘要与旧消息一起生成新摘要，再用 RemoveMessage 删除旧消息。
        近期轮次保留原文；截断点回退到 HumanMessage，保证工具调用与结果成对保留。
        无需压缩时返回 {}。直接裁剪、摘要压缩和历史检索是不同的上下文管理策略。
        """
        msgs = state["messages"]
        if (
            len(msgs) <= settings.keep_recent_messages
            or count_tokens_approximately(msgs) <= settings.context_token_budget
        ):
            return {}

        cut = len(msgs) - settings.keep_recent_messages

        while cut > 0 and not isinstance(msgs[cut], HumanMessage):
            cut -= 1
        if cut <= 0:
            return {}
        old = msgs[:cut]

        prompt = SUMMARIZE_PROMPT.format(summary=state.get("summary", ""), transcript=_render(old))
        summary = _text(await model.ainvoke([HumanMessage(prompt)])).strip()

        return {"summary": summary, "messages": [RemoveMessage(id=m.id) for m in old]}

    async def agent(state: AgentState):
        """Build a fresh system prompt and run one reasoning step.
        The last allowed step uses the model without bound tools, requesting a final answer.
        This is graceful budget exhaustion; recursion_limit is the harder fallback.

        构建最新系统提示词，执行一步决策。
        最后一个允许的步骤不绑定工具，要求模型给出最终回答。
        这是预算耗尽时的温和退出；recursion_limit 则是更硬的后备限制。
        """
        iterations = state.get("iterations", 0) + 1
        tools_enabled = iterations < settings.max_iterations
        system = build_system_prompt(
            state,
            remaining_steps=settings.max_iterations - iterations,
            tools_enabled=tools_enabled,
        )
        llm = model_with_tools if tools_enabled else model
        response = await llm.ainvoke([SystemMessage(system), *state["messages"]])

        return {"messages": [response], "iterations": iterations}

    def route_after_agent(state: AgentState) -> Literal["approval_gate", "tools", "reflect", "__end__"]:
        """Route tool calls to approval/tools, or an answer to reflection/END.
        Routers only return node names; they do not update state. Literal helps graph rendering.
        Reflection runs only after tool use, with revision budget and an agent step remaining.

        将工具调用路由到审批或执行，将回答路由到反思或结束。
        路由函数只返回节点名，不更新状态；Literal 帮助绘制图。
        只有本轮使用过工具、反思预算未耗尽、且仍有 Agent 步数时才执行反思。
        """
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            if any(tc["name"] in settings.risky_tools for tc in last.tool_calls):
                return "approval_gate"
            return "tools"

        turn = _current_turn(state["messages"])
        used_tools = any(isinstance(m, ToolMessage) for m in turn)
        if (
            settings.enable_reflection
            and used_tools
            and state.get("reflections", 0) < settings.max_reflections
            and state.get("iterations", 0) < settings.max_iterations
        ):
            return "reflect"
        return END

    def approval_gate(state: AgentState):
        """Pause before mutations and apply approve/edit/reject decisions.
        📘 LEARN: interrupt checkpoints and returns control to the caller. Command(resume=...)
        on the SAME thread re-runs this node from the top; interrupt then returns the answer.
        ⚠ PITFALL: everything before interrupt must be free of side effects.
        Edits replace the AIMessage by ID. Rejections keep the call and receive a ToolMessage.
        Missing/malformed decisions reject writes; safe calls in the same batch still run.

        写入前暂停，应用批准、编辑或拒绝决策。
        📘 LEARN：interrupt 保存检查点并把控制权交给调用方。同一个 thread 上的
        Command(resume=...) 会从节点开头重新执行，此时 interrupt 返回用户的回答。
        ⚠ PITFALL：interrupt 之前不能产生副作用。
        编辑通过相同 ID 替换 AIMessage；拒绝仍保留工具调用，并生成对应 ToolMessage。
        缺失或错误的决策会拒绝写入；同批次的安全调用仍可执行。
        """
        last: AIMessage = state["messages"][-1]
        risky = [tc for tc in last.tool_calls if tc["name"] in settings.risky_tools]

        response = interrupt(
            {
                "type": "approval",
                "calls": [{"id": tc["id"], "name": tc["name"], "args": tc["args"]} for tc in risky],
            }
        )

        decisions = response.get("decisions", {}) if isinstance(response, dict) else {}
        if not isinstance(decisions, dict):
            decisions = {}

        new_calls, hitl = [], {}
        for tc in last.tool_calls:
            d = decisions.get(tc["id"], {}) if tc["name"] in settings.risky_tools else {"action": "approve"}
            if not isinstance(d, dict) or d.get("action") not in ("approve", "edit", "reject"):
                d = {"action": "reject", "reason": "缺少有效的人工审批决策"}
            if d.get("action") == "edit" and not isinstance(d.get("args"), dict):
                d = {"action": "reject", "reason": "修改后的参数必须是 JSON 对象"}
            if d.get("action") == "edit":
                tc = {**tc, "args": d.get("args", tc["args"])}
            elif d.get("action") == "reject":
                hitl[tc["id"]] = {"action": "reject", "reason": d.get("reason", "")}
            new_calls.append(tc)

        updated = last.model_copy(update={"tool_calls": new_calls})
        return {"messages": [updated], "hitl_decisions": hitl}

    async def enforce_hitl(request, execute):
        """Intercept every tool call: reject without execution, apply a timeout, normalize output.
        📘 LEARN: wrappers may inspect a call, execute it, post-process it or short-circuit it.
        Every call must receive a matching ToolMessage, including human rejection.
        A timeout does not prove a remote write was rolled back; inspect the ledger before retrying.

        拦截每个工具调用：拒绝时不执行、设置超时、统一输出格式。
        📘 LEARN：包装器可以检查调用、执行、后处理，也可以直接返回结果。
        每次调用都必须有匹配的 ToolMessage，包括被人工拒绝的调用。
        超时不代表远程写入已回滚；重试前应查询账本确认结果。
        """
        # ToolNode shares one interrupt context across its parallel calls. Ask one combined question.
        # ToolNode 的并行调用共享中断上下文，因此应合并为一次提问。
        calls = request.state["messages"][-1].tool_calls
        if request.tool_call["name"] == "ask_human" and len(calls) > 1:
            return ToolMessage(
                content="Call ask_human alone, combining all necessary questions into one question.\n"
                "请单独调用 ask_human，把必要问题合并为一次提问。",
                tool_call_id=request.tool_call["id"],
                name="ask_human",
                status="error",
            )
        decision = (request.state.get("hitl_decisions") or {}).get(request.tool_call["id"])
        if decision and decision["action"] == "reject":
            return ToolMessage(
                content=f"{REJECT_PREFIX}. Reason: {decision['reason'] or 'not given'}. "
                "Do not retry this exact call; adapt or ask the user.",
                tool_call_id=request.tool_call["id"],
                name=request.tool_call["name"],
                status="error",
            )
        result = await asyncio.wait_for(execute(request), timeout=settings.tool_timeout_seconds)
        return _normalize_tool_result(result)

    # 📘 LEARN: independent calls in one AIMessage run in parallel, each producing a ToolMessage.
    # Dependencies need separate steps: summarize first, then calculate a share from that result.
    # 📘 LEARN：同一 AIMessage 中的独立调用可并行，每个调用产生一条 ToolMessage。
    # 有依赖的调用需要分步：先汇总，再用汇总结果计算占比。
    tool_node = ToolNode(
        tools,
        handle_tool_errors=_handle_tool_error,
        awrap_tool_call=enforce_hitl,
    )

    def loop_guard(state: AgentState):
        """Detect identical name/argument calls and consecutive tool failures in this turn.
        sort_keys makes argument key order irrelevant. Human rejections do not count as failures.
        The warning steers the next prompt; it does not itself halt execution. Clear batch decisions.

        检测本轮相同名称/参数的重复调用，以及连续工具错误。
        sort_keys 排除参数键顺序的影响；人工拒绝不计入工具故障。
        警告注入下一次提示词引导模型，本节点本身不强制停止。执行后清理本批审批决策。
        """
        turn = _current_turn(state["messages"])

        calls = Counter(
            f"{tc['name']}({json.dumps(tc['args'], sort_keys=True, ensure_ascii=False)})"
            for m in turn if isinstance(m, AIMessage) for tc in m.tool_calls
        )
        warnings = [
            f"You have called {sig} {n} times this turn with identical arguments. "
            "The result will not change. Use what you have or try a different approach."
            for sig, n in calls.items() if n >= settings.repeat_call_limit
        ]

        streak = 0
        for m in reversed([m for m in turn if isinstance(m, ToolMessage)]):
            if m.status == "error" and not _text(m).startswith(REJECT_PREFIX):
                streak += 1
            else:
                break
        if streak >= settings.error_streak_limit:
            warnings.append(
                f"The last {streak} tool calls failed. Stop retrying blindly: re-read the "
                "error messages, check argument formats, or explain the problem to the user."
            )

        return {"loop_warning": "\n".join(warnings), "hitl_decisions": {}}

    async def reflect(state: AgentState) -> Command[Literal["agent", "__end__"]]:
        """Review the draft against this turn’s request and tool log.
        📘 LEARN: Command combines a state update with routing. On revise, remove the draft
        and place it with feedback in the next system prompt. Bound this outer loop separately.
        Reflection checks answers; it cannot roll back ledger writes or replace human approval.

        对照本轮请求和工具日志审核回答草稿。
        📘 LEARN：Command 同时更新状态并决定路由。需要修改时删除旧草稿，
        把草稿和反馈加入下次系统提示词。这个外层循环有独立的次数上限。
        反思检查回答，不能撤销账本写入，也不能替代人工审批。
        """
        msgs = state["messages"]
        draft: AIMessage = msgs[-1]
        turn = _current_turn(msgs)
        prompt = CRITIC_PROMPT.format(
            question=_text(turn[0]),
            tool_log=_render(turn[1:-1], limit=400) or "(none)",
            draft=_text(draft),
        )
        verdict = _parse_json(_text(await critic_model.ainvoke([HumanMessage(prompt)])))
        reflections = state.get("reflections", 0) + 1

        if verdict.get("verdict") == "revise" and verdict.get("feedback"):
            return Command(
                goto="agent",
                update={
                    "reflections": reflections,
                    "critique": {"draft": _text(draft), "feedback": verdict["feedback"]},
                    "messages": [RemoveMessage(id=draft.id)],
                },
            )

        return Command(goto=END, update={"reflections": reflections, "critique": None})

    # 📘 LEARN: context_schema enables Runtime/ToolRuntime injection. destinations documents Command routes.
    # 📘 LEARN：context_schema 启用 Runtime/ToolRuntime 注入；destinations 声明 Command 的可能路由。
    g = StateGraph(AgentState, context_schema=AgentContext)

    g.add_node("prepare_turn", prepare_turn)
    g.add_node("compact_context", compact_context)
    g.add_node("agent", agent)
    g.add_node("approval_gate", approval_gate)
    g.add_node("tools", tool_node)
    g.add_node("loop_guard", loop_guard)
    g.add_node("reflect", reflect, destinations=("agent", END))

    g.add_edge(START, "prepare_turn")
    g.add_edge("prepare_turn", "compact_context")
    g.add_edge("compact_context", "agent")

    g.add_conditional_edges("agent", route_after_agent, ["approval_gate", "tools", "reflect", END])
    g.add_edge("approval_gate", "tools")
    g.add_edge("tools", "loop_guard")
    g.add_edge("loop_guard", "compact_context")

    return g.compile(checkpointer=checkpointer, store=store)
