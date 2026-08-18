"""The agent loop, written by hand without an agent framework.

The whole idea fits in one sentence: send the conversation to the model, and
as long as it answers "I want to call a tool", run the tools, add their
results to the conversation, and send it again.
"""

from openrouter import OpenRouter

from .config import API_KEY, MODEL
from .context import build_system_prompt
from .tools import TOOLS, run_tool_calls

# Safety limit so a misbehaving model cannot call tools forever.
MAX_TOOL_ROUNDS = 10


class Agent:
    """A digital twin that answers questions and can call tools."""

    def __init__(self, model=MODEL, api_key=API_KEY):
        """Create the client and load the system prompt from the profile files."""
        if not api_key:
            raise RuntimeError(
                "OPEN_ROUTER_API_KEY is not set. Add it to your .env file first."
            )
        self.client = OpenRouter(api_key=api_key)
        self.model = model
        self.system_prompt = build_system_prompt()

    def chat(self, message, history=None):
        """Answer one user message and return the reply text.

        Args:
            message: what the visitor just typed.
            history: the previous turns, as a list of {"role", "content"} dicts.

        This signature is exactly what gradio.ChatInterface expects, so the
        method can be handed to it directly.
        """
        # An LLM has no memory: every request must contain the whole
        # conversation. That is what creates the illusion that it remembers.
        messages = [{"role": "system", "content": self.system_prompt}]
        for turn in history or []:
            # Keep only role and content - gradio adds extra keys that some
            # providers reject, and empty messages are not valid either.
            if turn.get("content"):
                messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": message})

        response = self._send(messages)

        # This loop is the agent. Everything else is setup.
        for _ in range(MAX_TOOL_ROUNDS):
            choice = response.choices[0]
            if choice.finish_reason != "tool_calls":
                return choice.message.content or ""

            # The model asked for tools: append its request, then the results,
            # then ask again so it can use them to write a real answer.
            messages.append(choice.message)
            messages.extend(run_tool_calls(choice.message.tool_calls or []))
            response = self._send(messages)

        return response.choices[0].message.content or ""

    def _send(self, messages):
        """Send one request to the model, telling it which tools exist."""
        try:
            return self.client.chat.send(model=self.model, messages=messages, tools=TOOLS)
        except Exception as e:
            print(f"Error sending request to model: {e}")
            raise