"""Build the standard agent loop and compose its application middleware."""

from collections.abc import Mapping, Sequence
from typing import Any, cast

from langchain.agents import create_agent
from langchain.agents.middleware import (
    HumanInTheLoopMiddleware,
    SummarizationMiddleware,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from ..config import agent as agent_settings
from .mcp import approval_names
from .middleware import (
    ContextMiddleware,
    DraftPresentationMiddleware,
    HistoryMiddleware,
    SkillsMiddleware,
    ToolExecutionMiddleware,
    TurnControlMiddleware,
)
from .prompts import SUMMARY_PROMPT, SYSTEM_PROMPT
from .skills import Skill
from .state import AgentState
from .tools import create_tools

AgentGraph = CompiledStateGraph[AgentState, None, AgentState, Any]


def build_agent(
    model: BaseChatModel,
    checkpointer: BaseCheckpointSaver | None = None,
    *,
    skills: Mapping[str, Skill] | None = None,
    mcp_tools: Sequence[BaseTool] = (),
) -> AgentGraph:
    """Delegate nodes/edges to create_agent; fixed resources are bound only here."""
    settings = agent_settings.AGENT_CONFIG
    skills = dict(skills or {})
    # MCP tools are external; each server's tools pause for approval by default.
    approval = (*settings.approval_tools, *approval_names(list(mcp_tools)))
    # Middleware hook order:
    # - before_*: earlier in the list runs first.
    # - after_*: later in the list runs first.
    # - wrap_*: earlier in the list is the outer layer; enters first, exits last.
    # Only middleware implementing the corresponding hook participates.
    # TurnControl.after_model checks a batch before HITL can pause it.
    # Context is outside Skills: Context sets the system message, then Skills
    # appends the catalog and active instructions to it.
    middleware = [
        HumanInTheLoopMiddleware(
            interrupt_on={
                name: {"allowed_decisions": ["approve", "reject"]} for name in approval
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
        SkillsMiddleware(skills),
        ToolExecutionMiddleware(),
        DraftPresentationMiddleware(),
    ]
    compiled = create_agent(
        model=model,
        tools=[*create_tools(model, skills), *mcp_tools],
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
