"""
forge/tools/git.py — Git integration tools.

Registered tools: git_status, git_diff, git_log, git_commit
"""
from __future__ import annotations

import os

from forge.tools import registry
from forge.workspace.local import LocalWorkspace

_ws = LocalWorkspace(os.getcwd())


@registry.register(
    name="git_status",
    description="Show the current git status of the workspace in short format.",
    parameters={
        "type": "object",
        "properties": {
            "cwd": {"type": "string", "description": "Optional sub-directory to run git in."},
        },
        "required": [],
    },
)
def git_status(cwd: str | None = None) -> str:
    code, out = _ws.run_command("git status --short", cwd)
    if code != 0:
        return f"git status failed:\n{out}"
    return out.strip() or "Working tree is clean."


@registry.register(
    name="git_diff",
    description="Show git diff for unstaged changes (or staged changes when staged=true).",
    parameters={
        "type": "object",
        "properties": {
            "staged": {
                "type": "boolean",
                "description": "If true, show staged (--cached) diff. Default false.",
            },
            "cwd": {"type": "string", "description": "Optional sub-directory."},
        },
        "required": [],
    },
)
def git_diff(staged: bool = False, cwd: str | None = None) -> str:
    cmd = "git diff --staged" if staged else "git diff"
    code, out = _ws.run_command(cmd, cwd)
    if code != 0:
        return f"git diff failed:\n{out}"
    return out.strip() or "No differences found."


@registry.register(
    name="git_log",
    description="Show recent git commits in one-line format.",
    parameters={
        "type": "object",
        "properties": {
            "n": {"type": "integer", "description": "Number of commits to show. Default 10."},
            "cwd": {"type": "string", "description": "Optional sub-directory."},
        },
        "required": [],
    },
)
def git_log(n: int = 10, cwd: str | None = None) -> str:
    code, out = _ws.run_command(f"git log --oneline -n {n}", cwd)
    if code != 0:
        return f"git log failed:\n{out}"
    return out.strip() or "No commits found."


@registry.register(
    name="git_commit",
    description="Stage all changes and create a git commit with the provided message.",
    parameters={
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "Commit message."},
            "cwd": {"type": "string", "description": "Optional sub-directory."},
        },
        "required": ["message"],
    },
)
def git_commit(message: str, cwd: str | None = None) -> str:
    # Auto-ignore .forge directory
    try:
        gi_path = _ws._resolve(".gitignore")
        if not os.path.exists(gi_path):
            _ws.write_file(".gitignore", ".forge/\n")
        else:
            gi_content = _ws.read_file(".gitignore")
            if ".forge" not in gi_content:
                _ws.write_file(".gitignore", gi_content.rstrip() + "\n.forge/\n")
    except Exception:
        pass

    # Escape double quotes in the message for the shell
    safe_msg = message.replace('"', '\\"')
    code, out = _ws.run_command(f'git add -A :!.forge :!.forge/* && git commit -m "{safe_msg}"', cwd)
    if code != 0:
        return f"git commit failed:\n{out}"
    return f"Committed:\n{out.strip()}"
