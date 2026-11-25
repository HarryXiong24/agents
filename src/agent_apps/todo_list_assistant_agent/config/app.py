"""Application paths, environment loading, and assembly of typed settings."""

from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from . import agent as agent_settings
from .agent import AgentConfig
from .mcp import McpConfig, parse_mcp_config
from .model import ModelConfig, parse_model_config

APP_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = APP_DIR / ".env"
DATA_DIR = APP_DIR / "data"
# Trusted, version-controlled skill directories, separate from ignored data.
SKILLS_DIR = APP_DIR / "skills"
# Local MCP server list; ignored by Git because commands and URLs are personal.
MCP_FILE = APP_DIR / "mcp.json"


@dataclass(frozen=True)
class AppConfig:
    """Model, Agent and MCP settings assembled from one local configuration snapshot."""

    model: ModelConfig
    agent: AgentConfig
    mcp: McpConfig


def read_env(env_file: Path | None = None) -> dict[str, str | None]:
    """Read one local file without parent searches or global interpolation."""
    path = ENV_FILE if env_file is None else env_file
    return dict(dotenv_values(path, encoding="utf-8", interpolate=False))


def load_config(
    env_file: Path | None = None, mcp_file: Path | None = None
) -> AppConfig:
    """Load model values and MCP servers locally; Agent settings are defined in code."""
    path = ENV_FILE if env_file is None else env_file
    env = read_env(path)
    return AppConfig(
        model=parse_model_config(env, path),
        agent=agent_settings.AGENT_CONFIG,
        # ${NAME} placeholders in mcp.json resolve from this same local .env.
        mcp=parse_mcp_config(MCP_FILE if mcp_file is None else mcp_file, env),
    )
