"""
forge/workspace/grounding.py — Workspace & Repository context extractor.

Extracts dynamic metadata about the active repository and workspace:
- Project root path & repository name
- Current git branch, commit, and working tree status
- Top-level project directory & file structure
- Project overview / description from README.md or pyproject.toml
"""
from __future__ import annotations

import logging
import os
import subprocess
from typing import Any, Dict

logger = logging.getLogger(__name__)


def get_git_info(base_dir: str) -> Dict[str, Any]:
    """Inspect the local git repository status and branch."""
    info: Dict[str, Any] = {
        "is_repo": False,
        "branch": "",
        "status": "clean",
        "repo_name": "",
    }
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=base_dir,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        if res.returncode != 0:
            return info
        info["is_repo"] = True

        # Current branch
        res_branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=base_dir,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        if res_branch.returncode == 0 and res_branch.stdout.strip():
            info["branch"] = res_branch.stdout.strip()
        else:
            # Fallback for detached HEAD or older git
            res_head = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=base_dir,
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            if res_head.returncode == 0:
                info["branch"] = res_head.stdout.strip()

        # Repo toplevel name
        res_top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=base_dir,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        if res_top.returncode == 0 and res_top.stdout.strip():
            info["repo_name"] = os.path.basename(res_top.stdout.strip().rstrip("/\\"))

        # Working tree status
        res_status = subprocess.run(
            ["git", "status", "--short"],
            cwd=base_dir,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        if res_status.returncode == 0:
            lines = [line.strip() for line in res_status.stdout.splitlines() if line.strip()]
            info["status"] = f"{len(lines)} modified/untracked file(s)" if lines else "clean"
    except Exception as exc:
        logger.debug("Could not determine git info: %s", exc)

    return info


def get_workspace_grounding(base_dir: str = ".") -> str:
    """
    Build a comprehensive, compact summary of the active project workspace.

    Used by the agent loop and CLI to ground the model in the user's project context.
    """
    abs_base = os.path.abspath(base_dir)
    dir_name = os.path.basename(abs_base)

    git_info = get_git_info(abs_base)
    proj_name = git_info.get("repo_name") or dir_name

    # Try extracting description from README.md
    readme_snippet = ""
    for fname in ("README.md", "readme.md", "README.rst", "README.txt"):
        rpath = os.path.join(abs_base, fname)
        if os.path.isfile(rpath):
            try:
                with open(rpath, "r", encoding="utf-8", errors="ignore") as f:
                    raw_lines = [
                        l.strip()
                        for l in f.readlines()
                        if l.strip() and not l.startswith("```") and not l.startswith("![")
                    ]
                    if raw_lines:
                        # Extract first meaningful heading/paragraph
                        clean_lines = [l.lstrip("#").strip() for l in raw_lines[:4]]
                        readme_snippet = " — ".join(clean_lines)[:300]
                break
            except Exception:
                pass

    # Top-level workspace structure (ignore non-project clutter)
    top_entries = []
    ignored = {
        ".git", "__pycache__", ".pytest_cache", "node_modules",
        ".venv", "venv", ".egg-info", "build", "dist", ".forge"
    }
    try:
        with os.scandir(abs_base) as it:
            for entry in sorted(it, key=lambda e: (not e.is_dir(), e.name.lower())):
                if any(entry.name == ign or entry.name.endswith(ign) for ign in ignored):
                    continue
                if entry.is_dir():
                    top_entries.append(f"  [dir]  {entry.name}/")
                else:
                    top_entries.append(f"  [file] {entry.name}")
    except Exception:
        pass

    entries_summary = "\n".join(top_entries[:30])
    if len(top_entries) > 30:
        entries_summary += f"\n  … and {len(top_entries) - 30} more items"

    lines = [
        "## Active Project & Workspace Grounding:",
        f"- Root Path: {abs_base}",
        f"- Project Name: {proj_name}",
    ]
    if git_info.get("is_repo"):
        branch_str = git_info.get("branch") or "main"
        lines.append(f"- Git: branch '{branch_str}' ({git_info.get('status', 'clean')})")
    if readme_snippet:
        lines.append(f"- Overview: {readme_snippet}")
    if entries_summary:
        lines.append(f"- Top-level Structure:\n{entries_summary}")

    return "\n".join(lines)
