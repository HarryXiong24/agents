"""Generate, validate, and return unsaved proposals through the draft tool."""

import json
from typing import Any

from langchain.tools import ToolRuntime
from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool, tool
from langgraph.types import Command
from pydantic import StrictInt, ValidationError

from ..errors import InputValueError
from ..prompts import DRAFT_PROMPT
from ..schemas import TodoDraft, TodoDraftRequest
from ..state import AgentState


def validate_draft(draft: TodoDraft, request: TodoDraftRequest) -> None:
    """Check user requirements after Pydantic has checked each record's structure."""
    names = [todo.project for todo in draft.todos]
    if len(names) != len(request.projects) or set(names) != set(request.projects):
        raise ValueError("The draft must contain each requested task exactly once.")
    if any(todo.date != request.date for todo in draft.todos):
        raise ValueError("Every todo must use the requested date.")
    total = sum(todo.minutes for todo in draft.todos)
    if total > request.max_minutes:
        raise ValueError(
            f"The draft totals {total} minutes, exceeding the {request.max_minutes}-minute budget."
        )


class DraftGenerator:
    """Bind the base model; structured generation is used only for draft requests."""

    def __init__(self, model: BaseChatModel) -> None:
        self._model = model

    def generate(self, request: TodoDraftRequest) -> tuple[dict[str, Any] | None, str]:
        """Generate and validate a proposal; return plain State data and display text."""
        try:
            # JSON mode asks the provider for a JSON object. The prompt supplies
            # its schema; Pydantic validates it locally. Native strict-schema
            # support is not required, and ordinary chat never uses this wrapper.
            structured_model = self._model.with_structured_output(
                TodoDraft, method="json_mode", include_raw=True
            )
            result = structured_model.invoke(
                [
                    SystemMessage(
                        DRAFT_PROMPT
                        + "\n\nJSON Schema:\n"
                        + json.dumps(TodoDraft.model_json_schema(), ensure_ascii=False)
                    ),
                    HumanMessage(request.model_dump_json()),
                ]
            )
            if not isinstance(result, dict):
                raise ValueError("The draft wrapper did not return its parsing result.")
            raw = result["raw"]
            if (
                not isinstance(raw, AIMessage)
                or raw.tool_calls
                or raw.invalid_tool_calls
                or raw.response_metadata.get("finish_reason")
                in {"length", "max_tokens", "content_filter"}
            ):
                raise ValueError("The draft model returned an incomplete response.")
            if result["parsing_error"] is not None:
                raise ValueError("The model output did not match the TodoDraft schema.")
            candidate = TodoDraft.model_validate(result["parsed"])
            validate_draft(candidate, request)
        except (OutputParserException, ValidationError, ValueError) as exc:
            # No automatic retry or partial proposal: failed candidates cannot
            # replace the cleared draft or be presented as approved records.
            return None, (
                "Could not create a valid draft. "
                f"Draft generation did not save any todos. Details: {exc}"
            )

        lines = [f"Todo draft for {request.date}:"]
        for todo in candidate.todos:
            lines.append(f"- {todo.project}: {todo.minutes} minutes")
        total = sum(todo.minutes for todo in candidate.todos)
        lines.extend(
            [
                f"Total: {total} / {request.max_minutes} minutes.",
                "Not saved. Ask to save this draft if you want to keep it.",
            ]
        )
        return candidate.model_dump(mode="json"), "\n".join(lines)


def create_draft_tool(model: BaseChatModel) -> BaseTool:
    """Bind the base model and return the graph-aware draft tool."""
    generator = DraftGenerator(model)

    @tool(return_direct=True)
    def generate_todo_draft(
        projects: list[str],
        date: str,
        max_minutes: StrictInt,
        runtime: ToolRuntime[None, AgentState],
    ) -> Command:
        """Propose an unsaved arrangement for named tasks on one date within a budget.

        Copy distinct task names, date and total minutes from the user's request.
        Ask for missing requirements. Resolve relative dates with the time tool first.
        Budget is 1 to 1440 minutes and must allow one minute per task.
        Call this tool alone. It generates and checks a draft, ends the turn with
        one displayed proposal, and never writes todos. A later explicit request
        may use save_todo to save each proposed record.
        """
        request = TodoDraftRequest(
            projects=projects, date=date, max_minutes=max_minutes
        )
        if len(projects) > max_minutes:
            raise InputValueError("The budget must allow at least one minute per task.")
        candidate, reply = generator.generate(request)
        # ToolRuntime supplies the call ID. Command updates State while completing
        # this exact tool request; return_direct skips a second conversational LLM.
        return Command(
            update={
                "todo_draft": candidate,
                "draft_reply": reply,
                "messages": [
                    ToolMessage(
                        content=json.dumps(candidate, ensure_ascii=False)
                        if candidate
                        else reply,
                        tool_call_id=runtime.tool_call_id,
                        name="generate_todo_draft",
                        status="success" if candidate else "error",
                    )
                ],
            }
        )

    return generate_todo_draft
