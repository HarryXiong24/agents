from agent_apps.agent_by_langgraph.states.state import State
from agent_apps.agent_by_langgraph.tools.search import search
from agent_apps.agent_by_langgraph.utils.chat_model import create_model


def chatbot_node(state: State) -> dict:
    model = create_model()
    model = model.bind_tools([search])
    return {"messages": [model.invoke(state["messages"])]}
