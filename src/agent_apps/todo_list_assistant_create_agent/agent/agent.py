"""Build the standard agent loop and compose its application middleware."""

from typing import Any, cast

from langchain.agents import create_agent
from langchain.agents.middleware import (
    HumanInTheLoopMiddleware,
    SummarizationMiddleware,
)
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from ..config import agent as agent_settings
from .middleware import (
    ContextMiddleware,
    DraftPresentationMiddleware,
    HistoryMiddleware,
    ToolExecutionMiddleware,
    TurnControlMiddleware,
)
from .prompts import SUMMARY_PROMPT, SYSTEM_PROMPT
from .state import AgentState
from .tools import create_tools

AgentGraph = CompiledStateGraph[AgentState, None, AgentState, Any]


def build_agent(
    model: BaseChatModel, checkpointer: BaseCheckpointSaver | None = None
) -> AgentGraph:
    """Delegate nodes/edges to create_agent; fixed resources are bound only here."""
    settings = agent_settings.AGENT_CONFIG
    # Middleware hook order:
    # - before_*: earlier in the list runs first.
    # - after_*: later in the list runs first.
    # - wrap_*: earlier in the list is the outer layer; enters first, exits last.
    # Only middleware implementing the corresponding hook participates.
    # TurnControl.after_model checks a batch before HITL can pause it.
    middleware = [
        HumanInTheLoopMiddleware(
            interrupt_on={
                name: {"allowed_decisions": ["approve", "reject"]}
                for name in settings.approval_tools
            }
        ),
        TurnControlMiddleware(settings),
        HistoryMiddleware(),
        SummarizationMiddleware(
            model=model,
            trigger=("tokens", settings.summary_trigger_tokens),
            keep=("messages", settings.summary_keep_messages),
            summary_prompt=SUMMARY_PROMPT,
        ),
        ContextMiddleware(),
        ToolExecutionMiddleware(),
        DraftPresentationMiddleware(),
    ]
    compiled = create_agent(
        model=model,
        tools=create_tools(model),
        system_prompt=SYSTEM_PROMPT,
        state_schema=AgentState,
        middleware=middleware,
        checkpointer=checkpointer,
        name="todo_list_assistant_create_agent",
    )
    # The factory's generic return annotation keeps its default input type even
    # with a custom state_schema. Expose the schema actually used by this graph.
    return cast(AgentGraph, compiled).with_config(
        {"recursion_limit": settings.recursion_limit}
    )
