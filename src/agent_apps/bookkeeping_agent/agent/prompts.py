"""Rebuild the system prompt on every agent step.
📘 LEARN: base instructions + rolling summary + recalled memories + loop warning
+ revision feedback + remaining budget. Empty sections are omitted. Recent messages
and bound tool schemas accompany this prompt; the prompt itself is not checkpointed.

每个 Agent 步骤都重新组装系统提示词。
📘 LEARN：基础指令 + 滚动摘要 + 召回记忆 + 循环警告 + 修改反馈 + 剩余预算。
空内容不加入提示词；近期消息和绑定的工具 schema 随请求一起发送，
系统提示词本身不保存在检查点中。
"""

# 本文件负责定义和组装提示词，不直接调用模型；真正的模型请求在 graph.py 中执行。
# 四个部分：BASE_SYSTEM 定义基础规则，build_system_prompt 组装当前系统提示词，
# SUMMARIZE_PROMPT 指导旧对话压缩，CRITIC_PROMPT 指导回答评审。
# 与长期记忆的衔接：memory.recall() → prepare_turn 写入 state["memories"]
# → 本文件把记忆加入系统提示词 → graph.py 将提示词与近期消息一起发送给模型。

from __future__ import annotations

from datetime import datetime

# The model follows the user’s language; this template documents the USD-only contract.
# 模型按用户的语言回答；此模板规定仅记录美元支出。
# 这是固定的基础指令模板，{now} 在每次组装时替换为当前本地时间。
# 身份与范围：个人支出助手，仅支持美元支出，并使用指定的六种分类。
# ReAct 工作方式：决定下一步 → 调用一个或多个工具 → 阅读结果 → 继续行动或回答。
# 日期与查询：相对日期先查时间；汇总全部匹配记录使用 summarize_expenses，
# list_expenses 只返回分页数据，不能把一页记录误当成整个账本。
# 百分比：分子与分母必须采用相同币种和日期范围，分母为零时不能计算。
# 写入与审批：先查真实 ID；被拒绝后尊重原因；成功后不重复写入。
# 如果审批把 $20 改成 $25，最终回答必须报告实际执行的 $25，而非原提议。
# 数据分工：账本保存支出事实，长期记忆只保存用户偏好；工具确认成功后才报告成功。
# 回答要求：简洁，注明币种、日期范围、相关 ID，以及尚未完成的事项。
# 这些文本用于指导模型；实际审批、工具执行和数据持久化仍由其他代码落实。
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
    # state：当前图状态；* 表示后面的 remaining_steps 和 tools_enabled 必须按名称传入。
    # remaining_steps：剩余 Agent 决策步数；tools_enabled：当前这一步是否允许使用工具。
    state: dict, *, remaining_steps: int, tools_enabled: bool
) -> str:
    """Build the current system prompt from state, without appending it to message history.

    根据当前状态构建系统提示词，不把它追加到消息历史中。
    """
    # 例如把 {now} 替换为 "2026-10-25 14:30"，以基础指令作为第一部分。
    # parts 暂存各段文本，最后统一连接；这里尚未向模型发送任何请求。
    parts = [BASE_SYSTEM.format(now=datetime.now().strftime("%Y-%m-%d %H:%M"))]

    # get 在字段不存在时返回 None；没有摘要或摘要为空时，跳过这一段。
    if state.get("summary"):
        # 加入旧对话的滚动摘要，让模型了解已压缩的历史目标、决策和执行结果。
        parts.append(f"## Summary of earlier conversation\n{state['summary']}")

    # memories 是 prepare_turn 从长期存储召回后写入状态的字符串列表。
    if state.get("memories"):
        # 每条记忆前加 "- "，再用换行连接，例如 "- [a1] 用户希望用中文回答"。
        mem = "\n".join(f"- {m}" for m in state["memories"])
        # 数据保存在数据库里不代表模型自动知道；这里把召回内容显式放进上下文。
        parts.append(f"## What you remember about this user (long-term memory)\n{mem}")

    # loop_guard 检测到重复调用或连续失败时会写入警告；此处将警告传达给模型。
    if state.get("loop_warning"):
        parts.append(f"## ⚠ Loop guard\n{state['loop_warning']}")

    # reflect 节点要求修改时会保存 {"draft": 上一版回答, "feedback": 评审意见}。
    critique = state.get("critique")
    # 没有评审反馈时跳过；有反馈时，让模型同时看到旧草稿、问题和修改要求。
    if critique:
        # 相邻字符串会自动拼接；<draft>...</draft> 是标明草稿范围的文本分隔标记。
        parts.append(
            "## Revision requested\n"
            f"Your previous draft answer was:\n<draft>\n{critique['draft']}\n</draft>\n"
            f"A reviewer gave this feedback:\n{critique['feedback']}\n"
            "Fix the issues (use tools if needed) and give an improved final answer."
        )

    # graph.py 在最后一个允许的 Agent 步骤使用未绑定工具的模型；这里配套要求收尾。
    if not tools_enabled:
        # 只能根据已有信息回答，并明确尚未完成的事项，不能假装任务全部完成。
        parts.append(
            "## Step budget exhausted\nYou have no tool calls left. Give your best final "
            "answer now from what you already know, and say what is still unfinished."
        )
    # 工具仍可用但最多只剩两步时，提醒模型尽快完成任务。
    # 一步指 agent 节点的一次模型决策；一次决策可以生成多个工具调用。
    elif remaining_steps <= 2:
        parts.append(
            f"## Step budget\nOnly {remaining_steps} step(s) left. Wrap up soon."
        )

    # 用空行连接基础指令、摘要、记忆、警告、反馈与预算提醒，返回完整提示词字符串。
    # graph.py 随后调用 llm.ainvoke([SystemMessage(system), *state["messages"]])。
    # 本函数不修改消息历史；下一次 Agent 决策时，会根据最新状态重新组装提示词。
    return "\n\n".join(parts)


# Keep decisions, record IDs, date ranges and confirmed writes; distinguish proposals from facts.
# 保留决策、记录 ID、日期范围和已确认写入，区分提议与事实。
# compact_context 在对话超过预算且存在可压缩的旧轮次时，使用这个模板请求模型生成摘要。
# {summary} 填入之前的摘要，{transcript} 填入这次需要合并的旧消息文本。
# 保留用户目标、偏好、记录 ID、日期范围、工具结果、拒绝操作及待办，去掉闲聊和冗长输出。
# 例如“提议记录 $20”“用户拒绝记录 $20”“工具确认已记录 $20”是三种不同状态，不能混淆。
# 约 200 个词是给模型的长度要求，并非代码强制截断。
# graph.py 将结果写入 state["summary"] 并移除被压缩的旧消息，保留近期轮次原文。
# 摘要在后续通过 build_system_prompt 加回上下文；它是对话压缩，与按用户保存的长期偏好不同。
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
# reflect 节点用此模板请求评审模型检查回答；评审是否执行以及次数上限由 graph.py 控制。
# {question} 是用户问题，{tool_log} 是本轮工具活动，{draft} 是准备给用户的回答。
# 检查金额、币种、日期、百分比与工具证据是否一致，以及声称成功的写入是否真的成功。
# 人工修改过参数时按实际执行结果检查；不能要求重复成功写入，评审也无法撤销已执行的操作。
# 期望输出 JSON：{"verdict": "pass", "feedback": ""} 或
# {"verdict": "revise", "feedback": "金额与工具结果不一致，请修正。"}。
# graph.py 解析结果；若要求 revise 且有反馈，就把草稿和反馈写入 state["critique"]，
# 移除消息历史中的旧草稿并返回 agent，让下一次系统提示词带上修改要求。
# 模板中的 {question} 等是待替换占位符，而 {{ 和 }} 经 .format() 后变成普通的 { 和 }。
# 末行的 "pass" or "revise" 是描述可选值的提示文本，模型实际需选择一个值并输出合法 JSON。
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
