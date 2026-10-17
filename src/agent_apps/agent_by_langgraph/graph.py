from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from agent_apps.agent_by_langgraph.nodes.chatbot import chatbot_node
from agent_apps.agent_by_langgraph.nodes.silly_node import silly_node
from agent_apps.agent_by_langgraph.nodes.translator import translator_node
from agent_apps.agent_by_langgraph.states.state import State
from agent_apps.agent_by_langgraph.tools.search import search
from agent_apps.agent_by_langgraph.utils.print_graph import print_graph


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
    print_graph(graph.get_graph())

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
    print_graph(graph.get_graph())

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
    print_graph(graph.get_graph())

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


def init_graph_with_memory():
    memory = MemorySaver()
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

    graph = builder.compile(checkpointer=memory)
    print_graph(graph.get_graph())

    config = {"configurable": {"thread_id": "conversation-1"}}
    graph.invoke(
        State(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": "Hello there! My name is Harry.",
                    }
                ]
            }
        ),
        config,
    )
    result = graph.invoke(
        {"messages": [{"role": "user", "content": "What is my name?"}]}, config
    )
    print(result["messages"][-1].content, "\n", result["chinese"])

    # Check the state of the graph after the invocations
    print("------ Checking graph state ---")
    snapshot = graph.get_state(config)
    messages = snapshot.values["messages"]
    print("Messages stored so far:", len(messages))

    for message in messages:
        print(message.content)

    # Check the history of the graph
    print("------ Checking graph history ---")
    history = list(graph.get_state_history(config))
    print("Number of saved checkpoints:", len(history))

    for h in reversed(history):  # history is newest first; reversed reads as a story
        m = h.metadata
        queued = ", ".join(t.name for t in h.tasks) or "(run complete)"
        print(
            f"step {m['step']:>2}  {m['source']:<5}  messages={len(h.values.get('messages', []))}  about to run: {queued}"
        )

    # Time travel: take a checkpoint from earlier and resume the graph from that exact moment
    print("------ Time travel: resuming from an earlier checkpoint ---")
    # history is newest first, so the last one is the earliest checkpoint
    earlier = history[-1]
    print(
        "A checkpoint from earlier held",
        len(earlier.values["messages"]),
        "messages",
    )

    replay_config = {
        "configurable": {
            "thread_id": "conversation-1",
            "checkpoint_id": earlier.config["configurable"]["checkpoint_id"],
        }
    }

    # passing None means "resume from the checkpoint, but don't add any new messages yet"
    resumed = graph.invoke(None, replay_config)
    print(
        "Resumed from the past; the graph now holds",
        len(resumed["messages"]),
        "messages",
        resumed["messages"][-1].content,
    )

    # Passing a new message means "resume from the checkpoint, and add this new message to the conversation"
    again = graph.invoke(
        {"messages": [{"role": "user", "content": "What is my name?"}]},
        replay_config,
    )
    print(again["messages"][-1].content)
    print(again["chinese"])
