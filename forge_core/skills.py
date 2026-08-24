"""
forge_core/skills.py — Skills & AGENTS.md loader.

Implements the Antigravity CLI / OpenHands skills system:
- Always-on skills: loaded unconditionally into system prompt
- Keyword-triggered skills: loaded when user message matches trigger keywords
- AGENTS.md: project-level agent instructions (auto-loaded from cwd)
- .cursorrules / .windsurfrules: compatible loading

Skill .md files use YAML frontmatter:
---
name: my-skill
always_on: true          # always inject this skill
triggers: [keyword1, keyword2]  # inject when these appear in user message
priority: 100            # higher = earlier in prompt
---
<skill content>
"""
import os
import re
import glob
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict

logger = logging.getLogger(__name__)

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass
class Skill:
    name: str
    content: str
    always_on: bool = False
    triggers: List[str] = field(default_factory=list)
    priority: int = 50
    source_file: str = ""


def _parse_frontmatter(raw: str) -> Dict[str, object]:
    """
    Minimal YAML frontmatter parser — handles string, bool, and list fields
    without requiring a full YAML library.
    """
    result: Dict[str, object] = {}
    for line in raw.strip().splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            # Parse list: [a, b, c]
            items = [x.strip().strip('"').strip("'") for x in value[1:-1].split(",") if x.strip()]
            result[key] = items
        elif value.lower() in ("true", "yes"):
            result[key] = True
        elif value.lower() in ("false", "no"):
            result[key] = False
        else:
            result[key] = value.strip('"').strip("'")
    return result


def _load_skill_file(filepath: str) -> Optional[Skill]:
    """Parses a skill Markdown file with YAML frontmatter."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            raw = f.read()
    except OSError as e:
        logger.warning(f"Cannot read skill file {filepath}: {e}")
        return None

    match = FRONTMATTER_RE.match(raw)
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


class SkillLoader:
    """
    Loads and manages agent skills from the .forge/skills directory.

    Skills with ``always_on: true`` are injected into every system prompt.
    Skills with ``triggers`` are injected only when the current user message
    contains one of the trigger keywords (case-insensitive).
    """

    def __init__(self, skills_dir: str = ".forge/skills", cwd: str = "."):
        self.skills_dir = os.path.abspath(skills_dir)
        self.cwd = os.path.abspath(cwd)
        self._skills: List[Skill] = []
        self._loaded = False

    def _ensure_loaded(self):
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

    def reload(self):
        """Force reload from disk."""
        self._loaded = False
        self._ensure_loaded()

    def load_project_instructions(self) -> str:
        """
        Loads AGENTS.md, .cursorrules, or .windsurfrules from the project root.
        Returns combined content or empty string.
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
                    with open(path, "r", encoding="utf-8") as f:
                        parts.append(f"## Project instructions from {os.path.basename(path)}\n{f.read()}")
                    logger.debug(f"Loaded project instructions from {path}")
                except OSError:
                    pass
        return "\n\n".join(parts)

    def get_always_on_context(self) -> str:
        """Returns combined content for all always-on skills."""
        self._ensure_loaded()
        parts = []
        for skill in self._skills:
            if skill.always_on:
                parts.append(f"## Skill: {skill.name}\n{skill.content}")
        return "\n\n".join(parts)

    def get_triggered_context(self, user_message: str) -> str:
        """Returns combined content for all skills triggered by the user message."""
        self._ensure_loaded()
        msg_lower = user_message.lower()
        parts = []
        for skill in self._skills:
            if skill.always_on:
                continue
            if any(trigger in msg_lower for trigger in skill.triggers):
                parts.append(f"## Skill: {skill.name}\n{skill.content}")
                logger.debug(f"Triggered skill '{skill.name}' for message")
        return "\n\n".join(parts)

    def build_system_context(self, user_message: str = "") -> str:
        """
        Builds the full skill/instructions block to prepend to the system prompt.
        Includes: project instructions + always-on skills + triggered skills.
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
