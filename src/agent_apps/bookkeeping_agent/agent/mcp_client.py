"""Load MCP tools from configuration.
📘 LEARN: client → initialize → tools/list → BaseTool adapter → bind_tools;
a later model call reaches tools/call through the adapter. MCP serves tools;
it does not replace function calling. The model sees the same schema as local tools.
stdio launches a local subprocess; streamable_http connects to a remote server.
SSE is a legacy transport; the configuration can describe additional servers.

从配置加载 MCP 工具。
📘 LEARN：客户端 → initialize → tools/list → BaseTool 适配器 → bind_tools；
随后模型的工具调用通过适配器转为 tools/call。MCP 负责提供工具，
不替代 Function Calling，模型看到的 schema 与本地工具相同。
stdio 启动本地子进程；streamable_http 连接远程服务。
SSE 是较早的传输方式；配置中可以继续添加其他服务。
"""

from __future__ import annotations

import json
import sys

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from mcp.client.stdio import get_default_environment

from .config import ROOT, settings, user_data_dir


def _expand(value, user_id: str = "default"):
    """Expand portable Python, app-root and trusted per-user ledger paths recursively.

    递归展开 Python、应用根目录和可信的用户账本路径，使配置不依赖启动目录。
    """
    if isinstance(value, str):
        return (value.replace("${PYTHON}", sys.executable).replace("${ROOT}", str(ROOT))
                .replace("${LEDGER_DB}", str(user_data_dir(user_id) / "expenses.sqlite")))
    if isinstance(value, list):
        return [_expand(v, user_id) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v, user_id) for k, v in value.items()}
    return value


def load_connections(user_id: str = "default") -> dict:
    if not settings.mcp_config.exists():
        return {}
    conns = _expand(json.loads(settings.mcp_config.read_text()), user_id)
    for conn in conns.values():
        if conn.get("transport") == "stdio":
            # ⚠ PITFALL: an explicit stdio env replaces the inherited environment; merge safe defaults.
            # ⚠ PITFALL：显式传入 stdio env 会替换继承环境，需要合并安全默认值。
            conn["env"] = {**get_default_environment(), **conn.get("env", {})}
    return conns


async def load_mcp_tools(*, user_id: str = "default") -> tuple[list[BaseTool], dict[str, list[str]]]:
    """Discover each server independently; warn and skip a failed server.
    The adapter opens a short-lived session per call, so business state must persist
    outside the server process. user_id comes from the CLI, never from the model.

    分别发现各服务的工具；启动失败时警告并跳过该服务。
    适配器默认每次调用建立短会话，因此业务状态必须保存在服务进程之外。
    user_id 来自命令行入口，不由模型填写。
    """
    tools: list[BaseTool] = []
    report: dict[str, list[str]] = {}
    for name, conn in load_connections(user_id).items():
        try:
            server_tools = await MultiServerMCPClient({name: conn}).get_tools()
        except Exception as exc:
            print(f"  ! MCP server '{name}' failed to start: {exc}", file=sys.stderr)
            continue
        tools.extend(server_tools)
        report[name] = [t.name for t in server_tools]
    return tools, report


if __name__ == "__main__":
    import asyncio

    _, rep = asyncio.run(load_mcp_tools())
    print(json.dumps(rep, indent=2))
