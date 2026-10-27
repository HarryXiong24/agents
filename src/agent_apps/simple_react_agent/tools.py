"""第二块积木：两个普通的本地函数，用 @tool 变成模型可调用的工具。"""

import math
from datetime import datetime
from typing import Literal

from langchain_core.tools import tool


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


# 两个工具都在当前进程执行；列表会同时用于绑定模型和创建工具节点。
TOOLS = [get_current_time, calculate]
