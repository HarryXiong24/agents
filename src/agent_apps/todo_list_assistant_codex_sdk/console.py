"""Select a Codex thread, chat, and collect explicit tool approvals."""

import json
import readline
import signal

from openai_codex import AsyncCodex, AsyncThread, ExternalMessage
from openai_codex.errors import CodexError
from openai_codex.generated.v2_all import ThreadListCwdFilter

from .agent.gateway import ToolGateway
from .agent.runtime import TurnFailed, chat_input, run_turn
from .config import AppConfig


def terminal_text(text: str) -> str:
    """Prevent tool or assistant text from emitting terminal control sequences."""
    return "".join(char for char in text if char.isprintable() or char in "\n\t")


def read_prompt(prompt: str) -> str:
    """Let Ctrl-C interrupt terminal input immediately, even inside asyncio.run."""
    old_handler = signal.signal(signal.SIGINT, signal.default_int_handler)
    try:
        return input(prompt).strip()
    finally:
        signal.signal(signal.SIGINT, old_handler)


async def select_thread(
    codex: AsyncCodex, settings: AppConfig
) -> tuple[str | None, str] | None:
    threads: list[tuple[str, str]] = []
    cursor = None
    while True:
        page = await codex.thread_list(
            cwd=ThreadListCwdFilter(str(settings.workspace)), cursor=cursor
        )
        threads.extend(
            (thread.id, thread.name or thread.preview or thread.id)
            for thread in page.data
            if thread.cwd == str(settings.workspace) and not thread.ephemeral
        )
        cursor = page.next_cursor
        if cursor is None:
            break

    print("Todo List Assistant — Codex SDK\n")
    readline.set_auto_history(False)
    print("0. New conversation")
    for index, (_, label) in enumerate(threads, start=1):
        print(f"{index}. {terminal_text(label).replace(chr(10), ' ')}")
    while True:
        choice = read_prompt("Conversation (or exit): ")
        if choice.lower() in {"exit", "quit"}:
            return None
        if choice == "0":
            return None, read_prompt("Conversation name: ") or "Todo conversation"
        if (
            choice.isascii()
            and choice.isdecimal()
            and len(choice) <= len(str(len(threads)))
        ):
            index = int(choice)
            if 1 <= index <= len(threads):
                return threads[index - 1]
        print("Choose one of the listed numbers.")


async def chat(thread: AsyncThread, settings: AppConfig, gateway: ToolGateway) -> None:
    while True:
        text = read_prompt("You: ")
        if text.lower() in {"exit", "quit"}:
            return
        if not text:
            continue

        scope = gateway.begin(thread.id)
        try:
            try:
                reply = await run_turn(
                    thread,
                    chat_input(text, settings.workspace),
                    settings.turn_timeout_seconds,
                    print,
                )
            finally:
                await gateway.end()

            if reply:
                print(f"Assistant: {terminal_text(reply)}\n")
            if scope.pending:
                outcomes = []
                for call in list(scope.pending):
                    preview = json.dumps(call.preview, ensure_ascii=False)
                    print(f"Approval: {call.tool_name} {terminal_text(preview)}")
                    decision = read_prompt("Execute this operation? [y/N] ").lower()
                    if decision in {"exit", "quit"}:
                        return
                    approved = decision == "y"
                    output = await gateway.resolve(scope, call, approved=approved)
                    outcome = {
                        "tool": call.tool_name,
                        "result": [
                            block.text
                            for block in output.content
                            if block.type == "text"
                        ],
                    }
                    print(terminal_text(json.dumps(outcome, ensure_ascii=False)))
                    outcomes.append(outcome)
                # The tool scope stays closed in this second turn. Tool output is data.
                reply = await run_turn(
                    thread,
                    ExternalMessage(
                        tool_name="console_approval", content=json.dumps(outcomes)
                    ),
                    settings.turn_timeout_seconds,
                    print,
                )
                if reply:
                    print(f"Assistant: {terminal_text(reply)}\n")
        except (CodexError, TurnFailed) as exc:
            print(
                f"Turn failed. Pending approvals were discarded. {terminal_text(str(exc))}"
            )
            print("Reopen the conversation from the menu to continue.")
            return
