"""
forge/skills/loader.py — Skill and project-instruction loader.

Implements the Antigravity CLI / OpenHands skills system:

  Always-on skills    — injected unconditionally into every system prompt
  Keyword skills      — injected when a trigger keyword appears in the user message
  AGENTS.md           — project-level agent instructions (auto-loaded from cwd)
  .cursorrules        — Cursor IDE rules (compatible)
  .windsurfrules      — Windsurf IDE rules (compatible)

Skill Markdown files use YAML frontmatter::

    ---
    name: my-skill
    always_on: true
    triggers: [docker, containerise]
    priority: 100
    ---
    <skill content>
"""
from __future__ import annotations

import glob
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


# Data model
@dataclass
class Skill:
    name: str
    content: str
    always_on: bool = False
    triggers: List[str] = field(default_factory=list)
    priority: int = 50
    source_file: str = ""


# Frontmatter parser
def _parse_frontmatter(raw: str) -> Dict[str, object]:
    """
    Minimal YAML-subset parser — handles string, bool, and inline-list fields
    without requiring PyYAML.
    """
    result: Dict[str, object] = {}
    for line in raw.strip().splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            items = [x.strip().strip('"\'') for x in value[1:-1].split(",") if x.strip()]
            result[key] = items
        elif value.lower() in ("true", "yes"):
            result[key] = True
        elif value.lower() in ("false", "no"):
            result[key] = False
        else:
            result[key] = value.strip('"\'')
    return result


def _load_skill_file(filepath: str) -> Optional[Skill]:
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            raw = fh.read()
    except OSError as exc:
        logger.warning("Cannot read skill file %s: %s", filepath, exc)
        return None

    match = _FRONTMATTER_RE.match(raw)
    if match:
        fm = _parse_frontmatter(match.group(1))
        content = raw[match.end():]
    else:
        fm = {}
        content = raw

    return Skill(
        name=str(fm.get("name", os.path.splitext(os.path.basename(filepath))[0])),
        content=content.strip(),
        always_on=bool(fm.get("always_on", False)),
        triggers=[t.lower() for t in fm.get("triggers", [])],  # type: ignore[arg-type]
        priority=int(fm.get("priority", 50)),  # type: ignore[arg-type]
        source_file=filepath,
    )


# Loader
class SkillLoader:
    """
    Loads and manages agent skills from the ``.forge/skills`` directory.

    Skills with ``always_on: true`` are injected into every system prompt.
    Skills with ``triggers`` are injected only when the current user message
    contains one of the trigger keywords (case-insensitive).
    """

    def __init__(self, skills_dir: str = ".forge/skills", cwd: str = ".") -> None:
        self.skills_dir = os.path.abspath(skills_dir)
        self.cwd = os.path.abspath(cwd)
        self._skills: List[Skill] = []
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._skills = []
        if os.path.isdir(self.skills_dir):
            for filepath in glob.glob(os.path.join(self.skills_dir, "**", "*.md"), recursive=True):
                skill = _load_skill_file(filepath)
                if skill:
                    self._skills.append(skill)
        self._skills.sort(key=lambda s: s.priority, reverse=True)
        self._loaded = True
        logger.debug("Loaded %d skill(s) from %s.", len(self._skills), self.skills_dir)

    def reload(self) -> None:
        """Force a reload from disk."""
        self._loaded = False
        self._ensure_loaded()

    # Project instructions
    def load_project_instructions(self) -> str:
        """
        Load AGENTS.md, .cursorrules, or .windsurfrules from the project root.
        Returns the combined content or an empty string.
        """
        candidates = [
            os.path.join(self.cwd, "AGENTS.md"),
            os.path.join(self.cwd, ".cursorrules"),
            os.path.join(self.cwd, ".windsurfrules"),
            os.path.join(self.cwd, ".forge", "AGENTS.md"),
        ]
        parts: List[str] = []
        for path in candidates:
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        parts.append(
                            f"## Project instructions from {os.path.basename(path)}\n{fh.read()}"
                        )
                    logger.debug("Loaded project instructions from %s.", path)
                except OSError:
                    pass
        return "\n\n".join(parts)

    # Context builders
    def get_always_on_context(self) -> str:
        self._ensure_loaded()
        return "\n\n".join(
            f"## Skill: {s.name}\n{s.content}"
            for s in self._skills if s.always_on
        )

    def get_triggered_context(self, user_message: str) -> str:
        self._ensure_loaded()
        msg_lower = user_message.lower()
        parts = []
        for skill in self._skills:
            if skill.always_on:
                continue
            if any(t in msg_lower for t in skill.triggers):
                parts.append(f"## Skill: {skill.name}\n{skill.content}")
                logger.debug("Triggered skill '%s'.", skill.name)
        return "\n\n".join(parts)

    def build_system_context(self, user_message: str = "") -> str:
        """
        Build the full skill/instruction block to prepend to the system prompt.
        Order: project instructions → always-on skills → triggered skills.
        """
        parts: List[str] = []

        project = self.load_project_instructions()
        if project:
            parts.append(project)

        always_on = self.get_always_on_context()
        if always_on:
            parts.append(always_on)

        if user_message:
            triggered = self.get_triggered_context(user_message)
            if triggered:
                parts.append(triggered)

        return "\n\n".join(parts)
