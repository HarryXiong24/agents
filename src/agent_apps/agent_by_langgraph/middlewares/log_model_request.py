from langchain.agents.middleware import AgentState, before_model
from langgraph.runtime import Runtime


@before_model
def log_model_request(state: AgentState, runtime: Runtime) -> None:
    """Run before every model call, including calls after tool execution."""
    print(f"  [middleware] before model: {len(state['messages'])} messages")
