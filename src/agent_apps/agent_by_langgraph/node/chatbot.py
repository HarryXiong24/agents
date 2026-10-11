from langchain_openai import ChatOpenAI

from agent_apps.agent_by_langgraph.config import API_KEY, BASE_URL, MODEL_NAME
from agent_apps.agent_by_langgraph.state.state import State


def chatbot_node(state: State) -> dict:
    model = ChatOpenAI(
        model=MODEL_NAME,
        base_url=BASE_URL,
        api_key=API_KEY,
        use_responses_api=False,
    )
    return {"messages": [model.invoke(state["messages"])]}
