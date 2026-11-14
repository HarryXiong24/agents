"""Application paths, environment loading, and assembly of typed settings."""

from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from . import agent as agent_settings
from .agent import AgentConfig
from .model import ModelConfig, parse_model_config

APP_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = APP_DIR / ".env"
DATA_DIR = APP_DIR / "data"


@dataclass(frozen=True)
class AppConfig:
    """Model and Agent settings assembled from one local configuration snapshot."""

    model: ModelConfig
    agent: AgentConfig


def read_env(env_file: Path | None = None) -> dict[str, str | None]:
    """Read one local file without parent searches or global interpolation."""
    path = ENV_FILE if env_file is None else env_file
    return dict(dotenv_values(path, encoding="utf-8", interpolate=False))


def load_config(env_file: Path | None = None) -> AppConfig:
    """Load model values from the local .env and use Agent settings defined in code."""
    path = ENV_FILE if env_file is None else env_file
    env = read_env(path)
    return AppConfig(
        model=parse_model_config(env, path),
        agent=agent_settings.AGENT_CONFIG,
    )
