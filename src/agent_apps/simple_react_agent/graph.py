"""Version 5: add rolling summaries before the existing model/tool ReAct loop."""

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from . import memory
from .config import SummaryConfig
from .prompts import TOOL_ERROR_MESSAGE, build_system_prompt
from .state import AgentState
from .summarization import summarize_conversation
from .tools import TOOLS


def build_graph(
    model: BaseChatModel,
    checkpointer: BaseCheckpointSaver | None = None,
    summary_config: SummaryConfig | None = None,
):
    """Keep summaries in graph state and use the base model without tools for them."""
    summary_config = summary_config or SummaryConfig()
    # Expose tool schemas to the model. Binding does not execute any tools.
    model_with_tools = model.bind_tools(TOOLS)

    # A node returns a partial state update.
    def call_model(state: AgentState):
        # Version 3: query SQLite before every model call, including after writes.
        # Putting the records in the prompt makes them available to the model.
        todos = memory.load_todos()
        system = build_system_prompt(todos, state.get("summary", ""))
        # Send system instructions with each request without appending to history.
        response = model_with_tools.invoke([SystemMessage(system), *state["messages"]])
        # MessagesState appends new message IDs and replaces matching IDs.
        return {"messages": [response]}

    # A conditional router returns the next node's name.
    def route_after_model(state: AgentState):
        # Execute requested tools; otherwise this turn is complete.
        last_message = state["messages"][-1]
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            return "tools"
        return END

    def summarize(state: AgentState):
        return summarize_conversation(state, model, summary_config)

    graph = StateGraph(AgentState)
    graph.add_node("summarize", summarize)
    graph.add_node("model", call_model)
    graph.add_node(
        "tools",
        ToolNode(TOOLS, handle_tool_errors=TOOL_ERROR_MESSAGE),
    )

    # Check once per new user turn; never summarize inside an active tool loop.
    graph.add_edge(START, "summarize")
    graph.add_edge("summarize", "model")
    graph.add_conditional_edges("model", route_after_model, ["tools", END])
    graph.add_edge("tools", "model")

    # Version 4: restore and save state by thread_id when a checkpointer is supplied.
    # Keeping it optional lets isolated graph tests run without persistent state.
    return graph.compile(checkpointer=checkpointer)
