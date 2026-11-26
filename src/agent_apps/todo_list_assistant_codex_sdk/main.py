"""Compose the console, Codex SDK, and business MCP tools."""

import asyncio
from functools import partial

import httpx
from mcp import McpError
from openai_codex import AsyncCodex
from openai_codex.errors import CodexError

from .agent.gateway import ToolGateway
from .agent.mcp_client import connect_tools
from .agent.runtime import generate_draft, open_thread, runtime_config
from .agent.storage import Store
from .agent.tools import LocalTools
from .agent.transport import serve_tools
from .config import APP_DIR, load_config, prepare_workspace
from .console import chat, select_thread, terminal_text


async def run() -> None:
    settings = load_config()
    prepare_workspace(settings)
    # Listing sessions needs no model request and does not connect upstream servers.
    async with AsyncCodex(runtime_config(settings)) as codex:
        selection = await select_thread(codex, settings)
    if selection is None:
        return

    thread_id, name = selection
    store = Store(settings.data_dir / "todos.sqlite")
    local = LocalTools(store, APP_DIR / "skills", partial(generate_draft, settings))
    async with connect_tools(APP_DIR) as remote:
        gateway = ToolGateway(settings, local, remote)
        async with (
            serve_tools(gateway) as endpoint,
            AsyncCodex(runtime_config(settings, endpoint)) as codex,
        ):
            if settings.api_key:
                await codex.login_api_key(settings.api_key.get_secret_value())
            thread = await open_thread(codex, settings, thread_id=thread_id, name=name)
            # Let MCP task groups exit normally when input was interrupted.
            try:
                await chat(thread, settings, gateway)
            except (KeyboardInterrupt, EOFError):
                print("\nGoodbye.")


def main() -> None:
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, EOFError):
        print("\nGoodbye.")
    except (
        OSError,
        ValueError,
        CodexError,
        McpError,
        httpx.HTTPError,
        ExceptionGroup,
    ) as exc:
        # AnyIO may wrap expected MCP startup errors while closing its task groups.
        expected = (OSError, ValueError, CodexError, McpError, httpx.HTTPError)
        if isinstance(exc, ExceptionGroup):
            failures, unexpected = exc.split(expected)
            if unexpected is not None:
                raise unexpected
            assert failures is not None
            messages = error_messages(failures)
        else:
            messages = [str(exc)]
        print(f"Application failed: {terminal_text(' '.join(messages))}")
        raise SystemExit(1) from None


def error_messages(group: ExceptionGroup) -> list[str]:
    return [
        message
        for cause in group.exceptions
        for message in (
            error_messages(cause) if isinstance(cause, ExceptionGroup) else [str(cause)]
        )
    ]
