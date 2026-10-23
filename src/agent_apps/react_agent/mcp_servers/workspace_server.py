"""A small MCP server exposing a sandboxed file workspace over stdio.

Run standalone to inspect it:   python mcp_servers/workspace_server.py
The agent launches it as a subprocess via langchain-mcp-adapters (see mcp_servers.json).

📘 LEARN — this file is the SERVER side of MCP. Note what's absent: no LangChain, no
LangGraph, no model. An MCP server only knows how to describe and run tools. Any MCP
client (this agent, Claude Desktop, Cursor, another framework) can use it unchanged.
That reusability is the point of MCP.

📘 LEARN — FastMCP does the protocol work for you:
    @mcp.tool() on a function
      → name        = function name
      → description = docstring
      → inputSchema = JSON Schema generated from type hints (path: str, append: bool = False)
    and handles `tools/list` / `tools/call` JSON-RPC messages over stdio.

    An exception raised inside a tool is sent back as an error result (isError=true);
    the client adapter turns it into an error ToolMessage the model can read and react to.

🧪 TRY:  npx @modelcontextprotocol/inspector python mcp_servers/workspace_server.py
         (a web UI to list and call this server's tools by hand)
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

WORKSPACE = Path(os.getenv("WORKSPACE_DIR", Path(__file__).resolve().parent.parent / "workspace")).resolve()
WORKSPACE.mkdir(parents=True, exist_ok=True)

# log_level=WARNING: FastMCP logs every request at INFO to stderr, which would clutter
# the agent's console (the client forwards server stderr).
# ⚠ PITFALL: a stdio server must NEVER print() to stdout — stdout carries the JSON-RPC
# protocol, and stray text corrupts it. Log to stderr only.
mcp = FastMCP("workspace", log_level="WARNING")


def _resolve(path: str) -> Path:
    """Map a relative path into the workspace and refuse anything that escapes it.

    ⚠ PITFALL — path traversal: the model (or text it read) may send "../../.ssh/id_rsa"
    or an absolute path. `.resolve()` normalises ".." and symlinks; then we check the
    result is still inside WORKSPACE. Tool servers must enforce their own sandbox —
    never trust arguments just because "the model wrote them".
    """
    p = (WORKSPACE / path).resolve()
    if p != WORKSPACE and WORKSPACE not in p.parents:
        raise ValueError(f"Path '{path}' is outside the workspace")
    return p


# 📘 LEARN: read-only tools (list/read/search) are NOT in AGENT_RISKY_TOOLS, so they run
# without approval. Mutating tools (write/delete) are. Classifying tools by side effects
# is the usual basis for a HITL policy.

@mcp.tool()
def list_files(subdir: str = ".") -> str:
    """List files in the workspace (optionally inside a sub-directory)."""
    base = _resolve(subdir)
    if not base.exists():
        return f"Directory '{subdir}' does not exist."
    rows = []
    for p in sorted(base.rglob("*")):
        if p.is_file():
            rows.append(f"{p.relative_to(WORKSPACE)}  ({p.stat().st_size} bytes)")
    return "\n".join(rows) or "(workspace is empty)"


@mcp.tool()
def read_file(path: str) -> str:
    """Read a UTF-8 text file from the workspace."""
    p = _resolve(path)
    if not p.is_file():
        raise FileNotFoundError(f"No such file: {path}")  # → error result → model sees it
    text = p.read_text(encoding="utf-8", errors="replace")
    # Server-side cap as well as the client-side cap in graph.py: defence in depth.
    return text if len(text) <= 6000 else text[:6000] + "\n... [truncated]"


@mcp.tool()
def write_file(path: str, content: str, append: bool = False) -> str:
    """Create or overwrite a text file in the workspace (set append=true to append)."""
    p = _resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a" if append else "w", encoding="utf-8") as f:
        f.write(content)
    # Return a confirmation the model can quote, not just "ok": it helps the critic and
    # the final answer stay grounded in what actually happened.
    return f"{'Appended to' if append else 'Wrote'} {path} ({len(content)} chars)"


@mcp.tool()
def delete_file(path: str) -> str:
    """Delete a file from the workspace."""
    p = _resolve(path)
    if not p.is_file():
        raise FileNotFoundError(f"No such file: {path}")
    p.unlink()
    return f"Deleted {path}"


@mcp.tool()
def search_files(keyword: str) -> str:
    """Case-insensitive full-text search across all workspace files. Returns file:line matches."""
    hits = []
    for p in sorted(WORKSPACE.rglob("*")):
        if not p.is_file():
            continue
        try:
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if keyword.lower() in line.lower():
                    hits.append(f"{p.relative_to(WORKSPACE)}:{i}: {line.strip()[:160]}")
        except UnicodeDecodeError:
            continue  # skip binary files
    return "\n".join(hits[:50]) or f"No matches for '{keyword}'."


if __name__ == "__main__":
    mcp.run(transport="stdio")  # blocks, serving JSON-RPC on stdin/stdout
