"""
forge/skills/project.py — Project-level instruction loader.

Loads AGENTS.md, .cursorrules, and .windsurfrules from the project root,
providing IDE-agnostic project context to the agent's system prompt.
"""
from __future__ import annotations

import logging
import os
from typing import List

logger = logging.getLogger(__name__)

#: Files checked in order for project-level agent instructions.
PROJECT_INSTRUCTION_FILES = [
    "AGENTS.md",
    ".cursorrules",
    ".windsurfrules",
    os.path.join(".forge", "AGENTS.md"),
]


def load_project_instructions(cwd: str = ".") -> str:
    """
    Load AGENTS.md, .cursorrules, or .windsurfrules from the project root.

    Returns the combined content of all found files, or an empty string
    if none exist.
    """
    parts: List[str] = []
    for filename in PROJECT_INSTRUCTION_FILES:
        path = os.path.join(cwd, filename)
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
