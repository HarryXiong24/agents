import asyncio
import json
from pathlib import Path

from agent_apps.todo_list_assistant_codex_sdk.agent.gateway import ToolGateway
from agent_apps.todo_list_assistant_codex_sdk.agent.schemas import (
    TodoDraft,
    TodoDraftRequest,
    TodoView,
)
from agent_apps.todo_list_assistant_codex_sdk.agent.storage import Store
from agent_apps.todo_list_assistant_codex_sdk.agent.tools import LocalTools
from agent_apps.todo_list_assistant_codex_sdk.config import AppConfig

TODO = {"project": "Python", "minutes": 30, "date": "2026-12-04"}


def test_pending_delete_quota_and_history(tmp_path: Path) -> None:
    async def no_draft(_: TodoDraftRequest) -> TodoDraft:
        raise AssertionError("Unexpected draft")

    async def scenario() -> None:
        settings = AppConfig(tmp_path, tool_calls_per_turn=2, tool_history_limit=3)
        store = Store(tmp_path / "todos.sqlite")
        gateway = ToolGateway(settings, LocalTools(store, tmp_path, no_draft), {})
        scope = gateway.begin("thread")
        assert (await gateway.call("save_todo", TODO)).isError is False
        key = {"project": TODO["project"], "date": TODO["date"]}
        assert (await gateway.call("delete_todo", key)).isError is False
        assert store.list_todos(None, None) == [TODO]
        assert (await gateway.call("save_todo", {**TODO, "minutes": 45})).isError
        await gateway.end()
        assert (await gateway.call("save_todo", TODO)).isError

        await gateway.resolve(scope, scope.pending[0], approved=False)
        assert store.list_todos(None, None) == [TODO]
        scope = gateway.begin("thread")
        await gateway.call("delete_todo", key)
        await gateway.end()
        await gateway.resolve(scope, scope.pending[0], approved=True)
        assert store.list_todos(None, None) == []
        assert [entry["status"] for entry in store.history("thread")] == [
            "success",
            "declined",
            "success",
        ]
        assert store.history("another-thread") == []

    asyncio.run(scenario())


def test_draft_isolated_validated_and_replaced(tmp_path: Path) -> None:
    async def draft(_: TodoDraftRequest) -> TodoDraft:
        return TodoDraft(todos=[TodoView.model_validate(TODO)])

    async def scenario() -> None:
        settings = AppConfig(tmp_path)
        store = Store(tmp_path / "todos.sqlite")
        gateway = ToolGateway(settings, LocalTools(store, tmp_path, draft), {})
        gateway.begin("draft-thread")
        request = {"projects": ["Python"], "date": TODO["date"], "max_minutes": 35}
        generated = await gateway.call("generate_todo_draft", request)
        assert not generated.isError
        assert store.get_draft("other-thread") is None
        assert store.list_todos(None, None) == []
        assert store.get_draft("draft-thread") == TodoDraft(
            todos=[TodoView.model_validate(TODO)]
        )
        result = await gateway.call(
            "generate_todo_draft", {**request, "max_minutes": 20}
        )
        block = result.content[0]
        assert block.type == "text" and "exceeds" in json.loads(block.text)["error"]
        assert store.get_draft("draft-thread") is None
        await gateway.end()

    asyncio.run(scenario())
