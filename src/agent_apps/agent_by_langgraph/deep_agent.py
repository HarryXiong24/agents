from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langgraph.checkpoint.memory import MemorySaver

from .tools.search import search
from .utils.chat_model import create_model


def deep_agent():
    sandbox = Path(__file__).resolve().parent / "sandbox"
    sandbox.mkdir(parents=True, exist_ok=True)
    model = create_model()

    researcher = create_deep_agent(
        model=model,
        tools=[search],
        system_prompt=(
            "You are a research analyst. Plan your work with your todo tool, "
            "research with the search tool, and write your findings as a tidy markdown briefing to a file."
            " This is a short local test: do the work yourself without delegating to subagents."
            " Use at most two web searches, then write a briefing of at most 350 words."
            " State evidence limitations instead of continuing to search."
        ),
        checkpointer=MemorySaver(),
        backend=FilesystemBackend(root_dir=str(sandbox), virtual_mode=True),
    )

    config = {"configurable": {"thread_id": "deep-agent"}}
    inputs = {
        "messages": [
            {
                "role": "user",
                "content": """
                    Our company is planning to move its sales fleet to electric vehicles.
                    Research the public EV charging landscape in the US: find out roughly how many public charging points there are,
                    and pick out two major charging networks a fleet could rely on.
                    Write a one page markdown briefing, with a heading and a short section for each, to the file charging.md.
                """,
            }
        ]
    }
    result = researcher.invoke(inputs, config)
    print(result["messages"][-1].content)
    print_tools(result)


def print_tools(result):
    tools_used = [
        call["name"]
        for message in result["messages"]
        for call in (getattr(message, "tool_calls", []) or [])
    ]
    print("Tools the agent called, in order:")
    print(tools_used)
