"""Build a ReAct graph with rolling summaries and recent tool execution records."""

from datetime import datetime

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from ..config import agent as agent_settings
from . import memory
from .middleware import wrap_tool_call
from .prompts import TOOL_ERROR_MESSAGE, build_system_prompt
from .state import AgentState, ToolCallRecord
from .summarization import summarize_conversation
from .tools import TOOLS, get_tool_history


def build_graph(
    model: BaseChatModel,
    checkpointer: BaseCheckpointSaver | None = None,
):
    """Keep summaries in graph state and use the base model without tools for them."""
    agent_config = agent_settings.AGENT_CONFIG
    # Expose tool schemas to the model. Binding does not execute any tools.
    model_with_tools = model.bind_tools(TOOLS)
    tool_node = ToolNode(
        TOOLS,
        handle_tool_errors=TOOL_ERROR_MESSAGE,
        # Observe each individual call; call_tools still produces State updates.
        wrap_tool_call=wrap_tool_call,
    )

    # A node returns a partial state update.
    def call_model(state: AgentState):
        # Query SQLite before every model call, including after writes.
        # Putting the records in the prompt makes them available to the model.
        todos = memory.load_todos()
        system = build_system_prompt(todos, state.get("summary", ""))
        # Send system instructions with each request without appending to history.
        response = model_with_tools.invoke([SystemMessage(system), *state["messages"]])
        # MessagesState appends new message IDs and replaces matching IDs.
        return {"messages": [response]}

    def call_tools(state: AgentState, config: RunnableConfig):
        """Execute tools and return their messages alongside new history records."""
        request = state["messages"][-1]
        if not isinstance(request, AIMessage):
            raise TypeError("The tool node requires an AIMessage with tool calls.")

        # Keep ToolNode's execution and error handling; forward the graph's config.
        updates = tool_node.invoke(state, config=config)
        tool_messages: list[ToolMessage] = updates["messages"]
        # Match by call ID because one model reply can request several tools.
        calls_by_id = {call["id"]: call for call in request.tool_calls}
        records: list[ToolCallRecord] = []
        for message in tool_messages:
            call = calls_by_id[message.tool_call_id]
            # Keep lookup results in messages, but avoid nesting history inside itself.
            if call["name"] == get_tool_history.name:
                continue
            records.append(
                {
                    "tool_name": call["name"],
                    "tool_args": dict(call["args"]),
                    # Record the actual output, including handled error messages.
                    "result": message.text,
                    # This is the record creation time, with the local UTC offset.
                    "timestamp": datetime.now().astimezone().isoformat(),
                }
            )

        # Each field has its own reducer: messages merge by ID, history is bounded.
        # Return only this batch; returning old history too would duplicate it.
        return {"messages": tool_messages, "tool_history": records}

    # A conditional router returns the next node's name.
    def route_after_model(state: AgentState):
        # Execute requested tools; otherwise this turn is complete.
        last_message = state["messages"][-1]
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            return "tools"
        return END

    def summarize(state: AgentState):
        return summarize_conversation(state, model, agent_config)

    # init graph
    graph = StateGraph(AgentState)
    graph.add_node("summarize", summarize)
    graph.add_node("model", call_model)
    graph.add_node("tools", call_tools)

    # Check once per new user turn; never summarize inside an active tool loop.
    graph.add_edge(START, "summarize")
    graph.add_edge("summarize", "model")
    graph.add_conditional_edges("model", route_after_model, ["tools", END])
    graph.add_edge("tools", "model")

    # Restore and save state by thread_id when a checkpointer is supplied.
    # Keeping it optional lets isolated graph tests run without persistent state.
    # Bind a default for direct invocations and the console; callers may override it.
    return graph.compile(checkpointer=checkpointer).with_config(
        {"recursion_limit": agent_config.recursion_limit}
    )
