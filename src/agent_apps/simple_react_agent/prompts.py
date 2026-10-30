"""Read Markdown files from prompt_templates/ and insert study plan data."""

import json
from pathlib import Path

from .memory import StudyPlan

# Keep Markdown assets separate from the Python prompt loader.
PROMPT_TEMPLATES_DIR = Path(__file__).resolve().parent / "prompt_templates"
SYSTEM_PROMPT = (
    (PROMPT_TEMPLATES_DIR / "system_prompt.md").read_text(encoding="utf-8").strip()
)

# Return this instruction to the model when a tool fails.
TOOL_ERROR_MESSAGE = "Tool execution failed. Check the arguments and retry, or explain the issue to the user."
STUDY_PLANS_PROMPT = (
    (PROMPT_TEMPLATES_DIR / "study_plans_prompt.md").read_text(encoding="utf-8").strip()
)


def build_system_prompt(plans: list[StudyPlan]) -> str:
    """Insert all plans into the system prompt; this function only formats text."""
    # Only the template's {plans} is replaced; braces in plan data are not parsed again.
    memory_prompt = STUDY_PLANS_PROMPT.format(
        plans=json.dumps(plans, ensure_ascii=False, indent=2)
    )
    return SYSTEM_PROMPT + "\n\n" + memory_prompt
