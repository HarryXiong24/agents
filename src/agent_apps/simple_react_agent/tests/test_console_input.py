"""使用伪终端检查真实的中文退格行为，无需模型密钥或网络。"""

import os
import select
import subprocess
import sys
import time

import pytest


@pytest.mark.parametrize(("typed", "expected"), [
    ("你\x7f好", "好"),
    ("你好\x7f\x7f再见", "再见"),
    ("A你B\x7f\x7f\x7f学习", "学习"),
])
def test_backspace_can_delete_first_chinese_character(typed, expected):
    # 普通管道不能模拟终端退格，必须给子进程提供真实的终端接口。
    master, slave = os.openpty()
    code = """
from types import SimpleNamespace
from langchain_core.messages import AIMessage
from agent_apps.simple_react_agent.main import chat

def echo(state, config):
    text = state["messages"][-1].content
    return {"messages": [AIMessage(content="回显：" + text)]}

chat(SimpleNamespace(invoke=echo))
"""
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", code],
        stdin=slave, stdout=slave, stderr=slave,
    )
    os.close(slave)

    def read_until(marker):
        output = b""
        deadline = time.monotonic() + 10
        while marker not in output:
            remaining = deadline - time.monotonic()
            assert remaining > 0, f"等待终端输出超时：{output!r}"
            ready, _, _ = select.select([master], [], [], remaining)
            assert ready, f"等待终端输出超时：{output!r}"
            chunk = os.read(master, 4096)
            assert chunk, "终端提前关闭"
            output += chunk
        return output.decode("utf-8")

    try:
        read_until("输入：".encode())
        # DEL 表示真实退格键；替换内容提交后，再用“退出”正常结束。
        os.write(master, (typed + "\n退出\n").encode())
        output = read_until("助手：再见！".encode())
        assert process.wait(timeout=5) == 0
        assert f"助手：回显：{expected}\r\n" in output
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        os.close(master)
