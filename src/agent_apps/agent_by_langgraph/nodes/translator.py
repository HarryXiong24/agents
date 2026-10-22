from agent_apps.agent_by_langgraph.states.state import State
from agent_apps.agent_by_langgraph.utils.chat_model import create_model


def translator_node(state: State) -> dict:
    model = create_model()
    last = state["messages"][-1].content
    prompt = (
        f"Translate this into Chinese, replying with the translation only:\n\n{last}"
    )
    return {"chinese": model.invoke(prompt).content}
