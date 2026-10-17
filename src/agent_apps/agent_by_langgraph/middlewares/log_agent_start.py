from langchain.agents.middleware import AgentState, before_agent
from langgraph.runtime import Runtime


@before_agent
def log_agent_start(state: AgentState, runtime: Runtime) -> None:
    """Run once at the start of each invocation, including follow-up turns."""
    print(f"  [middleware] agent starting with {len(state['messages'])} messages")
