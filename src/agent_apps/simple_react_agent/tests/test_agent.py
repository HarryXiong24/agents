"""离线检查工具执行、ReAct 循环和会话历史，不访问模型接口。"""

import re
from unittest.mock import Mock

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.errors import GraphRecursionError

from agent_apps.simple_react_agent import main as app
from agent_apps.simple_react_agent.tools import calculate, get_current_time


def make_model(*responses):
    """只替换模型回复；图、路由和工具仍然执行真实代码。"""
    model = Mock(spec=BaseChatModel)
    model.bind_tools.return_value = model
    model.invoke.side_effect = responses
    return model


@pytest.mark.parametrize(
    ("operation", "expected"),
    [("加", "52.0"), ("减", "38.0"), ("乘", "315.0"), ("除", str(45 / 7))],
)
def test_calculate(operation, expected):
    assert calculate.invoke({"a": 45, "b": 7, "operation": operation}) == expected


def test_invalid_numbers_and_zero_division():
    assert "除数不能为零" in calculate.invoke({"a": 1, "b": 0, "operation": "除"})
    assert "有限的数字" in calculate.invoke({"a": float("inf"), "b": 1, "operation": "加"})
    assert "超出" in calculate.invoke({"a": 1e308, "b": 1e308, "operation": "乘"})


def test_current_time():
    assert re.fullmatch(r"\d{4}年\d{2}月\d{2}日 \d{2}时\d{2}分\d{2}秒", get_current_time.invoke({}))


def test_multistep_react():
    model = make_model(
        AIMessage(content="", tool_calls=[{
            "name": "calculate", "args": {"a": 45, "b": 7, "operation": "乘"}, "id": "first",
        }]),
        AIMessage(content="", tool_calls=[{
            "name": "calculate", "args": {"a": 315, "b": 60, "operation": "除"}, "id": "second",
        }]),
        AIMessage(content="一共 315 分钟，也就是 5.25 小时。"),
    )
    result = app.build_graph(model).invoke({"messages": [HumanMessage("每天45分钟，7天多少小时？")]})
    messages = result["messages"]
    assert len(messages) == 6
    assert [(m.tool_call_id, m.content) for m in messages if isinstance(m, ToolMessage)] == [
        ("first", "315.0"), ("second", "5.25"),
    ]
    # 下一次模型请求确实包含上次工具结果，而不只是预先安排好最终回复。
    assert model.invoke.call_args_list[1].args[0][-1].content == "315.0"
    assert model.invoke.call_args_list[2].args[0][-1].content == "5.25"
    assert isinstance(model.invoke.call_args_list[0].args[0][0], SystemMessage)
    assert not any(isinstance(m, SystemMessage) for m in messages)


def test_tool_validation_error_returns_to_model():
    model = make_model(
        AIMessage(content="", tool_calls=[{
            "name": "calculate", "args": {"a": 1, "b": 2, "operation": "未知"}, "id": "bad",
        }]),
        AIMessage(content="工具参数有误，暂时无法计算。"),
    )
    result = app.build_graph(model).invoke({"messages": [HumanMessage("请计算。")]})
    tool_result = result["messages"][2]
    assert isinstance(tool_result, ToolMessage)
    assert tool_result.status == "error"
    assert "工具执行失败" in tool_result.content
    assert model.invoke.call_count == 2


def test_console_keeps_history_without_duplicates(monkeypatch, capsys):
    model = make_model(AIMessage(content="好的。"), AIMessage(content="一周是210分钟。"))
    inputs = iter(["", "每天学习30分钟", "那一周呢？", "退出"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    app.chat(app.build_graph(model))
    second_request = model.invoke.call_args_list[1].args[0]
    assert [m.content for m in second_request[1:]] == ["每天学习30分钟", "好的。", "那一周呢？"]
    assert "一周是210分钟" in capsys.readouterr().out


def test_console_discards_failed_turn(monkeypatch, capsys):
    model = make_model(
        AIMessage(content="好的。"), RuntimeError("测试中的连接失败"), AIMessage(content="继续交流。"),
    )
    inputs = iter(["第一轮", "出错的一轮", "重试", "退出"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    app.chat(app.build_graph(model))
    third_request = model.invoke.call_args_list[2].args[0]
    assert [m.content for m in third_request[1:]] == ["第一轮", "好的。", "重试"]
    assert "本轮执行失败" in capsys.readouterr().out


def test_console_explains_step_limit(monkeypatch, capsys):
    graph = Mock()
    graph.invoke.side_effect = GraphRecursionError("测试中的步数上限")
    inputs = iter(["反复调用", "退出"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    app.chat(graph)
    assert "本轮工具调用步骤过多" in capsys.readouterr().out


def test_missing_api_key_has_chinese_error(monkeypatch):
    monkeypatch.setattr(app, "load_dotenv", lambda _: None)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(ValueError, match="请在项目根目录"):
        app.create_model()
