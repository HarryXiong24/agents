"""Load application-local Agent Skills from SKILL.md directories at startup."""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

import yaml

# Agent Skills naming: lowercase letters/digits separated by single hyphens.
NAME_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
# Skills enter the model context; keep each file small and bounded.
MAX_FILE_BYTES = 32_000
SKILL_FILE = "SKILL.md"
# Only read-only text references are loaded. Scripts and assets are never
# loaded or executed by this application.
RESOURCE_DIR = "references"
RESOURCE_SUFFIXES = frozenset({".md", ".txt"})


class SkillLoadError(ValueError):
    """A malformed skill stops startup instead of being silently skipped."""


@dataclass(frozen=True)
class Skill:
    """One skill: catalog metadata, full instructions and reference texts."""

    name: str
    description: str
    instructions: str
    # Keys are POSIX paths relative to the skill directory.
    resources: Mapping[str, str] = field(default_factory=dict)


def load_skills(directory: Path) -> dict[str, Skill]:
    """Return skills by name; a missing directory means no skills."""
    if not directory.is_dir():
        return {}
    skills: dict[str, Skill] = {}
    for skill_dir in sorted(directory.iterdir()):
        if skill_dir.is_dir() and not skill_dir.name.startswith((".", "_")):
            skill = load_skill_dir(skill_dir)
            skills[skill.name] = skill
    return skills


def load_skill_dir(skill_dir: Path) -> Skill:
    """Parse one directory; names must match their directory, so none collide."""
    root = skill_dir.resolve()
    skill_file = skill_dir / SKILL_FILE
    if not skill_file.is_file():
        raise SkillLoadError(f"{skill_dir} has no {SKILL_FILE}.")
    name, description, instructions = parse_skill_file(
        _read_text(skill_file, root), skill_dir.name, skill_file
    )
    resources: dict[str, str] = {}
    resource_root = skill_dir / RESOURCE_DIR
    if resource_root.is_dir():
        for path in sorted(resource_root.rglob("*")):
            relative = path.relative_to(skill_dir)
            if (
                path.is_file()
                and path.suffix in RESOURCE_SUFFIXES
                and not any(part.startswith(".") for part in relative.parts)
            ):
                resources[relative.as_posix()] = _read_text(path, root)
    return Skill(
        name=name,
        description=description,
        instructions=instructions,
        resources=MappingProxyType(resources),
    )


def parse_skill_file(
    text: str, directory_name: str, source: Path
) -> tuple[str, str, str]:
    """Split YAML frontmatter from Markdown instructions and validate both."""
    lines = text.removeprefix("﻿").splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillLoadError(f"{source} must start with '---' YAML frontmatter.")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise SkillLoadError(f"{source} frontmatter has no closing '---'.")
    try:
        # safe_load builds plain data only; it never constructs Python objects.
        metadata = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as exc:
        raise SkillLoadError(f"{source} has invalid YAML frontmatter: {exc}") from exc
    if not isinstance(metadata, dict):
        raise SkillLoadError(f"{source} frontmatter must be a mapping.")

    name = metadata.get("name")
    if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):
        raise SkillLoadError(
            f"{source} name must use lowercase letters, digits and single hyphens."
        )
    if len(name) > MAX_NAME_LENGTH:
        raise SkillLoadError(f"{source} name exceeds {MAX_NAME_LENGTH} characters.")
    if name != directory_name:
        raise SkillLoadError(
            f"{source} name {name!r} must match its directory {directory_name!r}."
        )
    description = metadata.get("description")
    if not isinstance(description, str) or not description.strip():
        raise SkillLoadError(f"{source} needs a nonblank description.")
    description = " ".join(description.split())
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise SkillLoadError(
            f"{source} description exceeds {MAX_DESCRIPTION_LENGTH} characters."
        )
    instructions = "\n".join(lines[end + 1 :]).strip()
    if not instructions:
        raise SkillLoadError(f"{source} has no instructions after its frontmatter.")
    return name, description, instructions


def _read_text(path: Path, root: Path) -> str:
    """Read bounded UTF-8 text that resolves inside the skill directory."""
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise SkillLoadError(f"{path} resolves outside its skill directory.")
    if resolved.stat().st_size > MAX_FILE_BYTES:
        raise SkillLoadError(f"{path} exceeds {MAX_FILE_BYTES} bytes.")
    try:
        return resolved.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise SkillLoadError(f"{path} must be UTF-8 text.") from exc
