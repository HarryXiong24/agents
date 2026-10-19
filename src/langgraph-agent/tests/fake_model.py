"""A deterministic chat model for offline tests (no Ollama needed).

`responder(messages, tools_bound)` decides what the "LLM" says, so tests can script
exact ReAct trajectories, critic verdicts and summaries.

📘 LEARN — how to test an agent:
    Real LLM output is non-deterministic, so tests that call a real model are flaky
    and slow. Separate two questions:
      • Does the MACHINERY work? (routing, interrupts, budgets, compaction, memory)
        → test with a scripted model. Deterministic, runs in seconds. ← this repo
      • Is the MODEL good at the task? (picks the right tool, answers correctly)
        → evals: a dataset of prompts scored over many runs. A different activity.

    This works because build_graph() only needs a BaseChatModel. Subclassing it and
    implementing `_generate` is enough for `ainvoke` to work; overriding `bind_tools`
    lets the responder know whether tools were offered (to test the forced final answer).
"""

from __future__ import annotations

import uuid
from typing import Any, Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class ScriptedChatModel(BaseChatModel):
    responder: Callable[[list[BaseMessage], bool], AIMessage]
    tools_bound: bool = False
    calls: list = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any):
        return self.model_copy(update={"tools_bound": True})

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.calls.append((messages, self.tools_bound))
        msg = self.responder(messages, self.tools_bound)
        msg = msg.model_copy(update={"id": msg.id or f"ai-{uuid.uuid4().hex[:8]}"})
        return ChatResult(generations=[ChatGeneration(message=msg)])


def tool_call(name: str, args: dict, call_id: str | None = None) -> dict:
    return {"name": name, "args": args, "id": call_id or f"call-{uuid.uuid4().hex[:6]}", "type": "tool_call"}
