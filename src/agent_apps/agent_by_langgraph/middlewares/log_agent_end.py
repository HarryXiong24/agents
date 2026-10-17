from langchain.agents.middleware import AgentState, after_agent
from langgraph.runtime import Runtime


@after_agent
def log_agent_end(state: AgentState, runtime: Runtime) -> None:
    """Run once after the agent completes successfully."""
    print(f"  [middleware] agent finished with {len(state['messages'])} messages")
    if state.get("structured_response") is not None:
        print("  [middleware] structured response is ready")
