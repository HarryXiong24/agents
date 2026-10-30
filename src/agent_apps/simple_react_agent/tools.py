"""第二块积木：时间、计算、学习计划保存和删除，全部使用本地工具。"""

import math
from datetime import datetime
from typing import Literal

from langchain_core.tools import tool

from . import memory


@tool
def get_current_time() -> str:
    """获取电脑当前的本地日期和时间。当用户询问现在的时间时使用。"""
    print("工具：正在获取当前时间。")
    return datetime.now().strftime("%Y年%m月%d日 %H时%M分%S秒")


@tool
def calculate(a: float, b: float, operation: Literal["加", "减", "乘", "除"]) -> str:
    """计算两个数字的加、减、乘、除，用于学习时长等数值计算。

    参数 a 是第一个数字，b 是第二个数字。
    operation 必须是“加”“减”“乘”“除”之一。
    例如计算每天学习 45 分钟、连续 7 天的总时长：a=45，b=7，operation="乘"。
    一次只执行一种运算，多步计算需要根据结果再次调用工具。
    """
    print(f"工具：计算 {a} {operation} {b}。")
    if not math.isfinite(a) or not math.isfinite(b):
        return "无法计算：请输入有限的数字。"

    # 明确列出四种运算，方便阅读，也不需要执行模型生成的代码或表达式。
    if operation == "加":
        result = a + b
    elif operation == "减":
        result = a - b
    elif operation == "乘":
        result = a * b
    else:
        if b == 0:
            return "无法计算：除数不能为零，请检查数字或向用户说明。"
        result = a / b

    if not math.isfinite(result):
        return "无法计算：结果超出支持的数值范围。"
    return str(result)


@tool
def save_study_plan(project: str, minutes: int, date: str) -> str:
    """保存一条学习计划，重启后仍可读取，仅在用户要求保存或更新计划时使用。

    project 是学习项目；minutes 是 1 到 1440 之间的整数分钟数；date 是 YYYY-MM-DD 日期。
    例如“保存2026年10月29日学习Python一小时”：project="Python"，minutes=60，date="2026-10-29"。
    三个属性缺少任意一个时先向用户询问；相对日期先用时间工具确认，小时先换算成分钟。
    同项目同日期再次保存时更新时长；不同项目或不同日期新增计划。
    """
    # 写入成功后才输出成功提示；失败时异常由工具节点转换成错误结果。
    plan = memory.save_plan(project, minutes, date)
    result = f"已保存学习计划：{plan['project']}，{plan['minutes']} 分钟，{plan['date']}。"
    print(f"工具：{result}")
    return result


@tool
def delete_study_plan(project: str, date: str) -> str:
    """按项目和日期删除学习计划，仅在用户明确要求删除时使用，无需提供时长。

    project 必须是要删除的学习项目，date 必须是 YYYY-MM-DD 日期。
    例如“删除2026年10月29日的Python计划”：project="Python"，date="2026-10-29"。
    项目或日期不明确时先询问；相对日期先通过时间工具确认。
    仅删除指定项目、指定日期的一条计划，找不到时如实返回，不删除其他计划。
    """
    deleted = memory.delete_plan(project, date)
    if deleted:
        result = f"已删除学习计划：{project.strip()}，{date}。"
    else:
        result = f"未找到学习计划：{project.strip()}，{date}；没有删除任何计划。"
    print(f"工具：{result}")
    return result


# 所有工具都在当前进程执行；列表同时用于绑定模型和创建工具节点。
# 新工具加入列表即可使用，原来两个节点的连线不需要改变。
TOOLS = [get_current_time, calculate, save_study_plan, delete_study_plan]
