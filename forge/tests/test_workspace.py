"""
tests/test_workspace.py — Tests for forge.workspace.local.LocalWorkspace.
"""
from __future__ import annotations

import os
import sys

import pytest

from forge.workspace.local import LocalWorkspace


@pytest.fixture
def ws(tmp_path):
    return LocalWorkspace(str(tmp_path))


class TestLocalWorkspaceReadWrite:
    def test_write_and_read(self, ws):
        ws.write_file("hello.txt", "Hello, World!")
        content = ws.read_file("hello.txt")
        assert content == "Hello, World!"

    def test_write_creates_parent_dirs(self, ws):
        ws.write_file("a/b/c.txt", "nested")
        assert os.path.isfile(os.path.join(ws.base_dir, "a", "b", "c.txt"))

    def test_read_missing_raises(self, ws):
        with pytest.raises(FileNotFoundError):
            ws.read_file("nonexistent.txt")


class TestLocalWorkspaceRunCommand:
    def test_successful_command(self, ws):
        # Use a cross-platform echo command
        cmd = "echo hello"
        code, out = ws.run_command(cmd)
        assert code == 0
        assert "hello" in out

    def test_failing_command(self, ws):
        # Exit with non-zero code cross-platform
        if sys.platform == "win32":
            cmd = "exit 1"
        else:
            cmd = "exit 1"
        code, out = ws.run_command(cmd)
        assert code != 0
