"""
tests/test_skills.py — Tests for forge.skills (frontmatter, project, loader).
"""
from __future__ import annotations

import os

import pytest

from forge.skills.frontmatter import Skill, _parse_frontmatter, load_skill_file
from forge.skills.loader import SkillLoader
from forge.skills.project import load_project_instructions


class TestParseFrontmatter:
    def test_string_value(self):
        fm = _parse_frontmatter("name: my-skill")
        assert fm["name"] == "my-skill"

    def test_bool_true(self):
        fm = _parse_frontmatter("always_on: true")
        assert fm["always_on"] is True

    def test_bool_false(self):
        fm = _parse_frontmatter("always_on: false")
        assert fm["always_on"] is False

    def test_list(self):
        fm = _parse_frontmatter("triggers: [docker, k8s]")
        assert fm["triggers"] == ["docker", "k8s"]

    def test_priority_raw_string(self):
        fm = _parse_frontmatter("priority: 99")
        assert fm["priority"] == "99"  # raw string; loader casts to int


class TestLoadSkillFile:
    def test_with_frontmatter(self, tmp_path):
        skill_file = tmp_path / "test.md"
        skill_file.write_text(
            "---\nname: test\nalways_on: true\ntriggers: [foo]\n---\nSkill body.",
            encoding="utf-8",
        )
        skill = load_skill_file(str(skill_file))
        assert skill is not None
        assert skill.name == "test"
        assert skill.always_on is True
        assert "foo" in skill.triggers
        assert skill.content == "Skill body."

    def test_without_frontmatter(self, tmp_path):
        skill_file = tmp_path / "plain.md"
        skill_file.write_text("Just plain content.", encoding="utf-8")
        skill = load_skill_file(str(skill_file))
        assert skill is not None
        assert skill.content == "Just plain content."
        assert skill.name == "plain"

    def test_missing_file_returns_none(self):
        skill = load_skill_file("/nonexistent/path.md")
        assert skill is None


class TestLoadProjectInstructions:
    def test_returns_empty_when_no_files(self, tmp_path):
        result = load_project_instructions(str(tmp_path))
        assert result == ""

    def test_loads_agents_md(self, tmp_path):
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text("# Project rules", encoding="utf-8")
        result = load_project_instructions(str(tmp_path))
        assert "Project rules" in result
        assert "AGENTS.md" in result


class TestSkillLoader:
    def test_no_skills_dir(self, tmp_path):
        loader = SkillLoader(skills_dir=str(tmp_path / "nonexistent"))
        assert loader.get_always_on_context() == ""

    def test_always_on_skill_injected(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "mys.md").write_text(
            "---\nname: mys\nalways_on: true\n---\nAlways here.", encoding="utf-8"
        )
        loader = SkillLoader(skills_dir=str(skills_dir))
        ctx = loader.get_always_on_context()
        assert "Always here." in ctx

    def test_triggered_skill(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "docker.md").write_text(
            "---\nname: docker\ntriggers: [docker]\n---\nDocker guide.", encoding="utf-8"
        )
        loader = SkillLoader(skills_dir=str(skills_dir))
        ctx = loader.get_triggered_context("how do I run docker?")
        assert "Docker guide." in ctx

    def test_triggered_skill_not_injected_without_keyword(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "docker.md").write_text(
            "---\nname: docker\ntriggers: [docker]\n---\nDocker guide.", encoding="utf-8"
        )
        loader = SkillLoader(skills_dir=str(skills_dir))
        ctx = loader.get_triggered_context("how do I run python?")
        assert "Docker guide." not in ctx

    def test_reload(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        loader = SkillLoader(skills_dir=str(skills_dir))
        assert loader.get_always_on_context() == ""
        (skills_dir / "new.md").write_text(
            "---\nname: new\nalways_on: true\n---\nNew content.", encoding="utf-8"
        )
        loader.reload()
        assert "New content." in loader.get_always_on_context()
