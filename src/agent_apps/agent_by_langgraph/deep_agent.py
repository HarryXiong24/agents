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


def deep_agent():
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
        backend=FilesystemBackend(root_dir=sandbox, virtual_mode=True),
    )

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
    result = researcher.invoke(inputs)
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
