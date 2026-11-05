"""Model credentials and client settings."""

from dataclasses import dataclass
from pathlib import Path

from pydantic import SecretStr


@dataclass(frozen=True)
class ModelConfig:
    """Model credentials and settings passed to the model factory."""

    api_key: SecretStr
    model: str
    base_url: str
    temperature: float = 0
    timeout: float = 30
    max_retries: int = 1


def parse_model_config(env: dict[str, str | None], env_file: Path) -> ModelConfig:
    """Validate credentials and choose model defaults from already-loaded values."""
    api_key = env.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(f"Set GROQ_API_KEY in {env_file}.")
    return ModelConfig(
        api_key=SecretStr(api_key),
        model=env.get("AGENT_MODEL") or "openai/gpt-oss-20b",
        base_url=env.get("GROQ_BASE_URL") or "https://api.groq.com",
    )
