import asyncio
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from agent_apps.todo_list_assistant_codex_sdk.agent.gateway import ToolGateway
from agent_apps.todo_list_assistant_codex_sdk.agent.schemas import (
    TodoDraftRequest,
    TodoView,
)
from agent_apps.todo_list_assistant_codex_sdk.agent.storage import Store
from agent_apps.todo_list_assistant_codex_sdk.agent.tools import LocalTools
from agent_apps.todo_list_assistant_codex_sdk.agent.transport import serve_tools
from agent_apps.todo_list_assistant_codex_sdk.config import AppConfig, prepare_workspace


@contextmanager
def mock_model() -> Iterator[tuple[str, list[dict]]]:
    """Serve deterministic Responses events without reaching a model provider."""
    requests: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            if len(requests) == 1:
                # Codex registers local MCP tools as callable functions.
                tools = {
                    (
                        group.get("name") if group.get("type") == "namespace" else None,
                        tool.get("name"),
                    )
                    for group in body["tools"]
                    for tool in group.get("tools", [group])
                }
                matches = [
                    (namespace, name)
                    for namespace, name in tools
                    if name and name.endswith("delete_todo")
                ]
                if not matches:
                    # Fail immediately with the names, without triggering transport retries.
                    self.send_error(
                        400,
                        f"Delete tool missing from {sorted(str(tool) for tool in tools)}",
                    )
                    return
                namespace, name = matches[0]
                item = {
                    "type": "function_call",
                    "id": "fc_mock",
                    "name": name,
                    "namespace": namespace,
                    "call_id": "call_mock",
                    "arguments": json.dumps(
                        {"project": "Python", "date": "2026-12-04"}
                    ),
                    "status": "completed",
                }
            else:
                reply = "Mock result"
                if body.get("text", {}).get("format", {}).get("type") == "json_schema":
                    reply = json.dumps(
                        {
                            "todos": [
                                {
                                    "project": "Python",
                                    "minutes": 30,
                                    "date": "2026-12-04",
                                }
                            ]
                        }
                    )
                item = {
                    "type": "message",
                    "id": "msg_mock",
                    "role": "assistant",
                    "phase": "final_answer",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "text": reply,
                            "annotations": [],
                        }
                    ],
                }

            response = {
                "id": f"resp_{len(requests)}",
                "output": [item],
                "status": "completed",
                "usage": {
                    "input_tokens": 10,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens": 5,
                    "output_tokens_details": {"reasoning_tokens": 0},
                    "total_tokens": 15,
                },
            }
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for event in [
                {"type": "response.output_item.done", "output_index": 0, "item": item},
                {"type": "response.completed", "response": response},
            ]:
                self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())

        def log_message(self, format: str, *args: object) -> None:
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/v1", requests
        finally:
            server.shutdown()
            worker.join()


@pytest.mark.skipif(
    os.environ.get("TODO_TEST_CODEX_RUNTIME") != "1",
    reason="Requires loopback bind and permission to launch the local Codex runtime",
)
# The pinned SDK's subprocess shutdown leaves its two reader pipes unclosed.
@pytest.mark.filterwarnings("ignore:unclosed file <_io.TextIOWrapper:ResourceWarning")
def test_real_sdk_and_mcp_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("openai_codex")
    from openai_codex import AsyncCodex, ExternalMessage

    from agent_apps.todo_list_assistant_codex_sdk.agent.runtime import (
        chat_input,
        generate_draft,
        open_thread,
        run_turn,
        runtime_config,
    )

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CODEX_API_KEY", raising=False)

    async def draft(request: TodoDraftRequest):
        return await generate_draft(settings, request)

    async def scenario(base_url: str, requests: list[dict]) -> None:
        store = Store(tmp_path / "todos.sqlite")
        store.save(TodoView(project="Python", minutes=30, date="2026-12-04"))
        gateway = ToolGateway(settings, LocalTools(store, tmp_path, draft), {})
        async with serve_tools(gateway) as endpoint:
            url, token = endpoint
            async with httpx.AsyncClient(trust_env=False) as unauthenticated:
                assert (await unauthenticated.post(url)).status_code == 401
            async with (
                httpx.AsyncClient(
                    headers={"Authorization": f"Bearer {token}"}, trust_env=False
                ) as client,
                streamable_http_client(url, http_client=client) as (read, write, _),
            ):
                async with ClientSession(read, write) as mcp:
                    await mcp.initialize()
                    assert "delete_todo" in {
                        tool.name for tool in (await mcp.list_tools()).tools
                    }
                    gateway.begin("test")
                    assert not (await mcp.call_tool("get_current_time")).isError
                    await gateway.end()

            config = runtime_config(settings, endpoint)
            config.config_overrides += (f"openai_base_url={json.dumps(base_url)}",)
            async with AsyncCodex(config) as codex:
                assert not (await codex.thread_list()).data
                await codex.login_api_key("offline-test-key")
                thread = await open_thread(
                    codex, settings, thread_id=None, name="Smoke"
                )
                scope = gateway.begin(thread.id)
                events: list[str] = []
                try:
                    assert (
                        await run_turn(thread, "Delete Python.", 20, events.append)
                        == "Mock result"
                    )
                finally:
                    await gateway.end()
                assert scope.remaining == settings.tool_calls_per_turn - 1
                assert events == ["Tool: delete_todo (completed)"]
                assert store.list_todos(None, None)
                assert len(requests) == 2
                output = await gateway.resolve(scope, scope.pending[0], approved=True)
                assert not output.isError and store.list_todos(None, None) == []
                assert store.history(thread.id)[0]["tool_name"] == "delete_todo"
                block = output.content[0]
                assert block.type == "text"
                receipt = ExternalMessage(
                    tool_name="console_approval", content=block.text
                )
                assert (
                    await run_turn(thread, receipt, 20, events.append) == "Mock result"
                )
                assert len(requests) == 3

            async with AsyncCodex(config) as reopened:
                page = await reopened.thread_list()
                assert [(entry.id, entry.name) for entry in page.data] == [
                    (thread.id, "Smoke")
                ]
                resumed = await open_thread(
                    reopened, settings, thread_id=thread.id, name="Smoke"
                )
                assert resumed.id == thread.id
                assert (await resumed.read(include_turns=True)).thread.turns
                skill = chat_input("$study-plan Plan Python.", settings.workspace)
                assert (
                    await run_turn(resumed, skill, 20, lambda _: None) == "Mock result"
                )
                assert "Split the goal into distinct" in json.dumps(
                    requests[-1]["input"]
                )

            draft_config = runtime_config(settings)
            draft_config.config_overrides += (
                f"openai_base_url={json.dumps(base_url)}",
            )
            request = TodoDraftRequest(
                projects=["Python"], date="2026-12-04", max_minutes=45
            )
            with patch(
                "agent_apps.todo_list_assistant_codex_sdk.agent.runtime.runtime_config",
                return_value=draft_config,
            ):
                candidate = await generate_draft(settings, request)
            assert candidate.todos == [
                TodoView(project="Python", minutes=30, date="2026-12-04")
            ]
            assert requests[-1]["text"]["format"]["type"] == "json_schema"
            assert not any(
                tool.get("name") == "mcp__todo" for tool in requests[-1]["tools"]
            )

    settings = AppConfig(tmp_path, model="gpt-5.4")
    prepare_workspace(settings)
    with mock_model() as (base_url, requests):
        asyncio.run(scenario(base_url, requests))
