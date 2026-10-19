"""Local (in-process) tools. MCP tools are loaded separately in mcp_client.py.

📘 LEARN — what a "tool" is to the model:
    The @tool decorator turns a Python function into a LangChain BaseTool:
        name        ← function name                    e.g. "calculator"
        description ← the docstring                    (the model reads this to decide WHEN to call it)
        args schema ← type hints → JSON Schema         (the model reads this to decide HOW to call it)
    So the docstring is not documentation for humans only — it IS the prompt for the tool.
    Write it like an instruction: what it does, input format, limits, side effects.

📘 LEARN — local tool vs MCP tool:
    Local: runs in this Python process. Simple, fast, can access graph internals
           (store, state, context) via ToolRuntime.
    MCP  : runs in a separate server process (any language, any machine), discovered at
           startup. Reusable across agents/apps. See mcp_servers/workspace_server.py.
    After loading, both are BaseTools — the graph treats them identically.

🧪 TRY:  python -c "from agent.tools import calculator; print(calculator.tool_call_schema.model_json_schema())"
"""

from __future__ import annotations

import ast
import asyncio
import operator
from datetime import datetime

from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from langgraph.types import interrupt

from . import memory
from .config import settings

# =========================================================================== utilities

# ⚠ PITFALL: never `eval()` model output. A model (or a prompt injection inside a file it
# read) could produce "__import__('os').system('rm -rf ~')". We parse the expression into
# an AST and only allow numbers and arithmetic operators — a whitelist, not a blacklist.
_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def _safe_eval(node: ast.AST) -> float:
    """Recursively evaluate an arithmetic AST; anything else raises ValueError."""
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError(f"Unsupported expression element: {ast.dump(node)[:60]}")


@tool
def calculator(expression: str) -> str:
    """Evaluate an arithmetic expression, e.g. '(3 + 4) * 2 ** 3 / 7'. Supports + - * / // % **."""
    # 📘 LEARN: LLMs are unreliable at arithmetic; a calculator tool is the classic
    # "give the model a tool for what it's bad at" example. If the expression is invalid,
    # the ValueError becomes an error ToolMessage (handle_tool_errors=True in graph.py)
    # and the model can retry with a corrected expression.
    result = _safe_eval(ast.parse(expression, mode="eval"))
    return str(round(result, 10))


@tool
def get_current_time() -> str:
    """Return the current local date and time."""
    # Models have no clock. Even though the system prompt includes the time, a tool is
    # needed for long-running sessions and shows a zero-argument tool schema.
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S (%A)")


@tool
async def run_shell(command: str) -> str:
    """Run a shell command inside the workspace directory and return stdout/stderr.
    Requires human approval. Times out after 20 seconds."""
    # 📘 LEARN: this is the "dangerous" tool that motivates human-in-the-loop. It is
    # listed in settings.risky_tools, so the graph routes every call through
    # approval_gate BEFORE this function ever runs. The tool itself does not need to know.
    #
    # Defence in depth even after approval: fixed working dir, timeout, output cap.
    # `async` tool: the event loop stays free while the subprocess runs, so multiple
    # tool calls in one step really run in parallel.
    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=settings.workspace_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
    except asyncio.TimeoutError:
        proc.kill()
        return "ERROR: command timed out after 20s"
    text = out.decode(errors="replace")
    if len(text) > 4000:  # keep tool output from flooding the context window
        text = text[:4000] + f"\n... [truncated {len(text) - 4000} chars]"
    # Returning the exit code lets the model distinguish success from failure.
    return f"exit_code={proc.returncode}\n{text}"


# =========================================================================== human-in-the-loop tool

@tool
def ask_human(question: str) -> str:
    """Ask the user a clarifying question and wait for their answer.
    Use only when you genuinely cannot proceed without their input."""
    # 📘 LEARN — model-initiated HITL. Compare with approval_gate (policy-initiated):
    #   approval_gate : the GRAPH decides a human must look (based on tool name)
    #   ask_human     : the MODEL decides it needs a human (based on its own uncertainty)
    # Both use the same primitive. interrupt() pauses the whole graph here, the state is
    # checkpointed, and when the caller resumes with Command(resume="San Jose"),
    # this tool function re-runs and interrupt() returns "San Jose".
    #
    # ⚠ PITFALL: interrupt() only works inside a graph run with a checkpointer. Calling
    # ask_human.invoke(...) directly in a script raises an error.
    answer = interrupt({"type": "question", "question": question})
    return f"User answered: {answer}"


# =========================================================================== long-term memory tools
# 📘 LEARN — ToolRuntime injection: a parameter named `runtime` typed `ToolRuntime` is
# filled in by LangGraph at call time and is HIDDEN from the schema the model sees.
# The model only sees `content: str`. Through runtime we reach:
#     runtime.store    → the long-term Store passed to graph.compile(store=...)
#     runtime.context  → AgentContext (user_id) passed to graph.astream(context=...)
#     runtime.state    → current graph state (not used here)
#     runtime.tool_call_id
# This keeps per-user scoping out of the model's hands: it cannot write to another
# user's memory because it never controls user_id.
#
# 📘 LEARN — "hot path" memory writes: the model decides what to remember, during the
# conversation, by calling save_memory. The alternative is a background job that extracts
# memories after each turn. Hot path = transparent and immediate but costs a tool call;
# background = no latency but less control. This repo uses hot path.

@tool
async def save_memory(content: str, runtime: ToolRuntime) -> str:
    """Save a durable fact or preference about the user to long-term memory
    (persists across conversations). Write it as a short standalone sentence."""
    key = await memory.save(runtime.store, runtime.context.user_id, content)
    return f"Saved memory [{key}]: {content}"


@tool
async def search_memory(query: str, runtime: ToolRuntime) -> str:
    """Search long-term memory for facts about the user."""
    # prepare_turn already auto-recalls the top-k memories each turn; this tool lets the
    # model dig deeper when those weren't enough (agentic retrieval).
    hits = await memory.recall(runtime.store, runtime.context.user_id, query, k=8)
    return "\n".join(hits) if hits else "No matching memories."


@tool
async def delete_memory(memory_id: str, runtime: ToolRuntime) -> str:
    """Delete a long-term memory by its id (the value in [brackets])."""
    # Memory needs an update/forget path too, e.g. "I moved to Seattle" should
    # replace "lives in San Jose", not sit next to it.
    ok = await memory.delete(runtime.store, runtime.context.user_id, memory_id.strip("[] "))
    return f"Deleted memory [{memory_id}]" if ok else f"No memory with id [{memory_id}]"


LOCAL_TOOLS = [
    calculator,
    get_current_time,
    run_shell,
    ask_human,
    save_memory,
    search_memory,
    delete_memory,
]
