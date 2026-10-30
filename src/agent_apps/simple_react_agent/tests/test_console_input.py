"""Check Unicode backspace in a real pseudo-terminal without API keys or network."""

import os
import select
import subprocess
import sys
import time

import pytest


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("你\x7f好", "好"),
        ("你好\x7f\x7f再见", "再见"),
        ("A你B\x7f\x7f\x7f学习", "学习"),
    ],
)
def test_backspace_can_delete_first_chinese_character(typed, expected):
    # A pipe cannot simulate terminal editing; give the child a pseudo-terminal.
    master, slave = os.openpty()
    code = """
from types import SimpleNamespace
from langchain_core.messages import AIMessage
from agent_apps.simple_react_agent.main import chat

def echo(state, config):
    text = state["messages"][-1].content
    return {"messages": [AIMessage(content="Echo: " + text)]}

chat(SimpleNamespace(invoke=echo))
"""
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", code],
        stdin=slave,
        stdout=slave,
        stderr=slave,
    )
    os.close(slave)

    def read_until(marker):
        output = b""
        deadline = time.monotonic() + 10
        while marker not in output:
            remaining = deadline - time.monotonic()
            assert remaining > 0, f"Timed out waiting for terminal output: {output!r}"
            ready, _, _ = select.select([master], [], [], remaining)
            assert ready, f"Timed out waiting for terminal output: {output!r}"
            chunk = os.read(master, 4096)
            assert chunk, "Terminal closed early"
            output += chunk
        return output.decode("utf-8")

    try:
        read_until(b"You: ")
        # DEL represents Backspace; submit the replacement text, then exit normally.
        os.write(master, (typed + "\nexit\n").encode())
        output = read_until(b"Assistant: Goodbye!")
        assert process.wait(timeout=5) == 0
        assert f"Assistant: Echo: {expected}\r\n" in output
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        os.close(master)
