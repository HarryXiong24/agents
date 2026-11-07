"""Generate structured candidate todos, check requirements, and present one draft."""

import json
from typing import Any

from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import ValidationError

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


class DraftNode:
    """Bind the base model; structured generation is used only for draft requests."""

    def __init__(self, model: BaseChatModel) -> None:
        self._model = model

    def draft(self, state: AgentState) -> dict[str, Any]:
        """Return a checked proposal and one display message without writing todos."""
        message = state["messages"][-1]
        if (
            not isinstance(message, ToolMessage)
            or message.name != "generate_todo_draft"
            or message.status != "success"
        ):
            raise TypeError("Draft generation requires an accepted draft request.")
        request = TodoDraftRequest.model_validate(message.artifact)
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
            return {
                "todo_draft": None,
                "messages": [
                    AIMessage(
                        "Could not create a valid draft. "
                        f"Draft generation did not save any todos. Details: {exc}"
                    )
                ],
            }

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
        # Internal structured data does not become an extra conversational message.
        # The console prints only this one ordinary AIMessage; no second LLM rephrases it.
        return {
            "todo_draft": candidate.model_dump(mode="json"),
            "messages": [AIMessage("\n".join(lines))],
        }
