"""Connect optional upstream MCP servers and expose their selected tools."""

import re
import sys
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Literal

import httpx
from dotenv import dotenv_values
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from pydantic import BaseModel, ConfigDict, Field


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tools: list[str] | None = None
    timeout: Annotated[int, Field(ge=1, le=120)] = 30
    require_approval: bool = True


class StdioConfig(ServerConfig):
    transport: Literal["stdio"]
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None


class HttpConfig(ServerConfig):
    transport: Literal["streamable_http"]
    url: str
    headers: dict[str, str] = Field(default_factory=dict)


class McpConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    mcpServers: dict[
        str, Annotated[StdioConfig | HttpConfig, Field(discriminator="transport")]
    ]


@dataclass(frozen=True)
class RemoteTool:
    definition: types.Tool
    remote_name: str
    session: ClientSession
    timeout: timedelta
    require_approval: bool

    async def call(self, arguments: dict) -> types.CallToolResult:
        return await self.session.call_tool(
            self.remote_name, arguments, read_timeout_seconds=self.timeout
        )


@asynccontextmanager
async def connect_tools(app_dir: Path) -> AsyncIterator[dict[str, RemoteTool]]:
    """Keep upstream sessions open in the same task for the lifetime of the console."""
    path = app_dir / "mcp.json"
    if not path.is_file():
        yield {}
        return

    config = McpConfig.model_validate_json(path.read_text(encoding="utf-8"))
    env = dotenv_values(app_dir / ".env", interpolate=False)

    def expand(value: str) -> str:
        def replace(match: re.Match[str]) -> str:
            name = match[1]
            if (resolved := env.get(name)) is None:
                raise ValueError(f"Missing local MCP setting: {name}")
            return resolved

        return re.sub(r"\$\{([A-Za-z_]\w*)\}", replace, value)

    async with AsyncExitStack() as stack:
        tools: dict[str, RemoteTool] = {}
        for server_name, settings in config.mcpServers.items():
            timeout = timedelta(seconds=settings.timeout)
            if isinstance(settings, StdioConfig):
                command = expand(settings.command)
                params = StdioServerParameters(
                    command=sys.executable if command == "python" else command,
                    args=[expand(arg) for arg in settings.args],
                    cwd=app_dir / expand(settings.cwd) if settings.cwd else app_dir,
                    env={key: expand(value) for key, value in settings.env.items()},
                )
                read, write = await stack.enter_async_context(stdio_client(params))
            else:
                client = await stack.enter_async_context(
                    httpx.AsyncClient(
                        headers={
                            key: expand(value)
                            for key, value in settings.headers.items()
                        },
                        timeout=settings.timeout,
                        trust_env=False,
                    )
                )
                read, write, _ = await stack.enter_async_context(
                    streamable_http_client(expand(settings.url), http_client=client)
                )

            session = await stack.enter_async_context(
                ClientSession(read, write, timeout)
            )
            await session.initialize()
            cursor = None
            found: set[str] = set()
            for _ in range(100):
                page = await session.list_tools(cursor)
                for tool in page.tools:
                    if settings.tools is not None and tool.name not in settings.tools:
                        continue
                    name = f"{server_name}_{tool.name}"
                    if not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", name) or name in tools:
                        raise ValueError(
                            f"Invalid or duplicate MCP tool name: {name!r}"
                        )
                    found.add(tool.name)
                    tools[name] = RemoteTool(
                        # The gateway returns its own text envelope, including approval receipts.
                        tool.model_copy(update={"name": name, "outputSchema": None}),
                        tool.name,
                        session,
                        timeout,
                        settings.require_approval,
                    )
                cursor = page.nextCursor
                if not cursor:
                    break
            else:
                raise ValueError(
                    f"Too many tool pages from MCP server {server_name!r}."
                )
            if settings.tools is not None and set(settings.tools) - found:
                raise ValueError(
                    f"Configured tool missing from MCP server {server_name!r}."
                )
        yield tools
