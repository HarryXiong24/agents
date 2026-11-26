"""Validate and run the local todo tools independently of the agent runtime."""

import math
from collections.abc import Awaitable, Callable
from datetime import date as calendar_date
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp import types
from pydantic import AfterValidator, BaseModel, ConfigDict

from .schemas import TodoDraft, TodoDraftRequest, TodoView
from .storage import Store


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def normalize_project(project: str) -> str:
    if not project.strip():
        raise ValueError("The todo name must not be blank.")
    return project.strip()


def check_date(value: str) -> str:
    if calendar_date.fromisoformat(value).isoformat() != value:
        raise ValueError("The date must use YYYY-MM-DD format.")
    return value


Project = Annotated[str, AfterValidator(normalize_project)]
CanonicalDate = Annotated[str, AfterValidator(check_date)]


class TodoFilter(ToolInput):
    project: Project | None = None
    date: CanonicalDate | None = None


class DeleteRequest(ToolInput):
    project: Project
    date: CanonicalDate


class Calculation(ToolInput):
    a: float
    b: float
    operation: Literal["add", "subtract", "multiply", "divide"]


class SkillFile(ToolInput):
    name: Literal["study-plan", "todo-cleanup"]
    path: Literal["SKILL.md", "references/session-guide.md"]


LOCAL_TOOLS: dict[str, tuple[type[BaseModel], str]] = {
    "save_todo": (
        TodoView,
        "Save a todo only at the user's explicit request. Same name and date updates its duration.",
    ),
    "list_todos": (
        TodoFilter,
        "List saved todos, optionally filtering by exact name and/or date.",
    ),
    "delete_todo": (
        DeleteRequest,
        "Request console approval to delete a saved todo by its exact name and date.",
    ),
    "get_current_time": (
        ToolInput,
        "Read the current local date and time, including the UTC offset.",
    ),
    "calculate": (
        Calculation,
        "Perform one arithmetic operation on two finite numbers.",
    ),
    "generate_todo_draft": (
        TodoDraftRequest,
        "Generate an unsaved arrangement for distinct projects on one date within max_minutes.",
    ),
    "get_todo_draft": (
        ToolInput,
        "Read this conversation's latest validated but unsaved arrangement.",
    ),
    "get_tool_history": (
        ToolInput,
        "Read recent tool names, arguments, outcomes, timestamps and durations for this conversation.",
    ),
    "read_skill_file": (
        SkillFile,
        "Read the shipped study-plan or todo-cleanup instructions or the study-plan session guide.",
    ),
}


def local_definitions() -> list[types.Tool]:
    return [
        types.Tool(
            name=name, description=description, inputSchema=schema.model_json_schema()
        )
        for name, (schema, description) in LOCAL_TOOLS.items()
    ]


DraftGenerator = Callable[[TodoDraftRequest], Awaitable[TodoDraft]]


class LocalTools:
    def __init__(self, store: Store, skills: Path, generate_draft: DraftGenerator):
        self.store = store
        self.skills = skills
        self.generate_draft = generate_draft

    async def run(self, thread_id: str, name: str, arguments: dict[str, Any]) -> Any:
        # Only the gateway accepts a delete request. It previews the exact record first.
        schema, _ = LOCAL_TOOLS[name]
        if name == "generate_todo_draft":
            self.store.set_draft(thread_id, None)
        params = schema.model_validate(arguments)

        match name, params:
            case "save_todo", TodoView():
                todo = params.model_copy(update={"project": params.project.strip()})
                self.store.save(todo)
                return {"saved": todo.model_dump()}
            case "list_todos", TodoFilter():
                return {"todos": self.store.list_todos(params.project, params.date)}
            case "get_current_time", _:
                return {"local_time": datetime.now().astimezone().isoformat()}
            case "calculate", Calculation():
                return {"result": calculate(params)}
            case "get_todo_draft", _:
                draft = self.store.get_draft(thread_id)
                return {"draft": draft.model_dump() if draft else None}
            case "generate_todo_draft", TodoDraftRequest():
                if len(params.projects) > params.max_minutes:
                    raise ValueError(
                        "The budget must allow at least one minute per project."
                    )
                draft = await self.generate_draft(params)
                validate_draft(params, draft)
                self.store.set_draft(thread_id, draft)
                return {"unsaved_draft": draft.model_dump()}
            case "get_tool_history", _:
                return {"tool_history": self.store.history(thread_id)}
            case "read_skill_file", SkillFile():
                if params.name == "todo-cleanup" and params.path != "SKILL.md":
                    raise ValueError("This skill does not have a session guide.")
                return {
                    "text": (self.skills / params.name / params.path).read_text(
                        encoding="utf-8"
                    )
                }
            case _:
                raise ValueError("Unsupported local tool operation.")


def validate_draft(request: TodoDraftRequest, draft: TodoDraft) -> None:
    projects = [todo.project for todo in draft.todos]
    if sorted(projects) != sorted(request.projects):
        raise ValueError("The draft must contain each requested project exactly once.")
    if any(todo.date != request.date for todo in draft.todos):
        raise ValueError("Every draft item must have the requested date.")
    if sum(todo.minutes for todo in draft.todos) > request.max_minutes:
        raise ValueError("The draft exceeds the time budget.")


def calculate(params: Calculation) -> float:
    a, b, operation = params.a, params.b, params.operation
    if not math.isfinite(a) or not math.isfinite(b):
        raise ValueError("Enter finite numbers.")
    if operation == "add":
        result = a + b
    elif operation == "subtract":
        result = a - b
    elif operation == "multiply":
        result = a * b
    else:
        if b == 0:
            raise ValueError("The divisor must not be zero.")
        result = a / b
    if not math.isfinite(result):
        raise ValueError("The result is outside the supported numeric range.")
    return result
