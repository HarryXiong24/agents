from langchain.agents.middleware import AgentState, after_model
from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime


@after_model
def log_model_response(state: AgentState, runtime: Runtime) -> None:
    """Inspect the latest model response without changing agent state."""
    message = state["messages"][-1]
    if isinstance(message, AIMessage):
        print(f"  [middleware] after model: {len(message.tool_calls)} tool calls")
        if message.usage_metadata:
            print(f"  [middleware] token usage: {message.usage_metadata}")
