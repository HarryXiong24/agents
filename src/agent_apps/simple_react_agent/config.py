"""Load and validate configuration from this agent's private .env file."""

from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

ENV_FILE = Path(__file__).resolve().parent / ".env"


def read_env() -> dict[str, str | None]:
    """Read only the agent-local file; do not search parents or interpolate globals."""
    return dict(dotenv_values(ENV_FILE, encoding="utf-8", interpolate=False))


@dataclass(frozen=True)
class SummaryConfig:
    """Keep two completed turns and aim for a short rolling summary."""

    # use to trigger a summary when the conversation exceeds this many tokens
    trigger_tokens: int = 500
    # use to keep a short rolling summary of the last N turns, where a turn is a user message and an agent response
    keep_turns: int = 2

    # Validate that the values are positive integers
    def __post_init__(self) -> None:
        for name in ("trigger_tokens", "keep_turns"):
            value = getattr(self, name)
            if type(value) is not int:
                raise TypeError(f"{name} must be an integer.")
            if value < 1:
                raise ValueError(f"{name} must be greater than zero.")


def load_summary_config() -> SummaryConfig:
    """Load summary settings independently from the same agent-local .env."""
    env = read_env()
    if "SUMMARY_TRIGGER_TOKENS" not in env:
        return SummaryConfig()
    raw = env["SUMMARY_TRIGGER_TOKENS"]
    try:
        if raw is None:
            raise ValueError("Missing threshold value.")
        return SummaryConfig(trigger_tokens=int(raw))
    except ValueError as exc:
        raise ValueError("SUMMARY_TRIGGER_TOKENS must be a positive integer.") from exc
