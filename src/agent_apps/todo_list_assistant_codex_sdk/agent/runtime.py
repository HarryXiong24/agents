"""Run Codex threads and translate their events for the console."""

import asyncio
import json
from collections.abc import Callable
from pathlib import Path

from openai_codex import (
    ApprovalMode,
    AsyncCodex,
    AsyncThread,
    CodexConfig,
    RunInput,
    Sandbox,
    SkillInput,
    TextInput,
)
from openai_codex.errors import CodexError
from openai_codex.generated.v2_all import MessagePhase
from openai_codex.models import ItemCompletedNotification, TurnCompletedNotification
from openai_codex.types import TurnStatus

from ..config import AppConfig
from .schemas import TodoDraft, TodoDraftRequest

PROMPTS = Path(__file__).parent / "prompt_templates"


def runtime_config(
    settings: AppConfig, endpoint: tuple[str, str] | None = None
) -> CodexConfig:
    overrides = [
        "features.shell_tool=false",
        "features.skill_mcp_dependency_install=false",
        "features.apps=false",
        "features.plugins=false",
        "features.hooks=false",
        "features.view_image=false",
        'web_search="disabled"',
        "project_root_markers=[]",
        "project_doc_max_bytes=0",
    ]
    if endpoint:
        url, token = endpoint
        overrides += [
            f"mcp_servers.todo.url={json.dumps(url)}",
            f"mcp_servers.todo.http_headers.Authorization={json.dumps(f'Bearer {token}')}",
            "mcp_servers.todo.required=true",
            # The private gateway enforces business approval before forwarding writes.
            'mcp_servers.todo.default_tools_approval_mode="approve"',
            f"mcp_servers.todo.tool_timeout_sec={settings.turn_timeout_seconds}",
        ]
    return CodexConfig(
        config_overrides=tuple(overrides),
        cwd=str(settings.workspace),
        env={"CODEX_HOME": str(settings.codex_home)},
    )


async def open_thread(
    codex: AsyncCodex, settings: AppConfig, *, thread_id: str | None, name: str
) -> AsyncThread:
    instructions = (PROMPTS / "assistant.md").read_text(encoding="utf-8")
    if thread_id is not None:
        return await codex.thread_resume(
            thread_id,
            approval_mode=ApprovalMode.deny_all,
            developer_instructions=instructions,
            include_turns=False,
            sandbox=Sandbox.read_only,
            cwd=str(settings.workspace),
        )
    thread = await codex.thread_start(
        approval_mode=ApprovalMode.deny_all,
        developer_instructions=instructions,
        sandbox=Sandbox.read_only,
        cwd=str(settings.workspace),
        model=settings.model,
    )
    await thread.set_name(name)
    return thread


def chat_input(text: str, workspace: Path) -> RunInput:
    # Explicit native invocation injects the skill body even with shell tools disabled.
    first_word = text.split(maxsplit=1)[0]
    if first_word not in {"$study-plan", "$todo-cleanup"}:
        return text
    name = first_word[1:]
    path = workspace / ".agents" / "skills" / name / "SKILL.md"
    return [TextInput(text), SkillInput(name, str(path))]


async def run_turn(
    thread: AsyncThread,
    text: RunInput,
    timeout: float,
    observe: Callable[[str], None],
) -> str:
    handle = None
    final = ""
    status = None
    try:
        async with asyncio.timeout(timeout):
            handle = await thread.turn(text)
            async for event in handle.stream():
                if isinstance(event.payload, ItemCompletedNotification):
                    item = event.payload.item.root
                    if item.type == "mcpToolCall":
                        observe(f"Tool: {item.tool} ({item.status.value})")
                    if item.type == "agentMessage" and item.phase in (
                        None,
                        MessagePhase.final_answer,
                    ):
                        final = item.text
                if isinstance(event.payload, TurnCompletedNotification):
                    status = event.payload.turn.status
    except TimeoutError as exc:
        if handle is not None:
            try:
                async with asyncio.timeout(3):
                    await handle.interrupt()
            except (TimeoutError, CodexError):
                # The caller closes the runtime after an unsuccessful turn.
                pass
        raise TurnFailed("Codex turn timed out.") from exc
    if status is None:
        raise TurnFailed("Codex closed the event stream before completing the turn.")
    if status != TurnStatus.completed:
        raise TurnFailed(f"Codex turn ended with status {status.value}.")
    return final


class TurnFailed(RuntimeError):
    """A turn ended unsuccessfully; its business writes may already be committed."""


async def generate_draft(settings: AppConfig, request: TodoDraftRequest) -> TodoDraft:
    try:
        async with asyncio.timeout(settings.draft_timeout_seconds):
            # A separate ephemeral thread keeps the schema out of ordinary chat.
            async with AsyncCodex(runtime_config(settings)) as codex:
                thread = await codex.thread_start(
                    ephemeral=True,
                    approval_mode=ApprovalMode.deny_all,
                    sandbox=Sandbox.read_only,
                    model=settings.model,
                    developer_instructions=(PROMPTS / "draft.md").read_text(
                        encoding="utf-8"
                    ),
                )
                response = await thread.run(
                    request.model_dump_json(),
                    output_schema=TodoDraft.model_json_schema(),
                )
    except TimeoutError as exc:
        raise ValueError("Draft generation timed out.") from exc
    except (RuntimeError, CodexError) as exc:
        raise ValueError("Codex could not generate the draft.") from exc
    if response.status != TurnStatus.completed or not response.final_response:
        raise ValueError("Codex did not complete the draft generation.")
    return TodoDraft.model_validate_json(response.final_response)
