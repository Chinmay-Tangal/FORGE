"""
forge/skills/frontmatter.py — Skill data model and YAML frontmatter parser.

Parses Markdown skill files with optional YAML frontmatter blocks.
Deliberately avoids PyYAML to keep dependencies minimal.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass
class Skill:
    """A loaded agent skill with its metadata and content."""

    name: str
    content: str
    always_on: bool = False
    triggers: List[str] = field(default_factory=list)
    priority: int = 50
    source_file: str = ""


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
            items = [x.strip().strip("\"'") for x in value[1:-1].split(",") if x.strip()]
            result[key] = items
        elif value.lower() in ("true", "yes"):
            result[key] = True
        elif value.lower() in ("false", "no"):
            result[key] = False
        else:
            result[key] = value.strip("\"'")
    return result


def load_skill_file(filepath: str) -> Optional[Skill]:
    """Load a single skill Markdown file and return a ``Skill`` instance."""
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
