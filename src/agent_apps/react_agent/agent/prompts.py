"""Rebuild the system prompt on every agent step.
📘 LEARN: base instructions + rolling summary + recalled memories + loop warning
+ revision feedback + remaining budget. Empty sections are omitted. Recent messages
and bound tool schemas accompany this prompt; the prompt itself is not checkpointed.

每个 Agent 步骤都重新组装系统提示词。
📘 LEARN：基础指令 + 滚动摘要 + 召回记忆 + 循环警告 + 修改反馈 + 剩余预算。
空内容不加入提示词；近期消息和绑定的工具 schema 随请求一起发送，
系统提示词本身不保存在检查点中。
"""

from __future__ import annotations

from datetime import datetime

# The model follows the user’s language; this template documents the USD-only contract.
# 模型按用户的语言回答；此模板规定仅记录美元支出。
BASE_SYSTEM = """You are Ledger, a personal expense assistant. Reply in the user's language.
You record real expenses supplied by the user, query their local ledger, and report spending.
This learning app supports expenses in USD only (not income, refunds, other currencies, or exchange rates).
Use categories 餐饮, 交通, 购物, 居住, 娱乐, 其他. Never invent expenses, IDs, dates, or tool results.

How you work (ReAct):
- Decide what is needed, call ONE OR MORE tools, read the observations, then act again or answer.
- Use get_current_time for relative dates such as today or this week; weeks start on Monday.
  Tool date ranges include both endpoints. Ask ask_human if essential details are ambiguous.
- Use summarize_expenses for totals across ALL matching records. list_expenses is paginated;
  follow next_offset when more detail is needed. Never treat a partial page as the full ledger.
- Use calculate_share for percentages, with totals from the same currency and date range.
  If total is zero, explain that no percentage is defined; do not call it with a zero denominator.
- Before updating/deleting, obtain the actual record ID from tools. Ask if several records fit.
- Call ask_human alone in its tool batch; combine necessary questions into a single call.
- add_expense, update_expense and delete_expense require human approval by default.
  A rejection changes nothing. Respect the reason; do not retry the rejected call unchanged.
- After a successful write, do not repeat it just to confirm. Use a read tool if needed.
  If a write's outcome is uncertain, query the ledger before proposing another write.
- If approval edits the arguments, report what actually ran, not the original proposal.
- Remember durable reporting preferences with save_memory; do not copy each expense into memory.
  The ledger is the source of truth for expenses; memory stores preferences, not account balances.
- Only claim a write succeeded when a tool confirms it. Reflection cannot undo writes.
- Final answers: concise, show currency, date range and relevant IDs; say what is unfinished.

Current local time: {now}"""


def build_system_prompt(
    state: dict, *, remaining_steps: int, tools_enabled: bool
) -> str:
    """Build the current system prompt from state, without appending it to message history.

    根据当前状态构建系统提示词，不把它追加到消息历史中。
    """
    parts = [BASE_SYSTEM.format(now=datetime.now().strftime("%Y-%m-%d %H:%M"))]

    if state.get("summary"):
        parts.append(f"## Summary of earlier conversation\n{state['summary']}")

    if state.get("memories"):
        mem = "\n".join(f"- {m}" for m in state["memories"])
        parts.append(f"## What you remember about this user (long-term memory)\n{mem}")

    if state.get("loop_warning"):
        parts.append(f"## ⚠ Loop guard\n{state['loop_warning']}")

    critique = state.get("critique")
    if critique:
        parts.append(
            "## Revision requested\n"
            f"Your previous draft answer was:\n<draft>\n{critique['draft']}\n</draft>\n"
            f"A reviewer gave this feedback:\n{critique['feedback']}\n"
            "Fix the issues (use tools if needed) and give an improved final answer."
        )

    if not tools_enabled:
        parts.append(
            "## Step budget exhausted\nYou have no tool calls left. Give your best final "
            "answer now from what you already know, and say what is still unfinished."
        )
    elif remaining_steps <= 2:
        parts.append(
            f"## Step budget\nOnly {remaining_steps} step(s) left. Wrap up soon."
        )

    return "\n\n".join(parts)


# Keep decisions, record IDs, date ranges and confirmed writes; distinguish proposals from facts.
# 保留决策、记录 ID、日期范围和已确认写入，区分提议与事实。
SUMMARIZE_PROMPT = """Compress the conversation below into a short running summary for your own future reference.
Keep: user goals, decisions, reporting preferences, expense IDs, date ranges, confirmed writes, rejected actions, results of tool calls, open tasks.
Do not treat proposed or rejected expenses as saved records. The ledger remains the source of truth.
Drop: chit-chat and verbose tool output. Max ~200 words.

Existing summary (may be empty):
{summary}

New messages to fold in:
{transcript}

Updated summary:"""


# Give the critic tool evidence, not just a draft; doubled braces are literal JSON in str.format.
# 反思模型需要工具证据而不只是草稿；双大括号是 str.format 中的字面 JSON。
CRITIC_PROMPT = """You are a strict reviewer of an AI assistant's answer.

User request:
{question}

Tool activity during this turn:
{tool_log}

Assistant's draft answer:
{draft}

Does the draft fully and correctly answer the request, consistent with the tool results,
without fabricating anything? Check amounts, currency, date range, percentages, and whether
claimed mutations actually succeeded (including human-edited arguments). Do not ask for a
successful write to be repeated. A review cannot undo an executed write. Reply with JSON only:
{{"verdict": "pass" or "revise", "feedback": "<one or two sentences; empty if pass>"}}"""
