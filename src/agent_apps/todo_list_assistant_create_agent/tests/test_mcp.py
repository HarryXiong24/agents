"""Exercise MCP configuration and real stdio servers through the factory graph."""

import asyncio
import json
import sys
import textwrap
from contextlib import asynccontextmanager
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from mcp.types import CallToolResult, ImageContent, ListToolsResult, TextContent
from pydantic import ValidationError

from agent_apps.todo_list_assistant_create_agent import main as app
from agent_apps.todo_list_assistant_create_agent.agent import checkpoints, mcp, memory
from agent_apps.todo_list_assistant_create_agent.agent.agent import build_agent
from agent_apps.todo_list_assistant_create_agent.agent.mcp import (
    EXTERNAL_NOTE,
    McpConnections,
    McpServerError,
    result_to_text,
)
from agent_apps.todo_list_assistant_create_agent.config import (
    AgentConfig,
    McpConfig,
    load_config,
)
from agent_apps.todo_list_assistant_create_agent.config import agent as agent_settings
from agent_apps.todo_list_assistant_create_agent.config import app as app_config
from agent_apps.todo_list_assistant_create_agent.config.mcp import parse_mcp_config

from .test_factory import CONFIG, OfflineModel, ask, call

POMODORO = "agent_apps.todo_list_assistant_create_agent.mcp_servers.pomodoro"
TOOL = "pomodoro_plan_pomodoros"


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DATABASE_FILE", tmp_path / "todos.sqlite")
    monkeypatch.setattr(
        agent_settings, "AGENT_CONFIG", AgentConfig(summary_trigger_tokens=100_000)
    )


def pomodoro(**options) -> McpConfig:
    server = {"command": "python", "args": ["-m", POMODORO], **options}
    return McpConfig.model_validate({"mcpServers": {"pomodoro": server}})


@pytest.fixture(scope="module")
def pomodoro_tools():
    with McpConnections(pomodoro()) as tools:
        yield tools


def test_absent_file_means_no_servers_and_example_parses(tmp_path):
    assert parse_mcp_config(tmp_path / "missing.json", {}).servers == {}
    example = parse_mcp_config(app_config.APP_DIR / "mcp.example.json", {})
    server = example.servers["pomodoro"]
    assert server.require_approval is False
    assert server.connection()["command"] == sys.executable


def test_placeholders_resolve_from_local_env_only(tmp_path, monkeypatch):
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "remote": {
                        "transport": "streamable_http",
                        "url": "https://example.test/mcp",
                        "headers": {"Authorization": "Bearer ${MCP_TOKEN}"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MCP_TOKEN", "from-shell")
    with pytest.raises(ValueError, match="MCP_TOKEN"):
        parse_mcp_config(path, {})
    server = parse_mcp_config(path, {"MCP_TOKEN": "local"}).servers["remote"]
    connection = server.connection()
    assert connection["headers"] == {"Authorization": "Bearer local"}
    assert server.require_approval is True
    env = tmp_path / ".env"
    env.write_text("GROQ_API_KEY=k\nMCP_TOKEN=local\n", encoding="utf-8")
    assert (
        load_config(env, path).mcp.servers["remote"].url == "https://example.test/mcp"
    )


@pytest.mark.parametrize(
    "servers",
    [
        {"Bad Name": {"command": "python"}},
        {"a": {}},
        {"a": {"command": "python", "url": "https://x.test"}},
        {"a": {"transport": "streamable_http"}},
        {"a": {"transport": "streamable_http", "url": "https://x", "command": "x"}},
        {"a": {"command": "python", "unknown": 1}},
        {"a": {"command": "python", "timeout": 0}},
    ],
)
def test_invalid_server_configuration_is_rejected(servers):
    with pytest.raises(ValidationError):
        McpConfig.model_validate({"mcpServers": servers})


def test_invalid_json_is_a_startup_value_error(tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        parse_mcp_config(path, {})


def test_real_stdio_tools_are_prefixed_described_and_callable(pomodoro_tools):
    (tool,) = pomodoro_tools
    assert tool.name == TOOL
    assert tool.description.startswith("[MCP server: pomodoro]")
    assert EXTERNAL_NOTE in tool.description
    assert tool.metadata == {
        "mcp_server": "pomodoro",
        "mcp_tool": "plan_pomodoros",
        "require_approval": True,
    }
    assert tool.invoke({"minutes": 50}).startswith("2 focus blocks (25, 25 minutes)")
    error = tool.invoke(
        {"type": "tool_call", "id": "x", "name": TOOL, "args": {"minutes": 0}}
    )
    assert isinstance(error, ToolMessage) and error.status == "error"
    assert "minutes must be between 1 and 1440" in error.text


def test_mcp_tool_pauses_for_approval_by_default(pomodoro_tools, tmp_path):
    model = OfflineModel(
        responses=[
            AIMessage("", tool_calls=[call(TOOL, {"minutes": 50}, "p")]),
            AIMessage("Two blocks."),
        ]
    )
    with SqliteSaver.from_conn_string(str(tmp_path / "cp.sqlite")) as saver:
        graph = build_agent(model, saver, mcp_tools=pomodoro_tools)
        paused = graph.invoke(ask("Split 50 minutes."), CONFIG)
        interrupt = paused["__interrupt__"][0]
        assert interrupt.value["action_requests"][0]["name"] == TOOL
        result = graph.invoke(
            Command(resume={interrupt.id: {"decisions": [{"type": "approve"}]}}),
            CONFIG,
        )
    reply = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert reply.text.startswith("2 focus blocks")
    assert result["messages"][-1].text == "Two blocks."
    assert [r["tool_name"] for r in result["tool_history"]] == [TOOL]
    assert result["tool_calls_this_turn"] == 1


def test_trusted_server_runs_without_approval_and_errors_stay_visible():
    model = OfflineModel(
        responses=[
            AIMessage("", tool_calls=[call(TOOL, {"minutes": 0}, "bad")]),
            AIMessage("", tool_calls=[call(TOOL, {"minutes": 30}, "good")]),
            AIMessage("Done."),
        ]
    )
    with McpConnections(pomodoro(require_approval=False)) as tools:
        result = build_agent(model, mcp_tools=tools).invoke(ask())
    bad, good = (m for m in result["messages"] if isinstance(m, ToolMessage))
    assert bad.status == "error" and "between 1 and 1440" in bad.text
    assert good.status == "success" and good.text.startswith("2 focus blocks")
    assert "__interrupt__" not in result


def test_allowlist_conflicts_and_bad_commands_fail_startup():
    with pytest.raises(McpServerError, match="no tools named: missing"):
        with McpConnections(pomodoro(tools=["missing"])):
            pass
    with pytest.raises(McpServerError, match="conflicts"):
        with McpConnections(pomodoro(), reserved_names=frozenset({TOOL})):
            pass
    broken = McpConfig.model_validate(
        {"mcpServers": {"broken": {"command": "definitely-not-a-command-xyz"}}}
    )
    with pytest.raises(McpServerError, match="Could not start MCP server 'broken'"):
        with McpConnections(broken):
            pass


def test_slow_tool_times_out_as_propagated_server_fault(tmp_path):
    script = tmp_path / "slow_server.py"
    script.write_text(
        textwrap.dedent(
            """
            import time
            from mcp.server.fastmcp import FastMCP

            server = FastMCP("slow", log_level="WARNING")

            @server.tool()
            def wait() -> str:
                \"\"\"Wait too long.\"\"\"
                time.sleep(30)
                return "late"

            server.run("stdio")
            """
        ),
        encoding="utf-8",
    )
    config = McpConfig.model_validate(
        {
            "mcpServers": {
                "slow": {
                    "command": "python",
                    "args": ["-I", str(script)],
                    "timeout": 3,
                    "require_approval": False,
                }
            }
        }
    )
    model = OfflineModel(responses=[AIMessage("", tool_calls=[call("slow_wait")])])
    with McpConnections(config) as tools:
        with pytest.raises(McpServerError, match="did not answer within 3 seconds"):
            build_agent(model, mcp_tools=tools).invoke(ask())


def test_reserved_langchain_argument_names_reach_the_server(tmp_path):
    script = tmp_path / "echo_server.py"
    script.write_text(
        textwrap.dedent(
            """
            from mcp.server.fastmcp import FastMCP

            server = FastMCP("echo", log_level="WARNING")

            @server.tool()
            def echo(config: str, run_manager: str, callbacks: str) -> str:
                \"\"\"Echo arguments whose names LangChain also uses.\"\"\"
                return f"{config}|{run_manager}|{callbacks}"

            server.run("stdio")
            """
        ),
        encoding="utf-8",
    )
    config = McpConfig.model_validate(
        {"mcpServers": {"echo": {"command": "python", "args": ["-I", str(script)]}}}
    )
    with McpConnections(config) as (tool,):
        args = {"config": "a", "run_manager": "b", "callbacks": "c"}
        assert tool.invoke(args) == "a|b|c"


def test_content_blocks_are_flattened_to_text():
    result = CallToolResult(
        content=[
            TextContent(type="text", text="a"),
            ImageContent(type="image", data="...", mimeType="image/png"),
        ]
    )
    assert result_to_text(result) == "a\n[image content omitted]"
    structured = CallToolResult(content=[], structuredContent={"blocks": 2})
    assert result_to_text(structured) == '{"blocks": 2}'


def test_main_starts_configured_servers_and_closes_them(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        checkpoints, "CHECKPOINTS_FILE", tmp_path / "data" / "checkpoints.sqlite"
    )
    monkeypatch.setattr(app_config, "ENV_FILE", tmp_path / ".env")
    app_config.ENV_FILE.write_text("GROQ_API_KEY=offline-test-key\n", encoding="utf-8")
    monkeypatch.setattr(app_config, "MCP_FILE", app_config.APP_DIR / "mcp.example.json")
    model = OfflineModel(
        responses=[
            AIMessage("", tool_calls=[call(TOOL, {"minutes": 50}, "p")]),
            AIMessage("Planned."),
        ]
    )
    monkeypatch.setattr(app, "create_model", lambda config: model)
    inputs = iter(["0", "focus", "Split 50 minutes", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    app.main()
    output = capsys.readouterr().out
    assert f"MCP tools: {TOOL}" in output
    assert "Assistant: Planned." in output
    assert model.requests[1][-1].text.startswith("2 focus blocks")


def test_main_reports_mcp_startup_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(
        checkpoints, "CHECKPOINTS_FILE", tmp_path / "data" / "checkpoints.sqlite"
    )
    monkeypatch.setattr(app_config, "ENV_FILE", tmp_path / ".env")
    app_config.ENV_FILE.write_text("GROQ_API_KEY=offline-test-key\n", encoding="utf-8")
    broken = tmp_path / "mcp.json"
    broken.write_text(
        json.dumps({"mcpServers": {"broken": {"command": "definitely-not-xyz"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(app_config, "MCP_FILE", broken)
    monkeypatch.setattr(app, "create_model", lambda config: OfflineModel())
    inputs = iter(["0", "focus"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    with pytest.raises(SystemExit, match="Startup failed: Could not start MCP server"):
        app.main()


@pytest.mark.parametrize(
    "literal",
    [
        "${REVIEW_SHELL_TOKEN}",
        "prefix-${REVIEW_SHELL_TOKEN}-$RAW_TOKEN",
        "literal-$$-123",
    ],
)
def test_stdio_env_values_are_not_expanded_again_from_shell(
    tmp_path, monkeypatch, literal
):
    monkeypatch.setenv("REVIEW_SHELL_TOKEN", "dummy-shell-value")
    script = tmp_path / "env_server.py"
    script.write_text(
        textwrap.dedent(
            """
            import os
            from mcp.server.fastmcp import FastMCP

            server = FastMCP("env", log_level="WARNING")

            @server.tool()
            def read_token() -> str:
                \"\"\"Return the test's explicit environment value.\"\"\"
                return os.environ["TOKEN"]

            server.run("stdio")
            """
        ),
        encoding="utf-8",
    )
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"GROQ_API_KEY=offline-test-key\nLOCAL_TOKEN='{literal}'\n", encoding="utf-8"
    )
    config_file = tmp_path / "mcp.json"
    config_file.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "env": {
                        "command": "python",
                        "args": ["-I", str(script)],
                        "env": {"TOKEN": "${LOCAL_TOKEN}"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    config = load_config(env_file, config_file)
    with McpConnections(config.mcp) as (tool,):
        assert tool.invoke({}) == literal


@pytest.mark.parametrize("slow_close", [False, True])
def test_shutdown_finishes_owner_and_background_tasks_before_closing_loop(
    monkeypatch, slow_close
):
    monkeypatch.setattr(mcp, "SHUTDOWN_GRACE_SECONDS", 0.02)
    session = SimpleNamespace(
        initialize=AsyncMock(),
        list_tools=AsyncMock(return_value=ListToolsResult(tools=[])),
    )
    cleaned = Event()
    child_finished = Event()
    child_started = Event()
    lifecycle = {}

    async def pending_call():
        child_started.set()
        try:
            await asyncio.sleep(60)
        finally:
            child_finished.set()

    @asynccontextmanager
    async def open_session(server):
        lifecycle["entered_by"] = asyncio.current_task()
        lifecycle["child"] = asyncio.create_task(pending_call())
        try:
            yield session
        finally:
            lifecycle["exited_by"] = asyncio.current_task()
            try:
                if slow_close:
                    await asyncio.sleep(60)
            finally:
                # A real session must finish unwinding in the owner task even
                # after the graceful-close allowance has elapsed.
                await asyncio.sleep(0)
                cleaned.set()

    monkeypatch.setattr(mcp, "open_mcp_session", open_session)
    connections = McpConnections(pomodoro())
    connections.__enter__()
    loop, thread, owner = (
        connections._loop,
        connections._thread,
        connections._owner_task,
    )
    assert loop is not None and thread is not None and owner is not None
    assert child_started.wait(timeout=1)
    connections.close()
    assert cleaned.is_set() and child_finished.is_set()
    assert lifecycle["entered_by"] is lifecycle["exited_by"] is owner
    assert owner.done()
    assert lifecycle["child"].done()
    assert not asyncio.all_tasks(loop)
    assert loop.is_closed() and not thread.is_alive()
    connections.close()  # Closing again is harmless.


def test_startup_timeout_cancels_owner_and_finishes_transport_cleanup(monkeypatch):
    monkeypatch.setattr(mcp, "SHUTDOWN_GRACE_SECONDS", 0.02)
    cleaned = Event()
    lifecycle = {}

    @asynccontextmanager
    async def never_connects(server):
        lifecycle["owner"] = asyncio.current_task()
        lifecycle["loop"] = asyncio.get_running_loop()
        try:
            await asyncio.sleep(60)
            yield
        finally:
            await asyncio.sleep(0)
            cleaned.set()

    monkeypatch.setattr(mcp, "open_mcp_session", never_connects)
    connections = McpConnections(pomodoro(timeout=0.05))
    with pytest.raises(McpServerError, match="did not start within"):
        connections.__enter__()
    assert cleaned.is_set()
    assert lifecycle["owner"].done()
    assert not asyncio.all_tasks(lifecycle["loop"])
    assert lifecycle["loop"].is_closed()
    assert connections._thread is None


def test_http_sessions_still_use_the_adapter(monkeypatch):
    session = SimpleNamespace(
        initialize=AsyncMock(),
        list_tools=AsyncMock(return_value=ListToolsResult(tools=[])),
    )
    received = []

    @asynccontextmanager
    async def fake_adapter(connection):
        received.append(connection)
        yield session

    monkeypatch.setattr(mcp, "create_session", fake_adapter)
    config = McpConfig.model_validate(
        {
            "mcpServers": {
                "remote": {
                    "transport": "streamable_http",
                    "url": "https://example.test/mcp",
                    "headers": {"Authorization": "Bearer literal-${TOKEN}"},
                }
            }
        }
    )
    with McpConnections(config) as tools:
        assert tools == []
    assert received[0]["headers"] == {"Authorization": "Bearer literal-${TOKEN}"}
