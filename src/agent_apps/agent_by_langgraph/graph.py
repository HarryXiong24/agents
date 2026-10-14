from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from agent_apps.agent_by_langgraph.node.chatbot import chatbot_node
from agent_apps.agent_by_langgraph.node.silly_node import silly_node
from agent_apps.agent_by_langgraph.node.translator import translator_node
from agent_apps.agent_by_langgraph.state.state import State
from agent_apps.agent_by_langgraph.tool.search import search


def init_graph_basic():
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


def init_graph_with_tools():
    tools = [search]
    builder = StateGraph(State)

    builder.add_node("chatbot", chatbot_node)
    builder.add_node("tools", ToolNode(tools))

    # Assuming ToolNode is defined elsewhere
    builder.add_edge(START, "chatbot")
    builder.add_conditional_edges("chatbot", tools_condition)
    builder.add_edge("tools", "chatbot")

    graph = builder.compile()

    result = graph.invoke(
        State(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": "Use your search tool to tell me what is today's date in New York City, in one sentence.",
                    }
                ]
            }
        )
    )
    print(result["messages"][-1].content)


def init_graph_with_second_node():
    tools = [search]
    builder = StateGraph(State)

    builder.add_node("chatbot", chatbot_node)
    builder.add_node("tools", ToolNode(tools))
    builder.add_node("translator", translator_node)

    builder.add_edge(START, "chatbot")
    builder.add_conditional_edges(
        "chatbot", tools_condition, {"tools": "tools", END: "translator"}
    )
    builder.add_edge("tools", "chatbot")
    builder.add_edge("translator", END)

    graph = builder.compile()

    result = graph.invoke(
        State(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": "Use your search tool to tell me what is today's date in New York City, in one sentence.",
                    }
                ]
            }
        )
    )
    print(result["messages"][-1].content, "\n", result["chinese"])
