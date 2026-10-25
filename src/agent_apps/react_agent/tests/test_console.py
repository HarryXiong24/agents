"""Exercise real process exit and approval recovery, without calling Groq.

使用真实进程验证退出与审批恢复，不调用 Groq。
"""

import errno
import os
import select
import signal
import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager

import pytest

from agent_apps.react_agent.agent.config import PROJECT_ROOT

pty = pytest.importorskip("pty", reason="Terminal integration tests require a POSIX PTY / 终端集成测试需要 POSIX PTY")

# Replace only the model; the console, SQLite checkpoint and MCP service are real.
# 只替换模型；控制台、SQLite 检查点和 MCP 服务均使用实际实现。
CLI_SCRIPT = """
import sys
from langchain_core.messages import AIMessage, ToolMessage
from agent_apps.react_agent import main as console
from agent_apps.react_agent.__main__ import main
from agent_apps.react_agent.tests.fake_model import ScriptedChatModel, tool_call

def respond(messages, tools_bound):
    if not any(isinstance(message, ToolMessage) for message in messages):
        return AIMessage('', tool_calls=[tool_call('add_expense', {
            'amount': '12.50', 'spent_on': '2026-10-25', 'category': '餐饮', 'note': 'CLI test'
        })])
    return AIMessage('Recorded / 已记录。')

console.get_chat_model = lambda: ScriptedChatModel(responder=respond)
sys.argv = ['react-agent', '--user', 'cli-test', '--thread', 'durable-cli']
main()
"""


class Terminal:
    def __init__(self, process, fd):
        self.process = process
        self.fd = fd
        self.buffer = b""

    def wait_for(self, text, timeout=15):
        marker = text.encode()
        deadline = time.monotonic() + timeout
        while marker not in self.buffer:
            remaining = deadline - time.monotonic()
            assert remaining > 0, self.buffer.decode(errors="replace")
            if not select.select([self.fd], [], [], remaining)[0]:
                continue
            try:
                chunk = os.read(self.fd, 65536)
            except OSError as exc:
                if exc.errno != errno.EIO:
                    raise
                chunk = b""
            assert chunk, self.buffer.decode(errors="replace")
            self.buffer += chunk
        before, self.buffer = self.buffer.split(marker, 1)
        return before.decode(errors="replace")

    def send(self, text):
        os.write(self.fd, text.encode())


@contextmanager
def start_console(data_dir):
    master, slave = pty.openpty()
    env = {**os.environ, "AGENT_DATA_DIR": str(data_dir), "AGENT_REFLECTION": "false",
           "AGENT_RISKY_TOOLS": "add_expense,update_expense,delete_expense"}
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", CLI_SCRIPT], cwd=PROJECT_ROOT, env=env,
        stdin=slave, stdout=slave, stderr=slave,
    )
    os.close(slave)
    try:
        yield Terminal(process, master)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        os.close(master)


def test_ctrl_c_at_input_exits_without_an_extra_enter(tmp_path):
    with start_console(tmp_path) as terminal:
        terminal.wait_for("you>")
        terminal.process.send_signal(signal.SIGINT)
        assert terminal.process.wait(timeout=5) == 0


def test_ctrl_c_at_approval_exits_and_restarts_without_duplicate_write(tmp_path):
    """Exit at approval with no extra input, then approve once after a real restart.

    在审批处退出，无需额外输入；真实重启后批准一次，只保存一条记录。
    """
    with start_console(tmp_path) as terminal:
        terminal.wait_for("you>")
        terminal.send("Record lunch / 记录午餐\n")
        terminal.wait_for("[a]pprove")
        assert not list(tmp_path.rglob("expenses.sqlite"))
        terminal.process.send_signal(signal.SIGINT)
        assert terminal.process.wait(timeout=5) == 0

    with start_console(tmp_path) as terminal:
        terminal.wait_for("[a]pprove")
        assert not list(tmp_path.rglob("expenses.sqlite"))
        terminal.send("a\n")
        terminal.wait_for("you>")
        ledger_path, = tmp_path.rglob("expenses.sqlite")
        with sqlite3.connect(ledger_path) as db:
            assert db.execute("SELECT amount_cents, note FROM expenses").fetchall() == [(1250, "CLI test")]
        terminal.send("/quit\n")
        assert terminal.process.wait(timeout=5) == 0
