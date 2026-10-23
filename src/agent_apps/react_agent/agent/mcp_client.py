"""Load tools from MCP servers declared in mcp_servers.json.

📘 LEARN — MCP (Model Context Protocol) in one picture:

    ┌──────── this process (MCP *client*) ────────┐        ┌──── separate process ────┐
    │ LangGraph  ──▶ BaseTool (adapter) ──▶ MCP   │ stdio  │ MCP *server*             │
    │                                     session ├───────▶│  tools/list  → schemas   │
    │                                             │JSON-RPC│  tools/call  → run tool  │
    └─────────────────────────────────────────────┘        └──────────────────────────┘

    1. Client spawns the server (stdio) or connects to it (HTTP).
    2. `initialize` handshake, then `tools/list` returns each tool's name, description
       and JSON-Schema for its inputs.
    3. langchain-mcp-adapters wraps each one as a LangChain BaseTool whose `ainvoke`
       sends `tools/call` to the server.
    4. bind_tools() turns those BaseTools into function-calling schemas for the chat model.

    So MCP is a *standard way to serve tools*; it sits on top of function calling, it does
    not replace it. The model never knows a tool came from MCP.

📘 LEARN — transports:
    stdio            : client launches the server as a subprocess; messages over stdin/stdout.
                       Best for local tools. (used here)
    streamable_http  : server runs independently at a URL; many clients can share it.
    sse / websocket  : older / alternative remote transports.
"""

from __future__ import annotations

import json
import sys

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from mcp.client.stdio import get_default_environment

from .config import ROOT, settings


def _expand(value):
    """Substitute ${PYTHON} and ${ROOT} placeholders so the JSON config is portable
    (works in any venv and from any working directory)."""
    if isinstance(value, str):
        return value.replace("${PYTHON}", sys.executable).replace("${ROOT}", str(ROOT))
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    return value


def load_connections() -> dict:
    if not settings.mcp_config.exists():
        return {}
    conns = _expand(json.loads(settings.mcp_config.read_text()))
    for conn in conns.values():
        if conn.get("transport") == "stdio":
            # ⚠ PITFALL: when you pass `env` to an MCP stdio server, it REPLACES the whole
            # environment — no PATH, no HOME. Commands like `npx`/`uvx` then fail with
            # "not found". Merge with MCP's safe default environment instead.
            conn["env"] = {**get_default_environment(), **conn.get("env", {})}
    return conns


async def load_mcp_tools() -> tuple[list[BaseTool], dict[str, list[str]]]:
    """Return (tools, {server_name: [tool names]}). A failing server is skipped, not fatal.

    📘 LEARN: we connect to each server separately so one broken server (missing binary,
    crash on start) doesn't take down the agent — graceful degradation. Tool calls later
    open a short-lived session per call (the adapter's default), so no connection has to
    be kept alive for the whole REPL session.
    """
    tools: list[BaseTool] = []
    report: dict[str, list[str]] = {}
    for name, conn in load_connections().items():
        try:
            server_tools = await MultiServerMCPClient({name: conn}).get_tools()
        except Exception as exc:  # noqa: BLE001 - surface any startup failure
            print(f"  ! MCP server '{name}' failed to start: {exc}", file=sys.stderr)
            continue
        tools.extend(server_tools)
        report[name] = [t.name for t in server_tools]
    return tools, report


if __name__ == "__main__":  # 🧪 TRY: python -m agent.mcp_client
    import asyncio

    _, rep = asyncio.run(load_mcp_tools())
    print(json.dumps(rep, indent=2))
