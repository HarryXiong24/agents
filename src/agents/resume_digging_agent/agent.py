"""The agent loop, written by hand without an agent framework.

The whole idea fits in one sentence: send the conversation to the model, and
as long as it answers "I want to call a tool", run the tools, add their
results to the conversation, and send it again.

That loop exists twice below, once per delivery mode - streaming, where the
answer is handed over a fragment at a time, and blocking, where it arrives in
one piece. They are kept apart on purpose: the two OpenAI calls return
different things, and folding them into one function would mean a branch on
every other line for no gain in clarity.
"""

from openai import OpenAI

from .config import API_KEY, API_KEY_ENV, BASE_URL, MODEL, REQUIRES_API_KEY
from .context import build_system_prompt
from .tools import TOOLS, run_tool_calls

# Safety limit so a misbehaving model cannot call tools forever.
MAX_TOOL_ROUNDS = 10


class Agent:
    """A digital twin that answers questions and can call tools."""

    def __init__(self, model=MODEL, api_key=API_KEY, base_url=BASE_URL, stream=True):
        """Create the client and load the system prompt from the profile files.

        The defaults come from config, so switching provider is a .env edit.
        Passing the arguments explicitly is for tests, or for running two
        models side by side in a notebook.

        stream=True makes the reply appear word by word. Turn it off for a
        provider whose streaming is unreliable with tools, or when you want a
        plain string back - a notebook cell, a test, a batch script.
        """
        if REQUIRES_API_KEY and not api_key:
            raise RuntimeError(
                f"{API_KEY_ENV} is not set. Add it to your .env file first."
            )
        # base_url is the whole trick: every provider in config.PROVIDERS
        # speaks this same protocol, so only the address changes.
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.system_prompt = build_system_prompt()
        self.stream = stream

        # Pick the mode here, by binding one of the two methods to the name
        # gradio is given. It has to happen this way round: gradio decides
        # whether to animate the reply by asking inspect.isgeneratorfunction
        # about the function it was handed, once, when the UI is built. A
        # single chat() that returned a generator would fail that test - the
        # question is about the function, not about what it returns - and the
        # generator object itself would be drawn into the chat bubble.
        self.chat = self.chat_streaming if stream else self.chat_blocking

    def chat_streaming(self, message, history=None):
        """Answer one user message, yielding the reply as it is written.

        Args:
            message: what the visitor just typed.
            history: the previous turns, as a list of {"role", "content"} dicts.

        Each yield carries the whole answer so far rather than just the new
        piece - that is the shape gradio.ChatInterface wants, since it replaces
        the bubble's contents on every yield instead of appending to them.
        """
        messages = self._build_messages(message, history)

        # Everything shown so far. It survives across tool rounds, so a model
        # that says "let me look that up" before calling a tool keeps those
        # words instead of having them wiped by the next round.
        reply = ""

        # This loop is the agent. Everything else is setup.
        for _ in range(MAX_TOOL_ROUNDS):
            with self._send_streaming(messages) as stream:
                for event in stream:
                    # Text arriving a fragment at a time. The other events are
                    # the tool-call fragments, which the SDK is quietly
                    # accumulating for us as they go past.
                    if event.type == "content.delta":
                        reply += event.delta
                        yield reply
                # The fragments reassembled into the same object the blocking
                # call would have returned, which is why the rest of this loop
                # reads exactly like its twin below.
                choice = stream.get_final_completion().choices[0]

            if choice.finish_reason != "tool_calls":
                # A model that streamed nothing still has its answer here.
                yield reply or choice.message.content or ""
                return

            # The model asked for tools: append its request, then the results,
            # then ask again so it can use them to write a real answer.
            messages.append(choice.message)
            messages.extend(run_tool_calls(choice.message.tool_calls or []))

        yield reply

    def chat_blocking(self, message, history=None):
        """Answer one user message and return the reply text.

        Same arguments as chat_streaming, but the answer comes back whole,
        after the model has finished writing it.
        """
        messages = self._build_messages(message, history)

        response = self._send_blocking(messages)

        # This loop is the agent. Everything else is setup.
        for _ in range(MAX_TOOL_ROUNDS):
            choice = response.choices[0]
            if choice.finish_reason != "tool_calls":
                return choice.message.content or ""

            # The model asked for tools: append its request, then the results,
            # then ask again so it can use them to write a real answer.
            messages.append(choice.message)
            messages.extend(run_tool_calls(choice.message.tool_calls or []))
            response = self._send_blocking(messages)

        return response.choices[0].message.content or ""

    def _build_messages(self, message, history):
        """Turn the UI's history plus the new message into a request payload."""
        # An LLM has no memory: every request must contain the whole
        # conversation. That is what creates the illusion that it remembers.
        messages = [{"role": "system", "content": self.system_prompt}]
        for turn in history or []:
            # Keep only role and content - gradio adds extra keys that some
            # providers reject, and empty messages are not valid either.
            if turn.get("content"):
                messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": message})
        return messages

    def _send_blocking(self, messages):
        """Send one request to the model, telling it which tools exist."""
        try:
            return self.client.chat.completions.create(
                model=self.model, messages=messages, tools=TOOLS
            )
        except Exception as e:
            print(f"Error sending request to model: {e}")
            raise

    def _send_streaming(self, messages):
        """Open one streaming request to the model, telling it which tools exist.

        Returns a context manager, not a response: the HTTP connection stays
        open while the answer arrives, so the caller must use `with`.
        """
        try:
            return self.client.chat.completions.stream(
                model=self.model, messages=messages, tools=TOOLS
            )
        except Exception as e:
            print(f"Error sending request to model: {e}")
            raise
