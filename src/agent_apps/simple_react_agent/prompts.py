"""从 prompts/ 读取 Markdown 提示词，再填入学习计划数据。"""

import json
from pathlib import Path

from .memory import StudyPlan

# prompts/ 只放 Markdown 文件，不放 __init__.py，Python 入口仍然是本文件。
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
SYSTEM_PROMPT = (PROMPTS_DIR / "system_prompt.md").read_text(encoding="utf-8").strip()

# 工具执行失败时，作为工具结果交给模型的修正指令。
TOOL_ERROR_MESSAGE = "工具执行失败，请检查参数后重试，或向用户说明。"
STUDY_PLANS_PROMPT = (PROMPTS_DIR / "study_plans_prompt.md").read_text(encoding="utf-8").strip()


def build_system_prompt(plans: list[StudyPlan]) -> str:
    """把全部计划加入系统提示词；这里只处理文本，不读写文件。"""
    # format 只替换模板的 {plans}；计划内容中的大括号不会再被解释为占位符。
    memory_prompt = STUDY_PLANS_PROMPT.format(plans=json.dumps(plans, ensure_ascii=False, indent=2))
    return SYSTEM_PROMPT + "\n\n" + memory_prompt
