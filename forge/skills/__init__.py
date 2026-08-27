"""forge.skills — AGENTS.md and frontmatter-based skill injection."""
from forge.skills.frontmatter import Skill, load_skill_file
from forge.skills.loader import SkillLoader
from forge.skills.project import load_project_instructions

__all__ = ["Skill", "SkillLoader", "load_skill_file", "load_project_instructions"]
