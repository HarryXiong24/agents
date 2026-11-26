"""Serve the private MCP endpoint used by this console's Codex runtime."""

import asyncio
import secrets
import socket
from collections.abc import AsyncIterator, Generator
from contextlib import asynccontextmanager, contextmanager

import uvicorn
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Mount
from starlette.types import Receive, Scope, Send

from .gateway import ToolGateway


class EmbeddedServer(uvicorn.Server):
    @contextmanager
    def capture_signals(self) -> Generator[None]:
        # asyncio.run and the console own Ctrl-C for the whole application.
        yield


@asynccontextmanager
async def serve_tools(gateway: ToolGateway) -> AsyncIterator[tuple[str, str]]:
    token = secrets.token_urlsafe(32)
    manager = StreamableHTTPSessionManager(
        gateway.server, json_response=True, stateless=True
    )

    async def dispatch(scope: Scope, receive: Receive, send: Send) -> None:
        headers = dict(scope["headers"])
        supplied = headers.get(b"authorization", b"")
        if not secrets.compare_digest(supplied, f"Bearer {token}".encode()):
            await PlainTextResponse("Unauthorized", status_code=401)(
                scope, receive, send
            )
            return
        await manager.handle_request(scope, receive, send)

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with manager.run():
            yield

    app = Starlette(routes=[Mount("/mcp", app=dispatch)], lifespan=lifespan)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = EmbeddedServer(
            uvicorn.Config(
                app,
                access_log=False,
                log_level="warning",
                timeout_graceful_shutdown=5,
                ws="none",
            )
        )
        task = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(5):
                while not server.started:
                    if task.done():
                        await task
                        raise RuntimeError("The local MCP server failed to start.")
                    await asyncio.sleep(0.01)
            yield f"http://127.0.0.1:{port}/mcp/", token
        finally:
            server.should_exit = True
            await task
