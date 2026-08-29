"""
forge/tools/filesystem.py — File system tools.

Registered tools:
    read_file, write_file, append_file, delete_file,
    list_dir, find_files, grep, patch_file
"""
from __future__ import annotations

import glob
import logging
import os
import subprocess
import tempfile

from forge.tools import registry
from forge.workspace.local import LocalWorkspace

logger = logging.getLogger(__name__)

_ws = LocalWorkspace(os.getcwd())


# read_file
@registry.register(
    name="read_file",
    description="Read the full contents of a file and return them as a string.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path relative to the workspace root."},
        },
        "required": ["path"],
    },
)
def read_file(path: str) -> str:
    try:
        return _ws.read_file(path)
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except Exception as exc:
        return f"Error reading {path}: {exc}"


# write_file
@registry.register(
    name="write_file",
    description=(
        "Write (or overwrite) a file with the given content. "
        "Parent directories are created automatically. "
        "Prefer patch_file for small targeted edits."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Destination file path."},
            "content": {"type": "string", "description": "Complete file content to write."},
        },
        "required": ["path", "content"],
    },
)
def write_file(path: str, content: str) -> str:
    try:
        _ws.write_file(path, content)
        return f"Wrote {len(content)} bytes to '{path}'."
    except Exception as exc:
        return f"Error writing '{path}': {exc}"


# append_file
@registry.register(
    name="append_file",
    description="Append content to the end of a file without touching existing content.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to append to."},
            "content": {"type": "string", "description": "Text to append."},
        },
        "required": ["path", "content"],
    },
)
def append_file(path: str, content: str) -> str:
    try:
        abs_path = _ws._resolve(path)
        os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
        with open(abs_path, "a", encoding="utf-8") as fh:
            fh.write(content)
        return f"Appended {len(content)} bytes to '{path}'."
    except Exception as exc:
        return f"Error appending to '{path}': {exc}"


# delete_file
@registry.register(
    name="delete_file",
    description="Permanently delete a file from the workspace. This cannot be undone.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to delete."},
        },
        "required": ["path"],
    },
)
def delete_file(path: str) -> str:
    abs_path = _ws._resolve(path)
    if not os.path.exists(abs_path):
        return f"File '{path}' does not exist."
    try:
        os.remove(abs_path)
        return f"Deleted '{path}'."
    except Exception as exc:
        return f"Error deleting '{path}': {exc}"


# list_dir
@registry.register(
    name="list_dir",
    description="List the contents of a directory, showing file sizes and types. Defaults to '.' (workspace root).",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path relative to workspace root. Defaults to '.' (current directory).",
            },
        },
        "required": [],
    },
)
def list_dir(path: str = ".") -> str:
    try:
        abs_path = _ws._resolve(path or ".")
        entries = sorted(os.scandir(abs_path), key=lambda e: (not e.is_dir(), e.name))
    except FileNotFoundError:
        return f"Directory '{path}' not found."
    except Exception as exc:
        return f"Error listing '{path}': {exc}"

    if not entries:
        return f"'{path}' is empty."

    display_path = os.path.relpath(abs_path, _ws.base_dir) if abs_path != _ws.base_dir else "."
    lines = [f"Contents of {display_path}:"]
    for entry in entries[:200]:
        if entry.is_dir():
            lines.append(f"  [dir]  {entry.name}/")
        else:
            size = entry.stat().st_size
            if size < 1024:
                sz = f"{size} B"
            elif size < 1024 ** 2:
                sz = f"{size // 1024} KB"
            else:
                sz = f"{size // 1024 ** 2} MB"
            lines.append(f"  [file] {entry.name}  ({sz})")
    if len(entries) > 200:
        lines.append(f"  … {len(entries) - 200} more entries not shown.")
    return "\n".join(lines)


# find_files
@registry.register(
    name="find_files",
    description=(
        "Find files matching a glob pattern within the workspace. "
        "Supports recursive globs, e.g. '**/*.py'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern, e.g. '**/*.py'."},
            "directory": {
                "type": "string",
                "description": "Sub-directory to search in. Defaults to workspace root ('.').",
            },
        },
        "required": ["pattern"],
    },
)
def find_files(pattern: str, directory: str = ".") -> str:
    try:
        base = _ws._resolve(directory or ".")
        matches = glob.glob(os.path.join(base, pattern), recursive=True)
    except Exception as exc:
        return f"Error finding files: {exc}"

    if not matches:
        return f"No files found matching '{pattern}' in '{directory}'."

    rel = sorted(os.path.relpath(m, _ws.base_dir) for m in matches)[:100]
    result = f"Found {len(matches)} match(es):\n" + "\n".join(rel)
    if len(matches) > 100:
        result += f"\n  … showing first 100 of {len(matches)}."
    return result


# grep
@registry.register(
    name="grep",
    description=(
        "Search for a text pattern across files in the workspace. "
        "Returns matching lines with file name and line number."
    ),
    parameters={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Text to search for (case-insensitive)."},
            "directory": {"type": "string", "description": "Directory to search. Defaults to workspace root ('.')."},
            "file_glob": {
                "type": "string",
                "description": "Glob to filter files, e.g. '**/*.py'. Defaults to all files.",
            },
        },
        "required": ["pattern"],
    },
)
def grep(pattern: str, directory: str = ".", file_glob: str = "**/*") -> str:
    try:
        base = _ws._resolve(directory or ".")
        files = [f for f in glob.glob(os.path.join(base, file_glob), recursive=True) if os.path.isfile(f)]
    except Exception as exc:
        return f"Error during grep setup: {exc}"

    matches: list[str] = []
    needle = pattern.lower()
    for filepath in files:
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as fh:
                for lineno, line in enumerate(fh, 1):
                    if needle in line.lower():
                        rel = os.path.relpath(filepath, _ws.base_dir)
                        matches.append(f"{rel}:{lineno}: {line.rstrip()}")
                        if len(matches) >= 50:
                            break
        except Exception:
            continue
        if len(matches) >= 50:
            break

    if not matches:
        return f"No matches for '{pattern}'."
    result = f"Found {len(matches)} match(es) for '{pattern}':\n" + "\n".join(matches)
    if len(matches) >= 50:
        result += "\n  … showing first 50 matches."
    return result


# patch_file
@registry.register(
    name="patch_file",
    description=(
        "Apply a unified diff patch to a file. "
        "Safer than full overwrite for small, targeted edits. "
        "The patch must be in standard unified diff format (output of 'diff -u')."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to patch."},
            "patch": {"type": "string", "description": "Unified diff content."},
        },
        "required": ["path", "patch"],
    },
)
def patch_file(path: str, patch: str) -> str:
    abs_path = _ws._resolve(path)
    if not os.path.isfile(abs_path):
        return f"Error: '{path}' not found."
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".patch", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(patch)
            tmp_path = tmp.name
        result = subprocess.run(
            ["patch", "-u", abs_path, tmp_path],
            capture_output=True, text=True,
        )
        os.unlink(tmp_path)
        if result.returncode == 0:
            return f"Patch applied to '{path}'.\n{result.stdout}"
        return (
            f"Patch failed (exit {result.returncode}):\n{result.stderr}\n"
            "Tip: ensure the patch was generated against the current file content."
        )
    except FileNotFoundError:
        return (
            "Error: 'patch' utility not found. "
            "Install it (e.g. 'sudo apt install patch') or use write_file instead."
        )
    except Exception as exc:
        return f"Error applying patch: {exc}"
