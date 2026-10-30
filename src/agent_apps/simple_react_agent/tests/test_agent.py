"""离线检查工具执行、ReAct 循环和会话历史，不访问模型接口。"""

import json
import re
from unittest.mock import Mock

import httpx
import pytest
from groq import APIConnectionError
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.errors import GraphRecursionError

from agent_apps.simple_react_agent import main as app, memory, model as model_config
from agent_apps.simple_react_agent.tools import calculate, delete_study_plan, get_current_time


@pytest.fixture(autouse=True)
def isolate_plans(tmp_path, monkeypatch):
    """每个测试使用临时文件，避免读取或修改用户真正的学习计划。"""
    monkeypatch.setattr(memory, "PLANS_FILE", tmp_path / "data" / "study_plans.json")


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
        AIMessage(content="好的。"),
        APIConnectionError(message="测试中的连接失败", request=httpx.Request("POST", "https://example.test")),
        AIMessage(content="继续交流。"),
    )
    inputs = iter(["第一轮", "出错的一轮", "重试", "退出"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    app.chat(app.build_graph(model))
    third_request = model.invoke.call_args_list[2].args[0]
    assert [m.content for m in third_request[1:]] == ["第一轮", "好的。", "重试"]
    assert "本轮执行失败" in capsys.readouterr().out


@pytest.mark.parametrize("error", [OSError("读取失败"), ValueError("计划值无效"), TypeError("计划类型无效")])
def test_console_handles_expected_data_errors(monkeypatch, capsys, error):
    graph = Mock()
    graph.invoke.side_effect = error
    inputs = iter(["请读取计划", "退出"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    app.chat(graph)
    assert "请检查学习计划文件或输入" in capsys.readouterr().out


def test_console_propagates_unexpected_error(monkeypatch):
    graph = Mock()
    graph.invoke.side_effect = RuntimeError("测试中的程序错误")
    monkeypatch.setattr("builtins.input", lambda _: "你好")
    with pytest.raises(RuntimeError, match="程序错误"):
        app.chat(graph)


def test_startup_explains_configuration_error(monkeypatch):
    monkeypatch.setattr(app, "create_model", Mock(side_effect=ValueError("缺少密钥")))
    with pytest.raises(SystemExit, match="启动失败：缺少密钥"):
        app.main()


def test_startup_propagates_graph_construction_error(monkeypatch):
    monkeypatch.setattr(app, "create_model", Mock(return_value=Mock()))
    monkeypatch.setattr(app, "build_graph", Mock(side_effect=ValueError("测试中的连线错误")))
    with pytest.raises(ValueError, match="连线错误"):
        app.main()


def test_console_explains_step_limit(monkeypatch, capsys):
    graph = Mock()
    graph.invoke.side_effect = GraphRecursionError("测试中的步数上限")
    inputs = iter(["反复调用", "退出"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    app.chat(graph)
    assert "本轮工具调用步骤过多" in capsys.readouterr().out


def test_missing_api_key_has_chinese_error(monkeypatch):
    monkeypatch.setattr(model_config, "load_dotenv", lambda _: None)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(ValueError, match="请在项目根目录"):
        model_config.create_model()


def test_save_tool_refreshes_prompt_and_survives_new_graph():
    plan = {"project": "Python", "minutes": 60, "date": "2026-10-29"}
    first_model = make_model(
        AIMessage(content="", tool_calls=[{
            "name": "save_study_plan", "args": plan, "id": "save",
        }]),
        AIMessage(content="已保存10月29日学习Python60分钟。"),
    )
    app.build_graph(first_model).invoke({"messages": [HumanMessage("保存2026年10月29日学习Python60分钟。")]})
    assert memory.load_plans() == [plan]
    # 保存工具刚执行完，同一轮的下一次模型调用就应看到新计划。
    assert json.dumps([plan], ensure_ascii=False, indent=2) in first_model.invoke.call_args_list[1].args[0][0].content

    second_model = make_model(AIMessage(content="你计划在10月29日学习Python60分钟。"))
    result = app.build_graph(second_model).invoke({"messages": [HumanMessage("我有哪些学习计划？")]})
    # 新建图且没有旧消息，仍能通过文件注入的提示词获得计划。
    assert json.dumps([plan], ensure_ascii=False, indent=2) in second_model.invoke.call_args.args[0][0].content
    assert len(result["messages"]) == 2


def test_updated_plan_reaches_next_model_request():
    memory.save_plan("Python", 30, "2026-10-29")
    updated = {"project": "Python", "minutes": 45, "date": "2026-10-29"}
    model = make_model(
        AIMessage(content="", tool_calls=[{
            "name": "save_study_plan", "args": updated, "id": "update",
        }]),
        AIMessage(content="已更新为45分钟。"),
    )
    app.build_graph(model).invoke({"messages": [HumanMessage("把2026年10月29日的Python计划改为45分钟，并保存。")]})
    assert '"minutes": 30' in model.invoke.call_args_list[0].args[0][0].content
    assert '"minutes": 45' in model.invoke.call_args_list[1].args[0][0].content
    assert memory.load_plans() == [updated]


def test_temporary_calculation_keeps_saved_plans():
    saved = memory.save_plan("Python", 45, "2026-10-29")
    model = make_model(
        AIMessage(content="", tool_calls=[{
            "name": "calculate", "args": {"a": 20, "b": 3, "operation": "乘"}, "id": "temporary",
        }]),
        AIMessage(content="临时按每天20分钟计算，三天共60分钟。"),
    )
    result = app.build_graph(model).invoke({"messages": [HumanMessage("临时每天20分钟，三天多少？")]})
    assert result["messages"][2].content == "60.0"
    assert memory.load_plans() == [saved]


def test_failed_save_does_not_report_success(monkeypatch, capsys):
    def fail_save(project, minutes, planned_date):
        raise OSError("测试中的磁盘写入失败")

    monkeypatch.setattr(memory, "save_plan", fail_save)
    model = make_model(
        AIMessage(content="", tool_calls=[{
            "name": "save_study_plan",
            "args": {"project": "Python", "minutes": 30, "date": "2026-10-29"},
            "id": "save-failed",
        }]),
        AIMessage(content="保存失败，请稍后重试。"),
    )
    result = app.build_graph(model).invoke({"messages": [HumanMessage("保存2026年10月29日学习Python30分钟。")]})
    assert result["messages"][2].status == "error"
    assert "已保存" not in capsys.readouterr().out
    assert not memory.PLANS_FILE.exists()


def test_one_batch_can_save_multiple_plans():
    plans = [
        {"project": "Python", "minutes": 60, "date": "2026-10-29"},
        {"project": "英语", "minutes": 30, "date": "2026-10-29"},
    ]
    model = make_model(
        AIMessage(content="", tool_calls=[
            {"name": "save_study_plan", "args": plan, "id": f"save-{index}"}
            for index, plan in enumerate(plans)
        ]),
        AIMessage(content="已保存两条计划。"),
    )
    result = app.build_graph(model).invoke({"messages": [HumanMessage("请保存这两条计划。")]})
    assert sorted(memory.load_plans(), key=lambda plan: plan["project"]) == plans
    assert len([message for message in result["messages"] if isinstance(message, ToolMessage)]) == 2


def test_delete_tool_refreshes_prompt_and_survives_new_graph():
    memory.save_plan("Python", 60, "2026-10-29")
    remaining = memory.save_plan("英语", 30, "2026-10-29")
    model = make_model(
        AIMessage(content="", tool_calls=[{
            "name": "delete_study_plan",
            "args": {"project": "Python", "date": "2026-10-29"}, "id": "delete",
        }]),
        AIMessage(content="已删除Python计划。"),
    )
    result = app.build_graph(model).invoke({"messages": [HumanMessage("删除2026年10月29日的Python计划。")]})
    assert "已删除学习计划" in result["messages"][2].content
    assert memory.load_plans() == [remaining]
    expected = json.dumps([remaining], ensure_ascii=False, indent=2)
    assert expected in model.invoke.call_args_list[1].args[0][0].content

    # 全新图没有旧对话，读取到的列表也只包含删除后剩余的计划。
    restarted_model = make_model(AIMessage(content="只剩英语计划。"))
    app.build_graph(restarted_model).invoke({"messages": [HumanMessage("列出我的计划。")]})
    assert expected in restarted_model.invoke.call_args.args[0][0].content


def test_delete_tool_reports_missing_plan(capsys):
    result = delete_study_plan.invoke({"project": "Python", "date": "2026-10-29"})
    assert "未找到" in result
    assert "已删除" not in capsys.readouterr().out
    assert not memory.PLANS_FILE.exists()


@pytest.mark.parametrize("missing_date", [True, False])
def test_delete_errors_do_not_report_success(monkeypatch, capsys, missing_date):
    saved = memory.save_plan("Python", 60, "2026-10-29")
    args = {"project": "Python"}
    if not missing_date:
        args["date"] = "2026-10-29"
        monkeypatch.setattr(memory, "delete_plan", Mock(side_effect=OSError("测试中的删除写入失败")))
    model = make_model(
        AIMessage(content="", tool_calls=[{"name": "delete_study_plan", "args": args, "id": "delete-error"}]),
        AIMessage(content="删除未成功。"),
    )
    result = app.build_graph(model).invoke({"messages": [HumanMessage("删除这条计划。")]})
    assert result["messages"][2].status == "error"
    assert "已删除" not in capsys.readouterr().out
    assert memory.load_plans() == [saved]
