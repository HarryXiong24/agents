"""A digital twin chat agent with tool calling, built without an agent framework.

Packaged from demo3.ipynb. To use it from Python or a notebook:

    from agents.resume_digging_agent import Agent

    # Blocking: chat returns the finished answer as a string.
    agent = Agent(stream=False)
    print(agent.chat("Please tell me about yourself"))

    # Streaming (the default): chat yields the answer so far, over and over.
    agent = Agent()
    for reply in agent.chat("Please tell me about yourself"):
        print(reply, end="\r")

To launch the web UI, run `uv run resume-digging-agent`, or the same thing via
`uv run python -m agents.resume_digging_agent`.
"""

# Only ChatAgent is re-exported here. The UI lives in app.py and is NOT
# imported, because this file runs on every import of the package - pulling in
# gradio here would cost about a second even when you just want the agent.
from .agent import Agent

# The names that `from agents.digital_twin_agent import *` exposes, and the
# package's public API by convention.
__all__ = ["Agent"]
