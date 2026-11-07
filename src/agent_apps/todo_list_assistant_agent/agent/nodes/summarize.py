"""Implement the summarize node, preserving recent tool exchanges during compression."""

import json
from collections.abc import Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.messages.utils import count_tokens_approximately

from ...config import AgentConfig
from ..prompts import SUMMARY_PROMPT
from ..state import AgentState


class SummaryError(ValueError):
    """An invalid summary must not replace the original conversation messages."""


class SummarizeNode:
    """Keep the base model and shared settings separate from conversation State."""

    def __init__(self, model: BaseChatModel, agent_config: AgentConfig) -> None:
        self._model = model
        self._agent_config = agent_config

    def summarize(self, state: AgentState) -> dict:
        """Check whether older conversation turns should be compressed."""
        return summarize_conversation(state, self._model, self._agent_config)


def estimate_history_tokens(messages: Sequence[BaseMessage], summary: str = "") -> int:
    """Estimate history only; exclude system instructions, todo data, and schemas."""
    history = [SystemMessage(content=summary), *messages] if summary else messages
    return count_tokens_approximately(history)


def older_messages_to_summarize(
    messages: Sequence[BaseMessage], summary_keep_turns: int
) -> list[BaseMessage]:
    """Select a prefix of completed turns; never split tool requests and results."""
    if not messages or not isinstance(messages[-1], HumanMessage):
        return []
    starts = [
        i for i, message in enumerate(messages) if isinstance(message, HumanMessage)
    ]
    # The final HumanMessage starts the current, unfinished turn.
    if len(starts) <= summary_keep_turns + 1:
        return []
    older = list(messages[: starts[-(summary_keep_turns + 1)]])
    if not isinstance(older[-1], AIMessage) or older[-1].tool_calls:
        return []

    pending: set[str] = set()
    for message in older:
        if isinstance(message, AIMessage):
            if pending or message.invalid_tool_calls:
                return []
            for call in message.tool_calls:
                call_id = call["id"]
                if not call_id or call_id in pending:
                    return []
                pending.add(call_id)
        elif isinstance(message, ToolMessage):
            if message.tool_call_id not in pending:
                return []
            pending.remove(message.tool_call_id)
        elif isinstance(message, HumanMessage) and pending:
            return []
    return [] if pending else older


def summarize_conversation(
    state: AgentState, model: BaseChatModel, config: AgentConfig
) -> dict:
    """Return an atomic summary/message update only after successful generation."""
    messages = state["messages"]
    previous_summary = state.get("summary", "")
    if (
        estimate_history_tokens(messages, previous_summary)
        < config.summary_trigger_tokens
    ):
        return {}
    older = older_messages_to_summarize(messages, config.summary_keep_turns)
    if not older:
        return {}
    if any(message.id is None for message in older):
        raise SummaryError("Cannot summarize messages without persistent IDs.")

    # Serialize tool exchanges as data rather than sending executable tool messages
    # to the summarizer. No tool binding or live todo database is used here.
    transcript = []
    for message in older:
        entry: dict[str, Any] = {"role": message.type, "content": message.content}
        if isinstance(message, AIMessage) and message.tool_calls:
            entry["tool_calls"] = message.tool_calls
        if isinstance(message, ToolMessage):
            entry["tool_call_id"] = message.tool_call_id
            entry["status"] = message.status
        transcript.append(entry)
    payload = json.dumps(
        {"previous_summary": previous_summary, "older_messages": transcript},
        ensure_ascii=False,
    )
    response = model.invoke([SystemMessage(SUMMARY_PROMPT), HumanMessage(payload)])
    if (
        not isinstance(response, AIMessage)
        or response.tool_calls
        or response.invalid_tool_calls
    ):
        raise SummaryError(
            "The summary model must return plain text without tool calls."
        )
    if response.response_metadata.get("finish_reason") in {"length", "max_tokens"}:
        raise SummaryError(
            "Summary generation was truncated. Original messages were kept."
        )
    summary = response.text.strip()
    if not summary:
        raise SummaryError("The summary model returned empty text.")
    if estimate_history_tokens([], summary) >= estimate_history_tokens(
        older, previous_summary
    ):
        # A long current/recent turn can trigger this check even when the older
        # prefix is tiny. Keep the old state and continue answering instead of
        # leaving the conversation stuck retrying an unhelpful summary.
        return {}

    # add_messages applies these removals to the current state. Older checkpoints
    # are retained; this is context compression, not database-file compaction.
    removals = [
        RemoveMessage(id=message.id) for message in older if message.id is not None
    ]
    return {"summary": summary, "messages": removals}
