"""A deterministic chat model for offline tests (no Groq API access needed).

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

用于离线测试的确定性聊天模型，无需 Groq API。
responder(messages, tools_bound) 决定模型响应，从而精确安排 ReAct 轨迹、反思结论和摘要。

📘 LEARN：Agent 测试要区分两个问题：
  • 机制是否正确（路由、中断、预算、压缩、记忆）：用脚本模型，运行快且结果确定。
  • 真实模型是否擅长任务（工具选择和回答质量）：用评估数据集多次运行，单独评估。
build_graph 只依赖 BaseChatModel；实现 _generate 即可让 ainvoke 工作，
覆盖 bind_tools 则让脚本知道是否提供了工具，用于验证预算耗尽后的最终回答。
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
