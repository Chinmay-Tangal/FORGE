"""tests/test_security.py — Unit tests for forge.security."""
from __future__ import annotations

import pytest

from forge.security.analyzer import SecurityAnalyzer


@pytest.fixture
def auto():
    return SecurityAnalyzer(policy="auto")


@pytest.fixture
def strict():
    return SecurityAnalyzer(policy="strict")


def test_invalid_policy():
    with pytest.raises(ValueError):
        SecurityAnalyzer(policy="yolo")


class TestRiskAssessment:
    def test_read_file_is_low(self, auto):
        assert auto.assess_risk("read_file", {}) == "low"

    def test_list_dir_is_low(self, auto):
        assert auto.assess_risk("list_dir", {}) == "low"

    def test_write_file_is_medium(self, auto):
        assert auto.assess_risk("write_file", {"path": "x", "content": "y"}) == "medium"

    def test_delete_file_is_high(self, auto):
        assert auto.assess_risk("delete_file", {"path": "x"}) == "high"

    def test_shell_echo_is_low(self, auto):
        assert auto.assess_risk("shell", {"command": "echo hello"}) == "low"

    def test_shell_rm_is_high(self, auto):
        assert auto.assess_risk("shell", {"command": "rm -rf /"}) == "high"

    def test_shell_git_status_is_low(self, auto):
        assert auto.assess_risk("shell", {"command": "git status"}) == "low"

    def test_shell_generic_is_medium(self, auto):
        assert auto.assess_risk("shell", {"command": "some-custom-cli --flag"}) == "medium"

    def test_unknown_tool_defaults_medium(self, auto):
        assert auto.assess_risk("unknown_tool_xyz", {}) == "medium"


class TestConfirmationPolicy:
    def test_auto_only_requires_high(self, auto):
        assert auto.requires_confirmation("delete_file", {}) is True
        assert auto.requires_confirmation("write_file", {}) is False
        assert auto.requires_confirmation("read_file", {}) is False

    def test_strict_requires_medium_and_high(self, strict):
        assert strict.requires_confirmation("delete_file", {}) is True
        assert strict.requires_confirmation("write_file", {}) is True
        assert strict.requires_confirmation("read_file", {}) is False
