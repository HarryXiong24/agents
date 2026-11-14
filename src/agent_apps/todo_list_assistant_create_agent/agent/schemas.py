"""Validate todo records and the structured output of draft generation."""

from datetime import date as calendar_date

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TodoView(BaseModel):
    """Describe one proposed todo with the same three fields as a saved record."""

    model_config = ConfigDict(extra="forbid", strict=True)

    project: str = Field(min_length=1, description="The todo name.")
    minutes: int = Field(ge=1, le=1440, description="Estimated duration in minutes.")
    date: str = Field(description="The scheduled date in YYYY-MM-DD format.")

    @field_validator("project")
    @classmethod
    def require_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("The todo name must not be blank.")
        return value

    @field_validator("date")
    @classmethod
    def require_calendar_date(cls, value: str) -> str:
        if calendar_date.fromisoformat(value).isoformat() != value:
            raise ValueError("The scheduled date must use YYYY-MM-DD format.")
        return value


class TodoDraftRequest(BaseModel):
    """Keep user-specified constraints separate from the model's proposed durations."""

    model_config = ConfigDict(extra="forbid", strict=True)

    projects: list[str] = Field(
        min_length=1, description="Distinct task names copied from the user request."
    )
    date: str = Field(description="The user-requested date in YYYY-MM-DD format.")
    max_minutes: int = Field(
        ge=1, le=1440, description="The user-requested total time budget in minutes."
    )

    @field_validator("projects")
    @classmethod
    def require_distinct_names(cls, values: list[str]) -> list[str]:
        if any(not name.strip() or name != name.strip() for name in values):
            raise ValueError("Task names must be nonblank without surrounding spaces.")
        if len(values) != len(set(values)):
            raise ValueError("Task names must be distinct.")
        return values

    @field_validator("date")
    @classmethod
    def require_calendar_date(cls, value: str) -> str:
        if calendar_date.fromisoformat(value).isoformat() != value:
            raise ValueError("The requested date must use YYYY-MM-DD format.")
        return value


class TodoDraft(BaseModel):
    """Model-generated candidate todos; validation does not save any records."""

    model_config = ConfigDict(extra="forbid", strict=True)

    todos: list[TodoView] = Field(
        min_length=1, description="Propose exactly one todo per requested task."
    )
