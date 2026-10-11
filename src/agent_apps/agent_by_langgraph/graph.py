from langgraph.graph import END, START, StateGraph

from agent_apps.agent_by_langgraph.node.chatbot import chatbot_node
from agent_apps.agent_by_langgraph.node.silly_node import silly_node
from agent_apps.agent_by_langgraph.state.state import State


def initGraph():
    builder = StateGraph(State)
    builder.add_node("silly", silly_node)
    builder.add_edge(START, "silly")
    builder.add_edge("silly", END)
    graph = builder.compile()

    result = graph.invoke(State({"messages": [{"role": "user", "content": "Hello"}]}))
    print(result["messages"][-1].content)

    builder = StateGraph(State)
    builder.add_node("chatbot", chatbot_node)
    builder.add_edge(START, "chatbot")
    builder.add_edge("chatbot", END)
    graph = builder.compile()

    result = graph.invoke(
        State(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": "What is a directed graph, in one sentence?",
                    }
                ]
            }
        )
    )
    print(result["messages"][-1].content)
