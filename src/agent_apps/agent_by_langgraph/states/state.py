from typing import NotRequired

from langgraph.graph import MessagesState


class State(MessagesState):
    chinese: NotRequired[str]
