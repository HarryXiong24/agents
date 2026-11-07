"""Build a ReAct graph with summaries, tool records, and an optional draft branch."""

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from ..config import agent as agent_settings
from .middleware import handle_tool_error, tool_call_middleware
from .nodes.draft import DraftNode
from .nodes.model import ModelNode, route_after_model
from .nodes.summarize import SummarizeNode
from .nodes.tools import ToolsNode, route_after_tools
from .state import AgentState
from .tools import TOOLS


def build_graph(
    model: BaseChatModel,
    checkpointer: BaseCheckpointSaver | None = None,
):
    """Bind fixed dependencies once and compile a checkpoint-aware ReAct loop."""
    agent_config = agent_settings.AGENT_CONFIG
    # Node objects hold fixed resources; conversation data remains in AgentState.
    model_node = ModelNode(model.bind_tools(TOOLS))
    summary_node = SummarizeNode(model, agent_config)
    draft_node = DraftNode(model)
    tools_node = ToolsNode(
        ToolNode(
            TOOLS,
            handle_tool_errors=handle_tool_error,
            wrap_tool_call=tool_call_middleware,
        )
    )

    # Init graph
    graph = StateGraph(AgentState)

    # Nodes
    graph.add_node("summarize", summary_node.summarize)
    graph.add_node("model", model_node.model)
    graph.add_node("tools", tools_node.tools)
    graph.add_node("draft", draft_node.draft)

    # Check once per new user turn; never summarize inside an active tool loop.
    # Edges
    graph.add_edge(START, "summarize")
    graph.add_edge("summarize", "model")
    graph.add_conditional_edges("model", route_after_model, ["tools", END])
    graph.add_conditional_edges("tools", route_after_tools, ["model", "draft"])
    graph.add_edge("draft", END)

    # Restore and save state by thread_id when a checkpointer is supplied.
    # Keeping it optional lets isolated graph tests run without persistent state.
    # Bind a default for direct invocations and the console; callers may override it.
    return graph.compile(checkpointer=checkpointer).with_config(
        {"recursion_limit": agent_config.recursion_limit}
    )
