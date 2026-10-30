"""Build the two-node ReAct graph independently of the console entry point."""

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from . import memory
from .prompts import TOOL_ERROR_MESSAGE, build_system_prompt
from .tools import TOOLS


def build_graph(model: BaseChatModel):
    """Block 3: build a ReAct loop with a model node and a tool node."""
    # Expose tool schemas to the model. Binding does not execute any tools.
    model_with_tools = model.bind_tools(TOOLS)

    # A node returns a partial state update.
    def call_model(state: MessagesState):
        # Version 3: query SQLite before every model call, including after writes.
        # Putting the records in the prompt makes them available to the model.
        plans = memory.load_plans()
        system = build_system_prompt(plans)
        # Send system instructions with each request without appending to history.
        response = model_with_tools.invoke([SystemMessage(system), *state["messages"]])
        # MessagesState appends new message IDs and replaces matching IDs.
        return {"messages": [response]}

    # A conditional router returns the next node's name.
    def route_after_model(state: MessagesState):
        # Execute requested tools; otherwise this turn is complete.
        last_message = state["messages"][-1]
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            return "tools"
        return END

    graph = StateGraph(MessagesState)
    graph.add_node("model", call_model)
    graph.add_node(
        "tools",
        ToolNode(TOOLS, handle_tool_errors=TOOL_ERROR_MESSAGE),
    )

    graph.add_edge(START, "model")
    graph.add_conditional_edges("model", route_after_model, ["tools", END])
    graph.add_edge("tools", "model")

    # The console explicitly keeps and supplies history; no checkpointer is used.
    return graph.compile()
