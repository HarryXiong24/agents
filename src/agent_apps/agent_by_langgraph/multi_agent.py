from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend

from .tools.search import search
from .utils.chat_model import create_model


def multi_deep_agent():
    sandbox = Path(__file__).resolve().parent / "sandbox"
    sandbox.mkdir(parents=True, exist_ok=True)
    model = create_model()

    research_subagent = {
        "name": "vehicle-researcher",
        "description": "Researches a single electric vehicle and returns a short list of facts about it.",
        "system_prompt": """
            You research one electric vehicle using the search tool and return three concise facts
            that a fleet buyer would care about, such as price, range and charging.
        """,
    }

    lead = create_deep_agent(
        model=model,
        tools=[search],
        system_prompt="""
            You write comparison briefings for a company choosing electric vehicles for its sales fleet.
            For each vehicle, delegate the research to your vehicle-researcher sub-agent,
            then write a markdown comparison to a file, ending with a clear recommendation.

            " Use at most two web searches, then write a briefing of at most 350 words."
            " State evidence limitations instead of continuing to search."
        """,
        subagents=[research_subagent],
        backend=FilesystemBackend(root_dir=str(sandbox), virtual_mode=True),
    )

    result = lead.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": """
    Compare the Tesla Model Y and the Ford Mustang Mach-E as candidates for our 100-car sales fleet.
    Research each vehicle, then write a short markdown comparison with a recommendation to fleet.md.
    """,
                }
            ]
        }
    )
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
