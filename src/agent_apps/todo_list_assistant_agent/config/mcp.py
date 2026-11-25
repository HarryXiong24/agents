"""MCP server settings parsed from the application-local mcp.json file."""

import json
import re
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Server names become tool-name prefixes, so keep them provider-safe.
SERVER_NAME_PATTERN = re.compile(r"[a-z0-9]+(?:[_-][a-z0-9]+)*")
PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class McpServerConfig(BaseModel):
    """One server: how to connect, which tools to expose, and approval policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    transport: Literal["stdio", "streamable_http"] = "stdio"
    # stdio: the literal command "python" means the interpreter running this app.
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    # stdio servers receive only the SDK's safe default variables plus these.
    env: dict[str, str] | None = None
    cwd: str | None = None
    # streamable_http
    url: str | None = None
    headers: dict[str, str] | None = None
    # Optional allowlist of the server's own tool names; None exposes all tools.
    tools: list[str] | None = None
    # External tools may have side effects, so approval is on unless disabled.
    require_approval: bool = True
    # Seconds allowed for one tool call; connecting uses the same limit.
    timeout: float = Field(default=30, gt=0, le=600)

    @model_validator(mode="after")
    def require_transport_fields(self) -> "McpServerConfig":
        if self.transport == "stdio":
            if not self.command:
                raise ValueError("stdio servers need a command.")
            if self.url or self.headers:
                raise ValueError("stdio servers do not use url or headers.")
        else:
            if not self.url:
                raise ValueError("streamable_http servers need a url.")
            if self.command or self.args or self.env or self.cwd:
                raise ValueError(
                    "streamable_http servers do not use command, args, env or cwd."
                )
        return self

    def connection(self) -> dict[str, Any]:
        """Return a langchain-mcp-adapters connection dictionary."""
        if self.transport == "stdio":
            command = sys.executable if self.command == "python" else self.command
            connection: dict[str, Any] = {
                "transport": "stdio",
                "command": command,
                "args": list(self.args),
            }
            if self.env is not None:
                connection["env"] = dict(self.env)
            if self.cwd is not None:
                connection["cwd"] = self.cwd
            return connection
        connection = {"transport": "streamable_http", "url": self.url}
        if self.headers is not None:
            connection["headers"] = dict(self.headers)
        connection["timeout"] = self.timeout
        return connection


class McpConfig(BaseModel):
    """All configured servers; an absent mcp.json means none."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    servers: dict[str, McpServerConfig] = Field(
        default_factory=dict, alias="mcpServers"
    )

    @field_validator("servers")
    @classmethod
    def require_safe_names(
        cls, value: dict[str, McpServerConfig]
    ) -> dict[str, McpServerConfig]:
        for name in value:
            if not SERVER_NAME_PATTERN.fullmatch(name):
                raise ValueError(
                    f"MCP server name {name!r} must use lowercase letters, digits, "
                    "and single '_' or '-' separators."
                )
        return value


def substitute(value: Any, env: dict[str, str | None], source: Path) -> Any:
    """Replace ${NAME} in strings with values from the local .env only."""
    if isinstance(value, str):

        def replace(match: re.Match[str]) -> str:
            found = env.get(match.group(1))
            if not found:
                raise ValueError(
                    f"{source} uses ${{{match.group(1)}}}, which is not set in the "
                    "application-local .env."
                )
            return found

        return PLACEHOLDER.sub(replace, value)
    if isinstance(value, list):
        return [substitute(item, env, source) for item in value]
    if isinstance(value, dict):
        return {key: substitute(item, env, source) for key, item in value.items()}
    return value


def parse_mcp_config(path: Path, env: dict[str, str | None]) -> McpConfig:
    """Read mcp.json when present; secrets stay in .env and are referenced."""
    if not path.is_file():
        return McpConfig()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc
    return McpConfig.model_validate(substitute(raw, env, path))
