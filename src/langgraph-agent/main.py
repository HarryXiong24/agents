"""Console front-end for the Atlas agent.

    python main.py                      # new thread, user "default"
    python main.py --user harry         # long-term memory is per user
    python main.py --thread <id>        # resume an earlier conversation

📘 LEARN — this file is the *application* around the graph. The graph knows nothing
about terminals; main.py is responsible for:
    1. Wiring infrastructure: model, local + MCP tools, checkpointer, store.
    2. Running one user turn with streaming, so you see each node as it finishes.
    3. The CALLER side of human-in-the-loop: noticing the graph paused, asking the
       human, and resuming with Command(resume=...).
    4. Slash commands that inspect persisted state (/state, /history, /memory).

Swap this file for a FastAPI endpoint or a Slack bot and the graph stays identical.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid

import httpx
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.sqlite.aio import AsyncSqliteStore
from langgraph.types import Command

from agent import memory
from agent.config import settings
from agent.graph import build_graph
from agent.llm import get_chat_model, get_embeddings
from agent.mcp_client import load_mcp_tools
from agent.state import AgentContext
from agent.tools import LOCAL_TOOLS

# ----------------------------------------------------------------------------- terminal styling
DIM, BOLD, RESET = "\033[2m", "\033[1m", "\033[0m"
CYAN, GREEN, YELLOW, RED, MAGENTA = "\033[36m", "\033[32m", "\033[33m", "\033[31m", "\033[35m"


def short(value, n: int = 160) -> str:
    s = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    s = s.replace("\n", " ⏎ ")
    return s if len(s) <= n else s[: n - 1] + "…"


async def ask(prompt: str) -> str:
    return (await asyncio.to_thread(input, prompt)).strip()


HELP = f"""{BOLD}Commands{RESET}
  /new              start a new conversation thread
  /threads          list saved threads          /switch <id>   resume a thread
  /state            show loop counters, summary and context size
  /history          list checkpoints of the current thread (time-travel log)
  /memory           list long-term memories     /forget <id>   delete one
  /tools            list tools (⚠ = needs approval)
  /graph            print the graph as Mermaid
  /help             this help                   /quit          exit"""


# ----------------------------------------------------------------------------- rendering of graph events

def render_update(node: str, update: dict | None) -> None:
    """Pretty-print one streamed event.

    📘 LEARN — stream modes: `graph.astream(..., stream_mode="updates")` yields
    `{node_name: the_update_that_node_returned}` after each node finishes. Other modes:
        "values"   → the full state after each step
        "messages" → LLM tokens as they are generated (for typewriter-style output)
        "custom"   → anything a node/tool writes via get_stream_writer()
    You can pass a list, e.g. ["updates", "messages"], to get several at once.
    """
    if not update:
        return
    if node == "agent":
        for msg in update.get("messages", []):
            if isinstance(msg, AIMessage) and msg.tool_calls:
                if msg.content:
                    print(f"{DIM}  💭 {short(msg.content, 200)}{RESET}")
                for tc in msg.tool_calls:
                    risky = " ⚠" if tc["name"] in settings.risky_tools else ""
                    print(f"{CYAN}  → {tc['name']}{risky}({short(tc['args'], 140)}){RESET}")
    elif node == "tools":
        for msg in update.get("messages", []):
            if isinstance(msg, ToolMessage):
                color = RED if msg.status == "error" else GREEN
                print(f"{color}  ← {msg.name}: {short(msg.content, 180)}{RESET}")
    elif node == "loop_guard" and update.get("loop_warning"):
        print(f"{YELLOW}  ⚠ loop guard: {short(update['loop_warning'], 200)}{RESET}")
    elif node == "compact_context" and update.get("summary"):
        n = len(update.get("messages", []))
        print(f"{MAGENTA}  ⇢ context compacted: {n} old messages folded into the summary{RESET}")
    elif node == "reflect":
        critique = update.get("critique")
        if critique:
            print(f"{MAGENTA}  ✎ critic asked for a revision: {short(critique['feedback'], 200)}{RESET}")
        else:
            print(f"{DIM}  ✓ critic approved the answer{RESET}")
    elif node == "prepare_turn" and update.get("memories"):
        print(f"{DIM}  ⓜ recalled {len(update['memories'])} memory item(s){RESET}")


# ----------------------------------------------------------------------------- human-in-the-loop prompts

async def handle_interrupt(payload: dict):
    """Turn an interrupt payload into a resume value by asking the human.

    📘 LEARN: the payload is whatever the graph passed to `interrupt(...)`. Its shape is a
    contract between graph and caller — here a "type" field says which UI to show:
        {"type": "question", "question": ...}            ← from the ask_human tool
        {"type": "approval", "calls": [{id,name,args}]}   ← from approval_gate
    The return value becomes the result of `interrupt()` inside the graph.
    """
    if payload.get("type") == "question":
        print(f"\n{YELLOW}{BOLD}🙋 Agent asks:{RESET} {payload['question']}")
        return await ask(f"{YELLOW}your answer> {RESET}")

    if payload.get("type") == "approval":
        decisions = {}
        print(f"\n{YELLOW}{BOLD}⏸  Approval required{RESET}")
        for call in payload["calls"]:
            print(f"{YELLOW}  {call['name']}{RESET}")
            print(json.dumps(call["args"], ensure_ascii=False, indent=4))
            while True:
                choice = (await ask("  [a]pprove / [e]dit args / [r]eject ? ")).lower()[:1]
                if choice in ("a", ""):
                    decisions[call["id"]] = {"action": "approve"}
                    break
                if choice == "r":
                    reason = await ask("  reason (optional): ")
                    decisions[call["id"]] = {"action": "reject", "reason": reason}
                    break
                if choice == "e":
                    raw = await ask("  new args as JSON: ")
                    try:
                        decisions[call["id"]] = {"action": "edit", "args": json.loads(raw)}
                        break
                    except json.JSONDecodeError as exc:
                        print(f"{RED}  invalid JSON: {exc}{RESET}")
        return {"decisions": decisions}

    print(f"{RED}Unknown interrupt payload: {payload}{RESET}")
    return None


# ----------------------------------------------------------------------------- one user turn

async def run_turn(graph, payload, config: dict, ctx: AgentContext) -> None:
    """Run one user turn to completion, handling any number of interrupts.

    📘 LEARN — the HITL driver loop:

        payload = {"messages": [HumanMessage]}        # first call: new input
        loop:
            stream the graph until it ENDS or PAUSES
            snapshot = aget_state(config)              # read the latest checkpoint
            paused?  snapshot.interrupts is non-empty
                     → ask human → payload = Command(resume=answer) → loop again
            else     → done

    ⚠ PITFALL: resuming must use the SAME thread_id (it's in `config`). The thread_id is
    how LangGraph finds the checkpoint where the graph paused. A different thread_id
    would start a brand new conversation instead.
    ⚠ PITFALL: resume with Command(resume=...), not a new {"messages": [...]} input.
    Sending new input to a paused thread does not answer the pending interrupt.
    """
    while True:
        async for chunk in graph.astream(payload, config, context=ctx, stream_mode="updates"):
            for node, update in chunk.items():
                if node != "__interrupt__":
                    render_update(node, update)
        snapshot = await graph.aget_state(config)
        if snapshot.interrupts:                       # graph paused: ask the human, then resume
            resume = await handle_interrupt(snapshot.interrupts[0].value)
            payload = Command(resume=resume)
            continue
        break

    messages = snapshot.values.get("messages", [])
    final = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
    if final is not None and final.content:
        print(f"\n{BOLD}Atlas:{RESET} {final.content}\n")


# ----------------------------------------------------------------------------- commands

async def list_threads(saver: AsyncSqliteSaver) -> list[str]:
    seen: dict[str, None] = {}
    async for cp in saver.alist(None):
        seen.setdefault(cp.config["configurable"]["thread_id"], None)
    return list(seen)


async def handle_command(cmd: str, *, graph, saver, store, session: dict) -> bool:
    """Return False to quit."""
    name, _, arg = cmd.partition(" ")
    config = {"configurable": {"thread_id": session["thread_id"]}, "recursion_limit": settings.recursion_limit}
    user_id = session["ctx"].user_id

    if name in ("/quit", "/exit"):
        return False
    if name == "/help":
        print(HELP)
    elif name == "/new":
        session["thread_id"] = uuid.uuid4().hex[:8]
        print(f"New thread: {session['thread_id']}")
    elif name == "/threads":
        for t in await list_threads(saver):
            mark = " (current)" if t == session["thread_id"] else ""
            print(f"  {t}{mark}")
    elif name == "/switch" and arg:
        session["thread_id"] = arg.strip()
        print(f"Switched to thread {session['thread_id']}")
    elif name == "/state":
        v = (await graph.aget_state(config)).values
        msgs = v.get("messages", [])
        print(f"  thread        : {session['thread_id']}")
        print(f"  messages      : {len(msgs)} (~{count_tokens_approximately(msgs)} tokens, "
              f"budget {settings.context_token_budget})")
        print(f"  last turn     : iterations={v.get('iterations', 0)}/{settings.max_iterations}, "
              f"reflections={v.get('reflections', 0)}/{settings.max_reflections}")
        print(f"  summary       : {v.get('summary') or '(none)'}")
    elif name == "/history":
        # 📘 LEARN — every super-step is a checkpoint. You could pass any of these
        # checkpoint configs back to graph.astream(None, that_config) to replay from that
        # point, or aupdate_state(...) to fork with edited state: "time travel".
        async for snap in graph.aget_state_history(config):
            step = snap.metadata.get("step")
            print(f"  step {step:>3}  next={list(snap.next) or ['END']}  "
                  f"checkpoint={snap.config['configurable']['checkpoint_id'][-8:]}")
    elif name == "/memory":
        items = await memory.list_all(store, user_id)
        print("\n".join(f"  [{k}] {c}" for k, c in items) or "  (no memories yet)")
    elif name == "/forget" and arg:
        ok = await memory.delete(store, user_id, arg.strip("[] "))
        print("  deleted" if ok else "  not found")
    elif name == "/tools":
        for t in session["tools"]:
            mark = "⚠ " if t.name in settings.risky_tools else "  "
            print(f"  {mark}{t.name:<16} {short(t.description, 90)}")
    elif name == "/graph":
        print(graph.get_graph().draw_mermaid())
    else:
        print("Unknown command. /help for the list.")
    return True


# ----------------------------------------------------------------------------- entry point

async def check_ollama() -> None:
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            tags = (await client.get(f"{settings.base_url}/api/tags")).json()
        names = {m["name"] for m in tags.get("models", [])}
        if settings.model not in names and f"{settings.model}:latest" not in names:
            print(f"{YELLOW}! Model '{settings.model}' not found in Ollama. Run: ollama pull {settings.model}{RESET}")
    except Exception:
        print(f"{RED}! Cannot reach Ollama at {settings.base_url}. Is `ollama serve` running?{RESET}")


async def main() -> None:
    """Wire everything together and run the REPL.

    📘 LEARN — startup order matters:
        1. load MCP tools  (spawns server subprocesses, reads their tool lists)
        2. open SQLite checkpointer + store (async context managers → closed cleanly)
        3. build_graph(model, tools, checkpointer, store) → compiled graph
        4. loop: read input → run_turn(...)
    """
    parser = argparse.ArgumentParser(description="Atlas — LangGraph agent console")
    parser.add_argument("--user", default="default", help="user id for long-term memory")
    parser.add_argument("--thread", default=None, help="resume an existing thread id")
    args = parser.parse_args()

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.workspace_dir.mkdir(parents=True, exist_ok=True)

    print(f"{BOLD}Atlas{RESET} · LangGraph ReAct agent · model={settings.model}")
    await check_ollama()

    mcp_tools, report = await load_mcp_tools()
    for server, names in report.items():
        print(f"{DIM}  MCP '{server}': {', '.join(names)}{RESET}")
    tools = [*LOCAL_TOOLS, *mcp_tools]

    # 📘 LEARN — Store index: with an embeddings model, the store embeds the "content"
    # field of every value on write and supports `asearch(ns, query=...)` by similarity.
    # Without it, the store is a plain key-value store and memory.py falls back to
    # keyword matching.
    embeddings = get_embeddings()
    index = {"embed": embeddings, "dims": settings.embed_dims, "fields": ["content"]} if embeddings else None

    async with (
        AsyncSqliteSaver.from_conn_string(str(settings.data_dir / "checkpoints.sqlite")) as saver,
        AsyncSqliteStore.from_conn_string(str(settings.data_dir / "store.sqlite"), index=index) as store,
    ):
        # 📘 LEARN — two databases, two lifetimes:
        #   checkpoints.sqlite : every state snapshot of every thread (short-term memory)
        #   store.sqlite       : long-term memories, independent of threads
        await store.setup()  # creates tables on first run (the saver does this lazily)
        graph = build_graph(get_chat_model(), tools, checkpointer=saver, store=store)
        session = {
            "thread_id": args.thread or uuid.uuid4().hex[:8],
            "ctx": AgentContext(user_id=args.user),
            "tools": tools,
        }
        print(f"{DIM}  thread={session['thread_id']} user={args.user} · /help for commands{RESET}\n")

        while True:
            try:
                text = await ask(f"{BOLD}you>{RESET} ")
            except (EOFError, KeyboardInterrupt):
                break
            if not text:
                continue
            if text.startswith("/"):
                if not await handle_command(text, graph=graph, saver=saver, store=store, session=session):
                    break
                continue
            # 📘 LEARN — config vs context:
            #   config["configurable"]["thread_id"] → which conversation (checkpoint key)
            #   config["recursion_limit"]           → loop engineering layer 5 (hard fuse)
            #   context=AgentContext(user_id)       → who the run is for (not persisted)
            config = {
                "configurable": {"thread_id": session["thread_id"]},
                "recursion_limit": settings.recursion_limit,
            }
            try:
                await run_turn(graph, {"messages": [HumanMessage(text)]}, config, session["ctx"])
            except KeyboardInterrupt:
                print(f"\n{YELLOW}(turn interrupted){RESET}")
            except Exception as exc:  # noqa: BLE001 - keep the REPL alive
                print(f"{RED}Error: {type(exc).__name__}: {exc}{RESET}")
    print("bye")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
