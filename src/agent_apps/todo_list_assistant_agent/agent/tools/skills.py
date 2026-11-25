"""Load skill instructions into State and read their bundled reference files."""

from collections.abc import Mapping

from langchain.tools import ToolRuntime
from langchain_core.tools import BaseTool, tool

from ..errors import InputValueError
from ..skills import Skill
from ..state import AgentState


def create_skill_tools(skills: Mapping[str, Skill]) -> list[BaseTool]:
    """Bind the startup skill registry; State records which skills are active."""
    registry = dict(skills)

    def find(name: str) -> Skill:
        skill = registry.get(name)
        if skill is None:
            available = ", ".join(sorted(registry))
            raise InputValueError(
                f"Unknown skill {name!r}. Available skills: {available}."
            )
        return skill

    @tool(response_format="content_and_artifact")
    def load_skill(name: str) -> tuple[str, dict[str, str]]:
        """Load one listed skill's full instructions into this conversation.

        name must exactly match a skill listed under Skills in the system context.
        Call this alone, before following that skill. Its instructions are added
        to the system context of later steps. This never saves or changes todos.
        """
        skill = find(name)
        print(f"Tool: Loaded skill {skill.name}.")
        content = (
            f"Loaded skill {skill.name}. Its instructions are now in the system "
            "context under Active skill instructions."
        )
        if skill.resources:
            content += " Files: " + ", ".join(skill.resources) + "."
        # The tools node commits this accepted name to State after the batch.
        # Keeping the task result as a ToolMessage preserves checkpoint replay.
        return content, {"skill_name": skill.name}

    @tool
    def read_skill_file(
        name: str, path: str, runtime: ToolRuntime[None, AgentState]
    ) -> str:
        """Read a reference file bundled with an active skill.

        name is an active skill; path is copied exactly from that skill's file list,
        for example "references/guide.md". Load the skill first. Read-only.
        """
        skill = find(name)
        if name not in runtime.state.get("active_skills", []):
            raise InputValueError(
                f"Load skill {name!r} with load_skill before reading its files."
            )
        # Lookup in the preloaded mapping: no disk access or path traversal here.
        content = skill.resources.get(path)
        if content is None:
            available = ", ".join(skill.resources) or "none"
            raise InputValueError(
                f"Skill {name!r} has no file {path!r}. Available files: {available}."
            )
        print(f"Tool: Read skill file {name}/{path}.")
        return content

    return [load_skill, read_skill_file]
