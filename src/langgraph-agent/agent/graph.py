"""The agent graph: a hand-built ReAct loop with loop engineering, HITL and memory.

★ This is the most important file in the repo. Read it top to bottom. ★

Comment conventions used throughout the codebase:
    📘 LEARN    — the concept behind the code (what / why)
    ⚠ PITFALL  — a mistake that is easy to make here
    🔁 FLOW     — where execution goes next
    🧪 TRY      — a small experiment you can run to see the behaviour yourself

                    ┌──────────────┐
         START ───▶ │ prepare_turn │  reset per-turn counters, recall long-term memory
                    └──────┬───────┘
                           ▼
                  ┌─────────────────┐
           ┌────▶ │ compact_context │  summarise old messages if over token budget
           │      └────────┬────────┘
           │               ▼
           │          ┌─────────┐   no tool calls   ┌─────────┐  pass   ┌─────┐
           │          │  agent  │ ────────────────▶ │ reflect │ ──────▶ │ END │
           │          └────┬────┘                   └────┬────┘         └─────┘
           │   tool calls  │  ▲                revise    │
           │   ┌───────────┤  └──────────────────────────┘
           │   │ risky?    │ safe
           │   ▼           │
           │ ┌───────────────┐  interrupt() → human approves / edits / rejects
           │ │ approval_gate │
           │ └──────┬────────┘
           │        ▼      ▼
           │      ┌─────────┐   local tools + MCP tools (rejected calls short-circuited)
           │      │  tools  │
           │      └────┬────┘
           │           ▼
           │    ┌────────────┐   detect repeated calls / error streaks
           └─── │ loop_guard │
                └────────────┘

📘 LEARN — LangGraph in 60 seconds
    A LangGraph program is a *state machine*:
      • State  : a dict (here `AgentState`) shared by all nodes.
      • Node   : a function `state -> partial update`. It never mutates state in place;
                 it RETURNS the keys it wants to change. LangGraph merges the update
                 using each key's *reducer* (see state.py).
      • Edge   : "after node A, run node B". A *conditional* edge calls a routing
                 function that looks at state and returns the next node's name.
      • Super-step : one round of running node(s). After EVERY super-step the
                 checkpointer saves a snapshot of the state. That is what makes
                 pause/resume (HITL), multi-turn memory and time-travel possible.

📘 LEARN — Why build the graph by hand instead of `create_react_agent(...)`?
    `create_react_agent` gives you exactly two nodes: agent ⇄ tools. Production agents
    need more: approval steps, loop limits, context compaction, self-checks. Writing
    the graph yourself turns each of these into a visible node you can test in isolation.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,       # what the model says; may contain `.tool_calls`
    AnyMessage,
    HumanMessage,    # what the user says
    RemoveMessage,   # special marker: "delete the message with this id from state"
    SystemMessage,   # instructions; we rebuild it every step and never store it in state
    ToolMessage,     # the result of one tool call; linked by `tool_call_id`
)
from langchain_core.messages.utils import count_tokens_approximately
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt

from . import memory
from .config import settings
from .prompts import CRITIC_PROMPT, SUMMARIZE_PROMPT, build_system_prompt
from .state import AgentContext, AgentState

# A fixed prefix lets other parts of the code recognise "this ToolMessage is a human
# rejection, not a real tool failure" (loop_guard must not count rejections as errors).
REJECT_PREFIX = "REJECTED by human"


# =========================================================================== helpers
# Small pure functions. No LangGraph magic here — just message-list manipulation.

def _current_turn(messages: list[AnyMessage]) -> list[AnyMessage]:
    """Messages since (and including) the latest HumanMessage.

    📘 LEARN: The thread's message list holds the WHOLE conversation. Most per-turn logic
    (loop detection, "did we use tools this turn?", the critic's view) must only look at
    the current turn, otherwise a repeated call from yesterday would trigger today's guard.

        [Human, AI, Human, AI(tool_calls), Tool, Tool, AI]
                       ^^^^^ current turn starts here
    """
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            return messages[i:]
    return list(messages)


def _text(msg: AnyMessage) -> str:
    """Get a message's text whether `content` is a plain string or a list of blocks.

    📘 LEARN: LangChain message content can be `str` OR `list[dict]` ("content blocks",
    e.g. [{"type": "text", "text": "..."}, {"type": "image_url", ...}]). MCP tools return
    the block form. Always normalise before doing string operations.
    """
    c = msg.content
    if isinstance(c, list):  # multimodal / block content
        c = "\n".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in c)
    return str(c)


def _render(messages: list[AnyMessage], limit: int = 600) -> str:
    """Turn messages into a compact plain-text transcript for a *secondary* LLM call
    (the summariser and the critic). Each line is truncated to keep that call cheap."""
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
    """Extract the first {...} object from model output.

    ⚠ PITFALL: Small local models often wrap JSON in prose or ```json fences, or emit
    slightly broken JSON. Never `json.loads(response)` directly; extract and fail soft.
    On failure we return {} and the caller treats it as "pass" (the safe default).
    """
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}


MAX_TOOL_OUTPUT = 4000  # characters; roughly 1k tokens


def _normalize_tool_result(result):
    """Flatten MCP content blocks to plain text and cap the size.

    📘 LEARN — context hygiene: a single `read_file` on a big log could dump 100k chars
    into the conversation and push everything else out of the model's context window.
    Capping every tool result at one choke point is the cheapest protection there is.
    """
    if isinstance(result, ToolMessage):
        text = _text(result)
        if len(text) > MAX_TOOL_OUTPUT:
            text = text[:MAX_TOOL_OUTPUT] + f"\n... [truncated {len(text) - MAX_TOOL_OUTPUT} chars]"
        if text != result.content:
            # Messages are pydantic models: copy-with-changes instead of mutating.
            result = result.model_copy(update={"content": text})
    return result


# =========================================================================== graph factory

def build_graph(
    model: BaseChatModel,
    tools: list[BaseTool],
    *,
    checkpointer=None,
    store=None,
    critic_model: BaseChatModel | None = None,
):
    """Assemble and compile the agent graph.

    📘 LEARN — dependency injection: the model, tools, checkpointer and store are all
    passed in. That is why tests can swap Qwen for a scripted fake model and SQLite for
    in-memory storage while exercising exactly the same graph.

    Nodes are defined as *closures* inside this function so they can use `model`,
    `tools`, etc. without globals.
    """
    critic_model = critic_model or model

    # 📘 LEARN — bind_tools: converts each tool's Python signature + docstring into a
    # JSON-Schema "function" definition and attaches it to every request. The model then
    # replies either with text or with structured `tool_calls`. This is function calling;
    # ReAct on top of it is just "loop until there are no more tool_calls".
    # 🧪 TRY: print(tools[0].tool_call_schema.model_json_schema()) to see what Qwen sees.
    model_with_tools = model.bind_tools(tools)

    # ------------------------------------------------------------------ node: prepare_turn
    async def prepare_turn(state: AgentState, runtime: Runtime[AgentContext]):
        """Start of a user turn: reset loop counters and recall relevant long-term memory.

        📘 LEARN — Runtime injection: if a node declares a parameter typed `Runtime[...]`,
        LangGraph passes in the per-run `context` (here: user_id) and the `store`.
        Context is static input for this run; it is NOT saved in the checkpoint.

        📘 LEARN — why reset here? State is persisted across turns. Without a reset, the
        iteration counter from the previous question would eat into this one's budget.
        """
        turn = _current_turn(state["messages"])
        query = _text(turn[0]) if turn else ""
        # Long-term memory READ path: fetch facts relevant to the new user message.
        # They are not added as messages; build_system_prompt() puts them in the prompt.
        memories = await memory.recall(runtime.store, runtime.context.user_id, query)
        return {
            "iterations": 0,
            "reflections": 0,
            "loop_warning": "",
            "critique": None,
            "hitl_decisions": {},
            "memories": memories,
        }
        # 🔁 FLOW: fixed edge → compact_context

    # ------------------------------------------------------------------ node: compact_context
    async def compact_context(state: AgentState):
        """Short-term memory management: fold old messages into a rolling summary.

        📘 LEARN — the problem: a thread's message list grows forever, but the model has a
        finite context window, and quality drops long before the window is full
        ("context rot"). Three common strategies:
            1. Trim     — drop old messages. Cheap, but forgets.
            2. Summarise — replace old messages with an LLM-written summary.  ← we do this
            3. Retrieve  — store everything, fetch only relevant pieces (RAG over history).

        How it works:
            messages: [H1 A1 H2 A2(tc) T T A2' H3 A3 H4]      budget exceeded
                       └──── old ─────────────┘ └─ keep ─┘
            → summary  = LLM("existing summary" + old)
            → messages = [RemoveMessage(id) for each old]   (deleted via the reducer)

        Runs before EVERY agent step (also mid-turn), but returns {} (no-op) when under
        budget, so it costs nothing most of the time.
        """
        msgs = state["messages"]
        if (
            len(msgs) <= settings.keep_recent_messages
            or count_tokens_approximately(msgs) <= settings.context_token_budget
        ):
            return {}  # 📘 Returning {} means "no change". Every node may do this.

        cut = len(msgs) - settings.keep_recent_messages
        # ⚠ PITFALL: Never split an AIMessage(tool_calls) from its ToolMessages. A
        # ToolMessage whose tool call was deleted is an invalid conversation for most chat
        # APIs. Moving the cut back to a HumanMessage boundary guarantees whole turns.
        while cut > 0 and not isinstance(msgs[cut], HumanMessage):
            cut -= 1
        if cut <= 0:
            return {}  # the current turn alone is big; tool-output capping handles that
        old = msgs[:cut]

        # "Rolling" summary: the previous summary is fed back in, so information compacted
        # three times ago is not lost — it is re-summarised together with the new part.
        prompt = SUMMARIZE_PROMPT.format(summary=state.get("summary", ""), transcript=_render(old))
        summary = _text(await model.ainvoke([HumanMessage(prompt)])).strip()

        # 📘 LEARN — RemoveMessage: the `messages` key uses the `add_messages` reducer, which
        # appends new messages, REPLACES messages with an existing id, and DELETES messages
        # for which it receives RemoveMessage(id=...). You cannot just return a shorter
        # list: that would be interpreted as "append these".
        return {"summary": summary, "messages": [RemoveMessage(id=m.id) for m in old]}
        # 🔁 FLOW: fixed edge → agent

    # ------------------------------------------------------------------ node: agent
    async def agent(state: AgentState):
        """The "Reason" half of ReAct: one LLM call that decides the next action.

        📘 LEARN — dynamic system prompt (context engineering): the system prompt is NOT
        stored in state. It is rebuilt from state on every step, so it always contains the
        latest summary, memories, loop warnings, critique and remaining budget. The model
        sees a curated view instead of a raw transcript.

        📘 LEARN — loop engineering layer 2, the forced final answer: on the last allowed
        step we call the model WITHOUT tools. A model that has no tools bound cannot emit
        tool calls, so the loop is guaranteed to end with a real answer instead of an
        exception. Compare with relying only on recursion_limit, which just crashes.
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
        # Only the AI response is appended to state; the SystemMessage is ephemeral.
        return {"messages": [response], "iterations": iterations}
        # 🔁 FLOW: conditional edge → route_after_agent decides

    # ------------------------------------------------------------------ router after agent
    def route_after_agent(state: AgentState) -> Literal["approval_gate", "tools", "reflect", "__end__"]:
        """The ReAct decision point, expressed as a conditional edge.

        📘 LEARN: A router is a plain function that returns the NAME of the next node.
        It must not change state (it has no way to return updates).

            tool_calls & any risky  → approval_gate   (human must approve first)
            tool_calls & all safe   → tools           (act)
            no tool_calls           → reflect / END   (the model thinks it is done)

        The `Literal[...]` return annotation lets LangGraph draw the graph correctly.
        """
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            if any(tc["name"] in settings.risky_tools for tc in last.tool_calls):
                return "approval_gate"
            return "tools"

        # Reflection costs an extra LLM call, so only spend it when the answer is built on
        # tool results (where fabrication / misreading is most likely). Pure chit-chat skips it.
        turn = _current_turn(state["messages"])
        used_tools = any(isinstance(m, ToolMessage) for m in turn)
        if (
            settings.enable_reflection
            and used_tools
            and state.get("reflections", 0) < settings.max_reflections
        ):
            return "reflect"
        return END

    # ------------------------------------------------------------------ node: approval_gate (HITL)
    def approval_gate(state: AgentState):
        """Pause before risky tool calls. The human approves, edits the args, or rejects.

        📘 LEARN — how interrupt() works, step by step:
          1. First run: `interrupt(payload)` raises a special exception. LangGraph catches
             it, saves a checkpoint (state + "we were inside approval_gate"), and returns
             control to the caller. `payload` is exposed as `snapshot.interrupts[0].value`.
          2. The caller (main.py) shows the payload to the human and collects a decision.
          3. The caller runs `graph.astream(Command(resume=decision), same thread_id)`.
          4. LangGraph loads the checkpoint and RE-RUNS THIS NODE FROM THE TOP. This time
             `interrupt()` does not pause — it returns `decision`.

        ⚠ PITFALL: because of step 4, any code BEFORE interrupt() runs twice. Keep it
        side-effect free (no API calls, no file writes, no DB inserts). Here we only read
        state, so re-running is harmless.

        📘 LEARN — durability: the pause is just a saved checkpoint. With the SQLite
        checkpointer you can quit the program, restart with `--thread <id>`, and the
        approval request is still pending. Nothing is blocked in memory.
        """
        last: AIMessage = state["messages"][-1]
        risky = [tc for tc in last.tool_calls if tc["name"] in settings.risky_tools]

        response = interrupt(  # ← execution pauses here on the first run
            {
                "type": "approval",
                "calls": [{"id": tc["id"], "name": tc["name"], "args": tc["args"]} for tc in risky],
            }
        )
        # Below this line only runs after resume. Expected shape:
        #   {"decisions": {tool_call_id: {"action": "approve" | "edit" | "reject", ...}}}
        decisions: dict = (response or {}).get("decisions", {})

        new_calls, hitl = [], {}
        for tc in last.tool_calls:
            d = decisions.get(tc["id"], {"action": "approve"})  # safe tools: auto-approve
            if d.get("action") == "edit":
                tc = {**tc, "args": d.get("args", tc["args"])}
            elif d.get("action") == "reject":
                # We do NOT delete the call. We record the rejection; the tools node turns it
                # into a ToolMessage so the history stays valid and the model learns why.
                hitl[tc["id"]] = {"action": "reject", "reason": d.get("reason", "")}
            new_calls.append(tc)

        # 📘 LEARN — replace-by-id: `updated` keeps the original message id, so the
        # add_messages reducer REPLACES the old AIMessage instead of appending a new one.
        # Result: the history records the args that actually ran (honest audit trail).
        updated = last.model_copy(update={"tool_calls": new_calls})
        return {"messages": [updated], "hitl_decisions": hitl}
        # 🔁 FLOW: fixed edge → tools

    # ------------------------------------------------------------------ node: tools
    async def enforce_hitl(request, execute):
        """Tool-call interceptor (middleware around every single tool execution).

        📘 LEARN — interceptor pattern: ToolNode calls `awrap_tool_call(request, execute)`
        for each tool call. You may inspect/modify `request`, call `execute(request)` to
        really run the tool, post-process the result, or skip execution entirely and
        return your own ToolMessage. It is the place for cross-cutting concerns:
        permissions, rate limits, caching, logging, output sanitising.

        Here it does two things:
          • rejected calls → return a "REJECTED" ToolMessage without running the tool
          • executed calls → normalise/cap the output
        """
        decision = (request.state.get("hitl_decisions") or {}).get(request.tool_call["id"])
        if decision and decision["action"] == "reject":
            # ⚠ PITFALL: every tool_call in an AIMessage MUST be answered by a ToolMessage
            # with the matching tool_call_id. Skipping it leaves a dangling call and many
            # model APIs will reject the next request.
            return ToolMessage(
                content=f"{REJECT_PREFIX}. Reason: {decision['reason'] or 'not given'}. "
                "Do not retry this exact call; adapt or ask the user.",
                tool_call_id=request.tool_call["id"],
                name=request.tool_call["name"],
                status="error",
            )
        result = await execute(request)
        return _normalize_tool_result(result)

    # 📘 LEARN — ToolNode is the "Act / Observe" half of ReAct. It reads the tool_calls on
    # the last AIMessage, runs them (in parallel when there are several), and appends one
    # ToolMessage per call.
    #
    # 📘 LEARN — loop engineering layer 3, error-as-observation: with
    # handle_tool_errors=True an exception (bad path, invalid args, timeout...) becomes a
    # ToolMessage(status="error", content="Error: ..."). The model reads the error and can
    # fix its own mistake on the next step, instead of the whole run crashing.
    # (GraphInterrupt is special-cased and still propagates, so ask_human keeps working.)
    tool_node = ToolNode(
        tools,
        handle_tool_errors=True,
        awrap_tool_call=enforce_hitl,
    )

    # ------------------------------------------------------------------ node: loop_guard
    def loop_guard(state: AgentState):
        """Loop engineering layer 4: detect degenerate loops and steer the model.

        📘 LEARN — two classic agent failure modes:
          • Repetition: calling the same tool with the same args again and again, hoping
            for a different result. Detected by counting `name(args)` signatures.
          • Error spiral: tool fails → model retries blindly → fails again ...
            Detected by counting consecutive error ToolMessages at the end of the turn.

        We do not stop the graph here. We write `loop_warning`, which build_system_prompt()
        injects into the next system prompt. This is *steering*, a softer and usually more
        useful intervention than killing the run. The hard stop is the step budget.
        """
        turn = _current_turn(state["messages"])

        # sort_keys=True so {"a":1,"b":2} and {"b":2,"a":1} count as the same call.
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
            # Human rejections are not tool failures; don't count them.
            if m.status == "error" and not _text(m).startswith(REJECT_PREFIX):
                streak += 1
            else:
                break
        if streak >= settings.error_streak_limit:
            warnings.append(
                f"The last {streak} tool calls failed. Stop retrying blindly: re-read the "
                "error messages, check argument formats, or explain the problem to the user."
            )

        # Clear hitl_decisions: they applied only to the tool batch that just ran.
        return {"loop_warning": "\n".join(warnings), "hitl_decisions": {}}
        # 🔁 FLOW: fixed edge → compact_context → agent  (this closes the ReAct loop)

    # ------------------------------------------------------------------ node: reflect
    async def reflect(state: AgentState) -> Command[Literal["agent", "__end__"]]:
        """Self-critique loop (also called Reflexion / evaluator-optimizer).

        📘 LEARN: A second LLM call reviews the draft answer against the tool log. It is
        an OUTER loop around the ReAct loop:
            agent → ... → draft → critic says "revise" → agent (with feedback) → new draft

        Capped by max_reflections so the critic itself cannot cause an infinite loop.

        📘 LEARN — Command(goto=..., update=...): a node can both update state AND choose
        the next node, instead of using a separate router. Useful when the routing
        decision is a by-product of the node's own work (here: the critic's verdict).
        Declare possible targets with `destinations=` in add_node so the graph draws right.

        📘 LEARN — why remove the draft? If we kept it and appended feedback, the model
        would see its own wrong answer as a finished turn and tend to repeat it. Removing it
        and quoting it in the system prompt ("here was your draft, here is the feedback")
        frames the next step as a rewrite.
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
        # Unparseable verdict → treated as pass. Failing open is right for a quality check;
        # it would be wrong for a safety check (that's what approval_gate is for).
        return Command(goto=END, update={"reflections": reflections, "critique": None})

    # ================================================================== wiring
    # 📘 LEARN: context_schema declares the type of the per-run `context` object, which
    # nodes receive via `Runtime` and tools via `ToolRuntime`.
    g = StateGraph(AgentState, context_schema=AgentContext)

    g.add_node("prepare_turn", prepare_turn)
    g.add_node("compact_context", compact_context)
    g.add_node("agent", agent)
    g.add_node("approval_gate", approval_gate)
    g.add_node("tools", tool_node)            # a ToolNode is itself a valid node
    g.add_node("loop_guard", loop_guard)
    g.add_node("reflect", reflect, destinations=("agent", END))  # routes via Command

    g.add_edge(START, "prepare_turn")
    g.add_edge("prepare_turn", "compact_context")
    g.add_edge("compact_context", "agent")
    # The 3rd argument lists every possible target (used for validation and drawing).
    g.add_conditional_edges("agent", route_after_agent, ["approval_gate", "tools", "reflect", END])
    g.add_edge("approval_gate", "tools")
    g.add_edge("tools", "loop_guard")
    g.add_edge("loop_guard", "compact_context")   # ← the back-edge that makes it a loop

    # 📘 LEARN — compile(): validates the graph (no dangling nodes/edges) and attaches:
    #   • checkpointer → short-term memory, pause/resume, history (needs a thread_id)
    #   • store        → long-term memory shared across threads
    # Without a checkpointer, interrupt() cannot work: there is nowhere to save the pause.
    # 🧪 TRY: `/graph` in the console prints this graph as Mermaid.
    return g.compile(checkpointer=checkpointer, store=store)
