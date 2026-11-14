"""Validate a draft request and pass its constraints to the graph's draft node."""

from typing import Any

from langchain_core.tools import tool

from ..errors import InputValueError
from ..schemas import TodoDraftRequest


@tool(args_schema=TodoDraftRequest, response_format="content_and_artifact")
def generate_todo_draft(
    projects: list[str], date: str, max_minutes: int
) -> tuple[str, dict[str, Any]]:
    """Request an unsaved arrangement for named tasks on one date within a time budget.

    Use when the user wants proposed durations or an arrangement draft, not saving.
    Copy distinct task names, date and total time limit from the user's requirements;
    ask if any are missing. Resolve relative dates with the time tool first.
    max_minutes is the total budget for this draft, from 1 to 1440 minutes.
    Call this tool alone in its batch. The graph's draft node generates and checks
    the proposal next, then ends the turn with one displayed draft. Nothing is saved
    to the todo database. A later explicit save request can use save_todo.
    """
    request = TodoDraftRequest(projects=projects, date=date, max_minutes=max_minutes)
    if len(request.projects) > request.max_minutes:
        raise InputValueError("The budget must allow at least one minute per task.")
    return (
        "Draft request accepted. The draft node will generate and validate it. This request does not save any todos.",
        request.model_dump(mode="json"),
    )
