"""
forge/skills/loader.py — Skill loader and system context builder.

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
from typing import List

from forge.skills.frontmatter import Skill, load_skill_file
from forge.skills.project import load_project_instructions

logger = logging.getLogger(__name__)


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
            for filepath in glob.glob(
                os.path.join(self.skills_dir, "**", "*.md"), recursive=True
            ):
                skill = load_skill_file(filepath)
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
        return load_project_instructions(self.cwd)

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
