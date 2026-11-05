"""Graph state and per-run context.
📘 LEARN: State changes during a run and is checkpointed. Context identifies the user
and is supplied by the caller on every run/resume; it is not checkpointed.
Nodes return partial updates instead of mutating state.

图状态与单次运行上下文。
📘 LEARN：State 在运行中变化并持久化；Context 标识用户，
由调用方在每次运行或恢复时传入，不保存在检查点中。节点返回局部更新，不直接修改状态。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langgraph.graph import MessagesState


class AgentState(MessagesState):
    """Persisted state shared by graph nodes.
    📘 LEARN: messages inherits the add_messages reducer: append new IDs, replace existing IDs,
    and delete with RemoveMessage. Other fields use last-write-wins.
    ⚠ PITFALL: a new thread may omit fields; use state.get with defaults.
    Iteration/reflection counters and approval decisions reset each user turn.

    图节点共享的持久化状态。
    📘 LEARN：messages 继承 add_messages reducer：新 ID 追加、相同 ID 替换、
    RemoveMessage 删除。其他字段采用后写覆盖。
    ⚠ PITFALL：新会话可能没有某些字段，读取时使用 state.get 默认值。
    循环计数、反思计数和审批决策在每轮用户输入时重置。
    """

    summary: str
    memories: list[str]

    iterations: int
    reflections: int
    loop_warning: str
    critique: dict[str, Any] | None

    hitl_decisions: dict[str, dict[str, Any]]


@dataclass
class AgentContext:
    """Static per-run input, injected through Runtime in nodes and ToolRuntime in tools.
    user_id scopes long-term memories and is never a model-controlled tool argument.

    单次运行的固定输入：节点通过 Runtime 获取，工具通过 ToolRuntime 获取。
    user_id 限定长期记忆的归属，不是模型可以填写的工具参数。
    """

    user_id: str = "default"
