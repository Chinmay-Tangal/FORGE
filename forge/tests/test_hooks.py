"""
tests/test_hooks.py — Tests for forge.security.hooks.HookRunner.
"""
from __future__ import annotations

import pytest

from forge.security.hooks import HookRunner


@pytest.fixture
def hooks_dir(tmp_path):
    return str(tmp_path / "hooks")


class TestHookRunnerNoHooksDir:
    def test_pre_hook_noop_when_no_dir(self, hooks_dir):
        runner = HookRunner(hooks_dir=hooks_dir)
        # Should not raise even when hooks dir doesn't exist
        runner.run_pre_hook("read_file", {"path": "a.py"})

    def test_post_hook_noop_when_no_dir(self, hooks_dir):
        runner = HookRunner(hooks_dir=hooks_dir)
        runner.run_post_hook("read_file", {"path": "a.py"}, "result")


class TestHookRunnerWithPythonHook:
    def test_pre_hook_runs_py_script(self, tmp_path):
        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        hook_file = hooks_dir / "pre_shell.py"
        marker = tmp_path / "marker.txt"
        hook_file.write_text(
            f"open(r'{marker}', 'w').write('ran')\n", encoding="utf-8"
        )
        runner = HookRunner(hooks_dir=str(hooks_dir))
        runner.run_pre_hook("shell", {"command": "ls"})
        assert marker.exists()
        assert marker.read_text() == "ran"
