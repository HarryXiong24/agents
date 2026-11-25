"""Shared isolation: tests never start a developer's personal MCP servers."""

import pytest

from agent_apps.todo_list_assistant_create_agent.config import app as app_config


@pytest.fixture(autouse=True)
def no_local_mcp_servers(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "MCP_FILE", tmp_path / "absent-mcp.json")
