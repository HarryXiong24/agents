"""Local tools run inside the agent process; MCP tools run in a separate service.
📘 LEARN: @tool converts the function name, docstring and type hints into the tool
name, description and JSON Schema seen by the model. Descriptions guide tool selection.
Both kinds become BaseTool objects and share one ToolNode.
🧪 TRY: inspect calculate_share.tool_call_schema.model_json_schema().

本地工具在 Agent 进程运行；MCP 工具由独立服务执行。
📘 LEARN：@tool 将函数名、文档字符串和类型提示转换为模型看到的
工具名称、描述和 JSON Schema。描述会影响模型选择工具的方式。
两类工具都转换为 BaseTool，由同一个 ToolNode 执行。
🧪 TRY：查看 calculate_share.tool_call_schema.model_json_schema()。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from langgraph.types import interrupt

from . import memory
from .state import AgentContext


@tool
def calculate_share(part: str, total: str) -> str:
    """Calculate a spending percentage from same-currency amount strings, e.g. part="28", total="100".
    Return a percentage rounded to two decimals. Require 0 <= part <= total and total > 0.
    A zero total has no defined share; explain this instead of retrying.

    计算同币种支出的占比，金额使用字符串，如 part="28", total="100"。
    返回保留两位小数的百分比。要求 0 <= part <= total 且 total > 0。
    总额为零时占比无定义，应说明原因，不要反复重试。
    """
    # 📘 LEARN: Decimal preserves decimal inputs; this tool needs no expression parser.
    # 📘 LEARN：Decimal 保留十进制输入；这个工具不需要表达式解析器。
    try:
        numerator, denominator = Decimal(part), Decimal(total)
    except InvalidOperation as exc:
        raise ValueError("金额必须是十进制数字") from exc
    if not numerator.is_finite() or not denominator.is_finite():
        raise ValueError("金额必须是有限数字")
    if denominator <= 0 or not 0 <= numerator <= denominator:
        raise ValueError("要求 0 <= part <= total，且 total > 0")

    return f"{numerator / denominator * 100:.2f}%"


@tool
def get_current_time() -> str:
    """Return the current local date and time; use it to resolve today or this week.

    返回当前本地日期和时间，用于确定“今天”或“本周”的范围。
    """
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S (%A)")


@tool
def ask_human(question: str) -> str:
    """Ask a necessary clarifying question and wait for the user.
    Use when you cannot proceed correctly without their input.
    Call this tool alone; combine multiple necessary questions into a single call.

    提出必要的澄清问题，等待用户回答。
    当缺少用户信息会导致无法正确继续时使用。
    请单独调用本工具，把多个必要问题合并为一次提问。
    """
    # 📘 LEARN: model-driven HITL; approval_gate is policy-driven. Both use interrupt.
    # The tool restarts on resume. Direct invocation outside a checkpointed graph cannot pause.
    # 📘 LEARN：这是模型主动发起的 HITL，approval_gate 则由策略触发，两者都使用 interrupt。
    # 恢复时工具重新执行；脱离带 Checkpointer 的图直接调用工具，无法正常暂停。
    answer = interrupt({"type": "question", "question": question})
    return f"User answered: {answer}"


@tool
async def save_memory(content: str, runtime: ToolRuntime[AgentContext]) -> str:
    """Save a durable reporting preference about this user across conversations.
    Use a short standalone sentence; expenses belong in the ledger, not memory.

    跨会话保存用户长期有效的报告偏好。
    使用简短独立的句子；支出应写入账本，不应写入偏好记忆。
    """
    # 📘 LEARN: ToolRuntime is injected and hidden from the tool schema. runtime.store/context
    # give access to per-user memory. Hot-path writes are explicit; background extraction is an alternative.
    # 📘 LEARN：ToolRuntime 自动注入，且不出现在工具 schema 中。runtime.store/context
    # 提供用户记忆访问。这里采用显式的即时写入，也可设计后台记忆提取。
    key = await memory.save(runtime.store, runtime.context.user_id, content)
    return f"Saved memory [{key}]: {content}"


@tool
async def search_memory(query: str, runtime: ToolRuntime[AgentContext]) -> str:
    """Search long-term memory for the user’s reporting preferences.

    搜索用户长期记忆中的报告偏好。
    """
    # Automatic recall happens in prepare_turn; this tool allows deeper, model-directed retrieval.
    # prepare_turn 已自动召回；这个工具允许模型按需进一步查询。
    hits = await memory.recall(runtime.store, runtime.context.user_id, query, k=8)
    return "\n".join(hits) if hits else "No matching memories."


@tool
async def delete_memory(memory_id: str, runtime: ToolRuntime[AgentContext]) -> str:
    """Delete a long-term memory by its ID (shown in brackets).

    按 ID 删除长期记忆，ID 显示在方括号内。
    """
    ok = await memory.delete(
        runtime.store, runtime.context.user_id, memory_id.strip("[] ")
    )
    return f"Deleted memory [{memory_id}]" if ok else f"No memory with id [{memory_id}]"


LOCAL_TOOLS = [
    calculate_share,
    get_current_time,
    ask_human,
    save_memory,
    search_memory,
    delete_memory,
]
