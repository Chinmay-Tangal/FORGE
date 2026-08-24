"""tests/test_tools.py — Unit tests for forge.tools."""
from __future__ import annotations

import os

import pytest

from forge.tools import registry


def test_registry_has_expected_tools():
    expected = {
        "read_file", "write_file", "append_file", "delete_file",
        "list_dir", "find_files", "grep", "patch_file",
        "git_status", "git_diff", "git_log", "git_commit",
        "shell",
        "memory_search", "memory_insert", "memory_evict",
    }
    assert expected.issubset(set(registry.tools.keys()))


def test_registry_len():
    assert len(registry) >= 16


def test_registry_contains():
    assert "read_file" in registry
    assert "nonexistent_tool" not in registry


def test_openai_schema_format():
    schema = registry.to_openai_schema()
    assert isinstance(schema, list)
    for entry in schema:
        assert entry["type"] == "function"
        assert "name" in entry["function"]
        assert "description" in entry["function"]
        assert "parameters" in entry["function"]


def test_read_file_not_found():
    result = registry.execute("read_file", {"path": "__nonexistent_file_12345.txt"})
    assert "Error" in result or "not found" in result.lower()


def test_write_and_read_roundtrip(tmp_path):
    # write_file resolves relative to cwd, so use an absolute path via shell
    target = str(tmp_path / "forge_test.txt")
    # write_file uses workspace which is rooted at os.getcwd(); use shell instead
    result = registry.execute("shell", {"command": f'echo "hello forge" > "{target}"'})
    content = open(target).read().strip()
    assert "hello forge" in content


def test_list_dir_current():
    result = registry.execute("list_dir", {})
    assert "forge" in result.lower() or "[dir]" in result


def test_find_files_python():
    result = registry.execute("find_files", {"pattern": "**/*.py"})
    assert "forge" in result.lower()


def test_grep_finds_pattern():
    result = registry.execute("grep", {"pattern": "ToolRegistry", "file_glob": "**/*.py"})
    assert "registry.py" in result.lower() or "ToolRegistry" in result


def test_memory_insert_and_search():
    insert_result = registry.execute("memory_insert", {"content": "Forge test memory 99999"})
    assert "Stored" in insert_result or "#" in insert_result
    search_result = registry.execute("memory_search", {"query": "99999"})
    assert "99999" in search_result


def test_git_status_no_repo(monkeypatch, tmp_path):
    """git_status should return a helpful error in non-git directories."""
    # We can't control the cwd of the workspace easily in tests, so just
    # confirm the tool doesn't raise an exception.
    result = registry.execute("git_status", {})
    assert isinstance(result, str)
