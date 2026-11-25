"""Small fake-model helpers; execute real graph nodes, tools and checkpoints."""

from typing import Any
from unittest.mock import Mock

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from agent_apps.todo_list_assistant_agent.agent.state import AgentState

CONFIG: RunnableConfig = {"configurable": {"thread_id": "offline"}}
TODO: dict[str, Any] = {"project": "Python", "minutes": 30, "date": "2026-11-15"}


def make_model(*, responses=()):
    model = Mock(spec=BaseChatModel)
    model.bind_tools.return_value = model
    model.invoke.side_effect = list(responses)
    return model


def ask(text="Hello") -> AgentState:
    return {
        "messages": [HumanMessage(text)],
        "model_calls_this_turn": 0,
        "tool_calls_this_turn": 0,
    }


def call(name, args=None, id="call"):
    return {"name": name, "args": args or {}, "id": id}
