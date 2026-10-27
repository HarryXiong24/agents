"""Console for Ledger: uv run react-agent --user harry [--thread ID].
📘 LEARN: the graph is independent of the terminal. This caller wires services, streams
node updates, handles interrupts/resume, and exposes inspection commands.
A web UI could replace this file without changing the graph.

Ledger 控制台：uv run react-agent --user harry [--thread ID]。
📘 LEARN：图不依赖终端。调用方负责连接服务、流式展示节点更新、
处理暂停与恢复，并提供检查命令。可以替换为网页入口而不修改图。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import threading
import uuid

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.sqlite.aio import AsyncSqliteStore
from langgraph.types import Command

from agent_apps.react_agent.agent import memory
from agent_apps.react_agent.agent.config import settings, user_data_dir
from agent_apps.react_agent.agent.graph import build_graph
from agent_apps.react_agent.agent.llm import get_chat_model
from agent_apps.react_agent.agent.mcp_client import load_mcp_tools
from agent_apps.react_agent.agent.state import AgentContext
from agent_apps.react_agent.agent.tools import LOCAL_TOOLS

DIM, BOLD, RESET = "\033[2m", "\033[1m", "\033[0m"
CYAN, GREEN, YELLOW, RED, MAGENTA = (
    "\033[36m",
    "\033[32m",
    "\033[33m",
    "\033[31m",
    "\033[35m",
)


def short(value, n: int = 160) -> str:
    s = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    s = s.replace("\n", " ⏎ ")
    return s if len(s) <= n else s[: n - 1] + "…"


async def ask(prompt: str) -> str:
    """Read terminal input without keeping process shutdown waiting after Ctrl+C.
    A daemon thread can wait for input; the event-loop thread owns the result Future.

    读取终端输入，避免 Ctrl+C 后进程仍等待输入线程结束。
    守护线程等待输入；结果 Future 由事件循环线程操作。
    """
    loop = asyncio.get_running_loop()
    answer = loop.create_future()

    def finish(value, error):
        if answer.done():
            return
        if error is not None:
            answer.set_exception(error)
        else:
            answer.set_result(value)

    def read():
        value, error = None, None
        try:
            value = input(prompt).strip()
        except Exception as exc:
            error = exc
        try:
            loop.call_soon_threadsafe(finish, value, error)
        except RuntimeError:
            # Cancellation may already have closed the loop; no answer is needed then.
            # 取消后事件循环可能已关闭，此时不再需要传回输入结果。
            pass

    # The default executor waits for input() at shutdown. A daemon thread does not.
    # 默认线程池在关闭时会等待 input()；守护线程不会阻止进程退出。
    threading.Thread(target=read, daemon=True, name="ledger-console-input").start()
    return await answer


HELP = f"""{BOLD}Commands / 命令{RESET}
  /new              Start a new thread
                    新建会话
  /threads          List this user's saved threads
                    查看当前用户的会话
  /switch <id>      Switch threads and resume pending interrupts
                    切换会话并恢复待处理中断
  /state            Inspect counters, summary and context size
                    检查计数器、摘要和上下文大小
  /history          Inspect checkpoints (not a ledger undo command)
                    检查检查点（不是账本撤销命令）
  /memory           List preferences     /forget <id>   Delete a preference
                    查看偏好                              删除偏好
  /tools            List tools (⚠ = approval required)
                    查看工具（⚠ 表示需要审批）
  /graph            Print the Mermaid graph
                    输出 Mermaid 图
  /help             Show help            /quit          Exit
                    显示帮助                              退出"""


def render_update(node: str, update: dict | None) -> None:
    """Render node updates from stream_mode="updates".
    Other modes: values=full state, messages=model tokens, custom=application events.
    A list of modes combines streams; rejected drafts need care when streaming tokens.

    展示 stream_mode="updates" 返回的节点更新。
    其他模式：values 为完整状态，messages 为模型 token，custom 为自定义事件。
    可以组合多个模式；逐 token 展示时需考虑被反思否决的草稿如何呈现。
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
                    print(
                        f"{CYAN}  → {tc['name']}{risky}({short(tc['args'], 140)}){RESET}"
                    )
    elif node == "tools":
        for msg in update.get("messages", []):
            if isinstance(msg, ToolMessage):
                color = RED if msg.status == "error" else GREEN
                print(f"{color}  ← {msg.name}: {short(msg.content, 180)}{RESET}")
    elif node == "loop_guard" and update.get("loop_warning"):
        print(f"{YELLOW}  ⚠ loop guard: {short(update['loop_warning'], 200)}{RESET}")
    elif node == "compact_context" and update.get("summary"):
        n = len(update.get("messages", []))
        print(
            f"{MAGENTA}  ⇢ context compacted: {n} old messages folded into the summary{RESET}"
        )
    elif node == "reflect":
        critique = update.get("critique")
        if critique:
            print(
                f"{MAGENTA}  ✎ critic asked for a revision: {short(critique['feedback'], 200)}{RESET}"
            )
        else:
            print(f"{DIM}  ✓ critic approved the answer{RESET}")
    elif node == "prepare_turn" and update.get("memories"):
        print(f"{DIM}  ⓜ recalled {len(update['memories'])} memory item(s){RESET}")


async def handle_interrupt(payload: dict):
    """Collect a response to an approval or clarification payload.
    The payload shape is the contract between the graph and the user interface.

    收集审批或澄清问题的回答。
    payload 的结构是图与用户界面之间的约定。
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
                choice = (await ask("  [a]pprove / [e]dit args / [r]eject ? ")).lower()[
                    :1
                ]
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
                        new_args = json.loads(raw)
                        if not isinstance(new_args, dict):
                            raise ValueError(
                                "Arguments must be a JSON object / 参数必须是 JSON 对象"
                            )
                        decisions[call["id"]] = {"action": "edit", "args": new_args}
                        break
                    except ValueError as exc:
                        print(f"{RED}  invalid JSON: {exc}{RESET}")
        return {"decisions": decisions}

    print(f"{RED}Unknown interrupt payload: {payload}{RESET}")
    return None


async def run_turn(graph, payload, config: dict, ctx: AgentContext) -> None:
    """Stream until completion or pause; answer interrupts and resume the SAME thread.
    ⚠ PITFALL: Command(resume=...) answers a pending interrupt; a new HumanMessage does not.

    流式运行到完成或暂停；回答中断并恢复同一个会话。
    ⚠ PITFALL：必须用 Command(resume=...) 回答待处理的中断，不能用新 HumanMessage 替代。
    """
    while True:
        async for chunk in graph.astream(
            payload, config, context=ctx, stream_mode="updates"
        ):
            for node, update in chunk.items():
                if node != "__interrupt__":
                    render_update(node, update)
        snapshot = await graph.aget_state(config)
        if snapshot.interrupts:
            payload = await resume_command(snapshot.interrupts)
            continue
        break

    messages = snapshot.values.get("messages", [])
    final = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
    if final is not None and final.content:
        print(f"\n{BOLD}Ledger:{RESET} {final.content}\n")


async def resume_command(interrupts) -> Command:
    """Collect each pending answer by interrupt ID. ToolNode questions use one combined call.

    按 interrupt ID 收集每个待处理回答。ToolNode 的多个问题应合并为一次调用。
    """
    answers = {}
    for pending in interrupts:
        answers[pending.id] = await handle_interrupt(pending.value)
    return Command(resume=answers)


async def resume_pending(graph, config: dict, ctx: AgentContext) -> bool:
    """Resume saved interrupts before new input after startup or a thread switch.

    启动或切换会话后，先恢复持久化中断，再接受新的输入。
    """
    snapshot = await graph.aget_state(config)
    if not snapshot.interrupts:
        return False
    print(
        "Resuming a pending approval or question.\n发现待处理的审批或提问，继续上次会话。"
    )
    await run_turn(graph, await resume_command(snapshot.interrupts), config, ctx)
    return True


async def list_threads(saver: AsyncSqliteSaver) -> list[str]:
    seen: dict[str, None] = {}
    async for cp in saver.alist(None):
        seen.setdefault(cp.config["configurable"]["thread_id"], None)
    return list(seen)


async def handle_command(cmd: str, *, graph, saver, store, session: dict) -> bool:
    """Inspect state, history, memories and tools; return False to quit.

    检查状态、历史、记忆和工具；返回 False 表示退出。
    """
    name, _, arg = cmd.partition(" ")
    config = {
        "configurable": {"thread_id": session["thread_id"]},
        "recursion_limit": settings.recursion_limit,
    }
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
        print(
            f"  messages      : {len(msgs)} (~{count_tokens_approximately(msgs)} tokens, "
            f"budget {settings.context_token_budget})"
        )
        print(
            f"  last turn     : iterations={v.get('iterations', 0)}/{settings.max_iterations}, "
            f"reflections={v.get('reflections', 0)}/{settings.max_reflections}"
        )
        print(f"  summary       : {v.get('summary') or '(none)'}")
    elif name == "/history":
        # 📘 LEARN: each snapshot records a super-step. Its config can support replay or branching
        # with aupdate_state; replaying side-effecting tools needs separate care.
        # 📘 LEARN：每个快照记录一个 super-step，其配置可用于重放或配合 aupdate_state 分支。
        # 重放有副作用的工具需要另外处理。
        async for snap in graph.aget_state_history(config):
            step = snap.metadata.get("step")
            print(
                f"  step {step:>3}  next={list(snap.next) or ['END']}  "
                f"checkpoint={snap.config['configurable']['checkpoint_id'][-8:]}"
            )
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


async def main() -> None:
    """Wire the application: model → MCP tools → SQLite resources → graph → input loop.
    Async context managers close resources cleanly. Each user has their own ledger and
    checkpoints; the shared Store still uses per-user namespaces. Resume with the same user.

    连接应用：模型 → MCP 工具 → SQLite 资源 → 图 → 输入循环。
    异步上下文管理器负责关闭资源。每个用户拥有独立账本与检查点；
    共享 Store 仍按用户命名空间隔离。恢复时需要使用相同用户。
    """
    parser = argparse.ArgumentParser(
        description="Ledger — USD expense agent / 美元记账助手"
    )
    parser.add_argument(
        "--user",
        default="default",
        help="User ID for ledger, checkpoints and memory / 账本、检查点和记忆的用户 ID",
    )
    parser.add_argument(
        "--thread",
        default=None,
        help="Resume a thread under the same user / 恢复同一用户的会话",
    )
    args = parser.parse_args()

    model = get_chat_model()
    # 创建应用数据目录（Path 对象）；后续在这里保存长期记忆 store.sqlite 等数据。
    # parents=True：缺少的上级目录也一起创建；exist_ok=True：目录已存在时不报错。
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    # 根据 --user 的值计算用户专属路径：data_dir / "users" / 用户 ID 的 SHA-256 哈希。
    # 哈希避免用户 ID 中的斜杠影响路径；这里只计算路径，不会创建目录。
    user_dir = user_data_dir(args.user)
    # 创建这个用户的目录，供其账本和会话检查点使用；重复启动时保留已有目录和数据。
    user_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"{BOLD}Ledger{RESET} · USD expense agent / 美元记账助手 · model={settings.model}"
    )

    mcp_tools, report = await load_mcp_tools(user_id=args.user)
    for server, names in report.items():
        print(f"{DIM}  MCP '{server}': {', '.join(names)}{RESET}")
    tools = [*LOCAL_TOOLS, *mcp_tools]

    async with (
        AsyncSqliteSaver.from_conn_string(
            str(user_dir / "checkpoints.sqlite")
        ) as saver,
        AsyncSqliteStore.from_conn_string(
            str(settings.data_dir / "store.sqlite")
        ) as store,
    ):
        await store.setup()
        graph = build_graph(model, tools, checkpointer=saver, store=store)
        session = {
            "thread_id": args.thread or uuid.uuid4().hex[:8],
            "ctx": AgentContext(user_id=args.user),
            "tools": tools,
        }
        print(
            f"{DIM}  thread={session['thread_id']} user={args.user} · /help for commands{RESET}\n"
        )

        while True:
            config = {
                "configurable": {"thread_id": session["thread_id"]},
                "recursion_limit": settings.recursion_limit,
            }
            try:
                await resume_pending(graph, config, session["ctx"])
                text = await ask(f"{BOLD}you>{RESET} ")
            except (EOFError, KeyboardInterrupt):
                break
            except Exception as exc:
                print(
                    f"{RED}Resume failed; the pause is preserved. Restart with the same --user and --thread after fixing the error.\n恢复失败，暂停保留；修复后请使用相同 --user 和 --thread 重启：{exc}{RESET}"
                )
                break
            if not text:
                continue
            if text.startswith("/"):
                if not await handle_command(
                    text, graph=graph, saver=saver, store=store, session=session
                ):
                    break
                continue

            try:
                await run_turn(
                    graph, {"messages": [HumanMessage(text)]}, config, session["ctx"]
                )
            except KeyboardInterrupt:
                print(f"\n{YELLOW}(turn interrupted){RESET}")
            except Exception as exc:
                print(f"{RED}Error: {type(exc).__name__}: {exc}{RESET}")
    print("bye")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
