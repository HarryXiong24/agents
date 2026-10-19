import os

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain_community.tools import GoogleSerperRun
from langchain_community.utilities import GoogleSerperAPIWrapper
from langchain_ollama import ChatOllama

from .config import (
    DEEP_AGENT_MODEL,
    DEEP_AGENT_NUM_CTX,
    DEEP_AGENT_NUM_PREDICT,
    DEEP_AGENT_REASONING,
    SERPER_API_KEY,
)


def multi_deep_agent():
    sandbox = os.path.abspath("sandbox")
    os.makedirs(sandbox, exist_ok=True)
    search = GoogleSerperRun(
        api_wrapper=GoogleSerperAPIWrapper(serper_api_key=SERPER_API_KEY, k=3)
    )
    model = ChatOllama(
        model=DEEP_AGENT_MODEL,
        base_url="http://localhost:11434",
        num_ctx=DEEP_AGENT_NUM_CTX,
        num_predict=DEEP_AGENT_NUM_PREDICT,
        reasoning={"true": True, "false": False}.get(
            DEEP_AGENT_REASONING.lower(), DEEP_AGENT_REASONING
        ),
        keep_alive="1m",
    )

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
        """,
        subagents=[research_subagent],
        backend=FilesystemBackend(root_dir=sandbox, virtual_mode=True),
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
