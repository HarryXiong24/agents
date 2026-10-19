"""Prompt templates. The system prompt is rebuilt on every agent step (context engineering).

📘 LEARN — context engineering = deciding exactly what goes into the model's context
window on each call. The window is the model's entire "working memory"; anything not in
it does not exist for the model, and irrelevant content dilutes attention.

On each `agent` step we assemble:

    ┌───────────────────────────── system prompt ─────────────────────────────┐
    │ BASE_SYSTEM            role, ReAct rules, tool etiquette, current time  │
    │ + summary              compacted earlier conversation      (if any)     │
    │ + memories             long-term facts about this user     (if any)     │
    │ + loop warning         from loop_guard                     (if any)     │
    │ + revision request     draft + critic feedback             (if any)     │
    │ + budget notice        steps left / "no tools left"        (if needed)  │
    └──────────────────────────────────────────────────────────────────────────┘
    + recent messages (Human / AI / Tool) from state
    + tool schemas (added by bind_tools)

Each section appears only when it has content, so the prompt stays short by default.
"""

from __future__ import annotations

from datetime import datetime

# 📘 LEARN: The base prompt encodes the ReAct contract in plain words. Native function
# calling means we don't need the old "Thought: / Action: / Observation:" text format —
# the model emits structured tool_calls and the framework handles parsing.
BASE_SYSTEM = """You are Atlas, a workspace assistant running in a terminal.
You help the user manage notes and files in their workspace, do calculations,
run shell commands, and remember things about them across sessions.

How you work (ReAct):
- Think about what is needed, then either call ONE OR MORE tools or give the final answer.
- After each tool result, decide again: call another tool, or answer.
- Prefer tools over guessing. Never invent file contents or tool results.
- If the request is ambiguous and a wrong guess would be costly, call `ask_human`.
- When the user tells you a durable fact or preference about themselves, call `save_memory`.
- Some tools (shell, writing/deleting files) require human approval. If a call is
  rejected, respect the reason and adapt; do not retry the same call.
- Final answers: concise, plain text, no tool-call syntax.

Current time: {now}"""


def build_system_prompt(state: dict, *, remaining_steps: int, tools_enabled: bool) -> str:
    """Assemble the per-step system prompt from graph state (see module docstring)."""
    parts = [BASE_SYSTEM.format(now=datetime.now().strftime("%Y-%m-%d %H:%M"))]

    # Memory layer 2 (compaction): what the deleted messages said.
    if state.get("summary"):
        parts.append(f"## Summary of earlier conversation\n{state['summary']}")

    # Memory layer 3 (long-term): facts recalled by prepare_turn. The [id] prefix lets the
    # model reference a memory precisely, e.g. delete_memory("a1b2c3d4").
    if state.get("memories"):
        mem = "\n".join(f"- {m}" for m in state["memories"])
        parts.append(f"## What you remember about this user (long-term memory)\n{mem}")

    # Loop engineering layer 4: steering message from loop_guard.
    if state.get("loop_warning"):
        parts.append(f"## ⚠ Loop guard\n{state['loop_warning']}")

    # Reflection loop: the removed draft + critic feedback, framed as a rewrite task.
    critique = state.get("critique")
    if critique:
        parts.append(
            "## Revision requested\n"
            f"Your previous draft answer was:\n<draft>\n{critique['draft']}\n</draft>\n"
            f"A reviewer gave this feedback:\n{critique['feedback']}\n"
            "Fix the issues (use tools if needed) and give an improved final answer."
        )

    # Loop engineering layers 1 & 2: budget awareness and the forced final answer.
    # Telling the model WHY it has no tools avoids confused "I'll call X now" replies.
    if not tools_enabled:
        parts.append(
            "## Step budget exhausted\nYou have no tool calls left. Give your best final "
            "answer now from what you already know, and say what is still unfinished."
        )
    elif remaining_steps <= 2:
        parts.append(f"## Step budget\nOnly {remaining_steps} step(s) left. Wrap up soon.")

    return "\n\n".join(parts)


# 📘 LEARN: The summariser prompt says what to KEEP (decisions, file names, results, open
# tasks) as much as what to drop. A vague "summarise this" loses exactly the details an
# agent needs later, such as which file it already wrote.
SUMMARIZE_PROMPT = """Compress the conversation below into a short running summary for your own future reference.
Keep: user goals, decisions, facts learned, file names, results of tool calls, open tasks.
Drop: chit-chat and verbose tool output. Max ~200 words.

Existing summary (may be empty):
{summary}

New messages to fold in:
{transcript}

Updated summary:"""


# 📘 LEARN: The critic gets the TOOL LOG, not just the answer — the most common agent
# error is an answer that contradicts what the tools returned (hallucinated results).
# A binary verdict + short feedback keeps the output easy to parse with small models.
# (Double braces {{ }} are literal braces in str.format.)
CRITIC_PROMPT = """You are a strict reviewer of an AI assistant's answer.

User request:
{question}

Tool activity during this turn:
{tool_log}

Assistant's draft answer:
{draft}

Does the draft fully and correctly answer the request, consistent with the tool results,
without fabricating anything? Reply with JSON only:
{{"verdict": "pass" or "revise", "feedback": "<one or two sentences; empty if pass>"}}"""
