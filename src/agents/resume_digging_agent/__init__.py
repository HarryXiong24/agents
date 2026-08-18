"""A digital twin chat agent with tool calling, built without an agent framework.

Packaged from demo3.ipynb. To use it from Python or a notebook:

    from agents.digital_twin_agent import ChatAgent

    agent = ChatAgent()
    print(agent.chat("Please tell me about yourself"))

To launch the web UI, run `uv run digital-twin-agent`, or the same thing via
`uv run python -m agents.digital_twin_agent`.
"""

# Only ChatAgent is re-exported here. The UI lives in app.py and is NOT
# imported, because this file runs on every import of the package - pulling in
# gradio here would cost about a second even when you just want the agent.
from .agent import Agent

# The names that `from agents.digital_twin_agent import *` exposes, and the
# package's public API by convention.
__all__ = ["Agent"]
