"""Expose business tools over MCP and enforce policy before executing them."""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from time import monotonic
from typing import Any

import httpx
from mcp import McpError, types
from mcp.server.lowlevel import Server

from ..config import AppConfig
from .mcp_client import RemoteTool
from .schemas import TodoView
from .tools import LOCAL_TOOLS, DeleteRequest, LocalTools, local_definitions

logger = logging.getLogger(__name__)


def result(data: dict[str, Any], *, error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(
        content=[
            types.TextContent(type="text", text=json.dumps(data, ensure_ascii=False))
        ],
        isError=error,
    )


@dataclass(frozen=True)
class PendingCall:
    tool_name: str
    arguments: dict[str, Any]
    preview: dict[str, Any]
    execute: Callable[[], Awaitable[types.CallToolResult]]


@dataclass
class TurnScope:
    thread_id: str
    remaining: int
    pending: list[PendingCall] = field(default_factory=list)


class ToolGateway:
    def __init__(
        self, config: AppConfig, local: LocalTools, remote: dict[str, RemoteTool]
    ) -> None:
        if duplicates := LOCAL_TOOLS.keys() & remote.keys():
            raise ValueError(
                f"MCP names conflict with local tools: {sorted(duplicates)}"
            )
        self.config = config
        self.local = local
        self.remote = remote
        self.scope: TurnScope | None = None
        self.lock = asyncio.Lock()

        self.server = Server("todo")
        self.server.list_tools()(self.list_tools)
        # Validate inside the dispatch boundary so rejected inputs use a tool slot.
        self.server.call_tool(validate_input=False)(self.call)

    async def list_tools(self) -> list[types.Tool]:
        return [
            *local_definitions(),
            *(tool.definition for tool in self.remote.values()),
        ]

    def begin(self, thread_id: str) -> TurnScope:
        if self.scope is not None:
            raise RuntimeError("A tool scope is already open.")
        self.scope = TurnScope(thread_id, self.config.tool_calls_per_turn)
        return self.scope

    async def end(self) -> None:
        # Queued MCP requests must not execute after the turn closes.
        self.scope = None
        async with self.lock:
            pass

    async def call(self, name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        scope = self.scope
        async with self.lock:
            if scope is None or self.scope is not scope:
                return result({"error": "No active user turn."}, error=True)
            if scope.remaining <= 0:
                return result(
                    {"error": "The tool limit for this turn was reached."}, error=True
                )
            scope.remaining -= 1
            started = monotonic()
            try:
                if name == "delete_todo":
                    return self.request_delete(scope, arguments)
                if remote := self.remote.get(name):
                    if remote.require_approval:
                        scope.pending.append(
                            PendingCall(
                                name,
                                arguments,
                                arguments,
                                lambda: self.call_remote(remote, arguments),
                            )
                        )
                        return result({"pending_approval": True})
                    output = await self.call_remote(remote, arguments)
                elif name in LOCAL_TOOLS:
                    data = await self.local.run(scope.thread_id, name, arguments)
                    output = result(data)
                else:
                    output = result({"error": "Unknown tool."}, error=True)
            except ValueError as exc:
                output = result({"error": str(exc)}, error=True)
            self.record(scope.thread_id, name, arguments, output, started)
            return output

    def request_delete(
        self, scope: TurnScope, arguments: dict[str, Any]
    ) -> types.CallToolResult:
        params = DeleteRequest.model_validate(arguments)
        rows = self.local.store.list_todos(params.project, params.date)
        if not rows:
            output = result({"error": "No matching todo."}, error=True)
            self.record(scope.thread_id, "delete_todo", arguments, output, monotonic())
            return output
        todo = TodoView.model_validate(rows[0])

        async def delete() -> types.CallToolResult:
            if not self.local.store.delete(todo):
                return result(
                    {"error": "The todo changed or was already removed."}, error=True
                )
            return result({"deleted": todo.model_dump()})

        scope.pending.append(
            PendingCall("delete_todo", arguments, todo.model_dump(), delete)
        )
        return result({"pending_approval": True, "todo": todo.model_dump()})

    async def call_remote(
        self, remote: RemoteTool, arguments: dict[str, Any]
    ) -> types.CallToolResult:
        try:
            output = await remote.call(arguments)
        except (McpError, OSError, httpx.HTTPError, TimeoutError, RuntimeError):
            return result(
                {"error": "The upstream MCP call did not complete."}, error=True
            )

        # Keep history and terminal previews text-only. Do not forward opaque content.
        data: dict[str, Any] = {
            "content": [block.text for block in output.content if block.type == "text"]
        }
        if output.structuredContent is not None:
            data["structured_content"] = output.structuredContent
        return result(data, error=output.isError)

    async def resolve(
        self, scope: TurnScope, call: PendingCall, *, approved: bool
    ) -> types.CallToolResult:
        if self.scope is not None or not any(
            pending is call for pending in scope.pending
        ):
            raise RuntimeError("Approval requires a pending call from a closed turn.")
        # Remove the request before any external side effect, including on failure.
        scope.pending.remove(call)
        started = monotonic()
        if approved:
            output = await call.execute()
        else:
            output = result({"error": "The user declined this operation."}, error=True)
        self.record(
            scope.thread_id,
            call.tool_name,
            call.arguments,
            output,
            started,
            declined=not approved,
        )
        return output

    def record(
        self,
        thread_id: str,
        name: str,
        arguments: dict[str, Any],
        output: types.CallToolResult,
        started: float,
        *,
        declined: bool = False,
    ) -> None:
        if name == "get_tool_history":
            return
        status = "declined" if declined else "error" if output.isError else "success"
        text = "\n".join(block.text for block in output.content if block.type == "text")
        self.local.store.record(
            thread_id,
            name,
            arguments,
            text,
            status,
            round((monotonic() - started) * 1000),
            self.config.tool_history_limit,
        )
