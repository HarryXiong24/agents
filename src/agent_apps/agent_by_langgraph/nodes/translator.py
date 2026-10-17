from langchain_openai import ChatOpenAI

from agent_apps.agent_by_langgraph.config import API_KEY, BASE_URL, MODEL_NAME
from agent_apps.agent_by_langgraph.states.state import State


def translator_node(state: State) -> dict:
    model = ChatOpenAI(
        model=MODEL_NAME,
        base_url=BASE_URL,
        api_key=API_KEY,
        use_responses_api=False,
    )
    last = state["messages"][-1].content
    prompt = (
        f"Translate this into Chinese, replying with the translation only:\n\n{last}"
    )
    return {"chinese": model.invoke(prompt).content}
