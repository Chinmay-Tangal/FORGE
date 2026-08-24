import os
import glob
import subprocess
import tempfile
import logging
from forge_tools.registry import ToolRegistry
from forge_workspace.local_workspace import LocalWorkspace

logger = logging.getLogger(__name__)

registry = ToolRegistry()
workspace = LocalWorkspace(os.getcwd())


# ---------------------------------------------------------------------------
# Existing tools (read_file, write_file, shell, memory_*)
# ---------------------------------------------------------------------------

@registry.register(
    name="read_file",
    description="Read the contents of a file.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to read."}
        },
        "required": ["path"]
    }
)
def read_file(path: str) -> str:
    try:
        return workspace.read_file(path)
    except Exception as e:
        return f"Error reading file: {e}"


@registry.register(
    name="write_file",
    description="Write (or overwrite) content to a file. Creates parent directories as needed.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file."},
            "content": {"type": "string", "description": "Content to write."}
        },
        "required": ["path", "content"]
    }
)
def write_file(path: str, content: str) -> str:
    try:
        workspace.write_file(path, content)
        return f"Successfully wrote to {path}"
    except Exception as e:
        return f"Error writing file: {e}"


@registry.register(
    name="shell",
    description="Run a shell command in the workspace.",
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The command to run."},
            "cwd": {"type": "string", "description": "Optional working directory (relative to workspace root)."}
        },
        "required": ["command"]
    }
)
def shell(command: str, cwd: str = None) -> str:
    exit_code, output = workspace.run_command(command, cwd)
    if exit_code == 0:
        return f"Command succeeded:\n{output}"
    return f"Command failed with code {exit_code}:\n{output}"


@registry.register(
    name="memory_search",
    description="Search the archival memory for stored information.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The semantic query."}
        },
        "required": ["query"]
    }
)
def memory_search(query: str) -> str:
    from forge_core.memory import MemoryStore
    store = MemoryStore()
    results = store.search_archival(query)
    if not results:
        return "No results found in memory."
    return "\n".join([f"[{r['id']}] {r['timestamp']}: {r['content']}" for r in results])


@registry.register(
    name="memory_insert",
    description="Insert new information into archival (long-term) memory.",
    parameters={
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "The information to remember."}
        },
        "required": ["content"]
    }
)
def memory_insert(content: str) -> str:
    from forge_core.memory import MemoryStore
    store = MemoryStore()
    mem_id = store.insert_archival(content)
    return f"Inserted memory with ID {mem_id}"


@registry.register(
    name="memory_evict",
    description="Evict (delete) a specific memory entry by ID.",
    parameters={
        "type": "object",
        "properties": {
            "mem_id": {"type": "integer", "description": "The ID of the memory to remove."}
        },
        "required": ["mem_id"]
    }
)
def memory_evict(mem_id: int) -> str:
    from forge_core.memory import MemoryStore
    store = MemoryStore()
    success = store.evict_archival(mem_id)
    return f"Memory {mem_id} evicted." if success else f"Memory {mem_id} not found."


# ---------------------------------------------------------------------------
# New tools
# ---------------------------------------------------------------------------

@registry.register(
    name="list_dir",
    description="List the contents of a directory, showing file sizes and types.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory path relative to workspace root. Defaults to '.'"}
        },
        "required": []
    }
)
def list_dir(path: str = ".") -> str:
    try:
        abs_path = os.path.join(workspace.base_dir, path)
        entries = sorted(os.scandir(abs_path), key=lambda e: (not e.is_dir(), e.name))
        if not entries:
            return f"Directory '{path}' is empty."
        lines = [f"Contents of {path}:"]
        for i, entry in enumerate(entries[:200]):
            if entry.is_dir():
                lines.append(f"  [DIR]  {entry.name}/")
            else:
                size = entry.stat().st_size
                size_str = f"{size}B" if size < 1024 else f"{size//1024}KB" if size < 1024**2 else f"{size//1024**2}MB"
                lines.append(f"  [FILE] {entry.name} ({size_str})")
        if len(entries) > 200:
            lines.append(f"  ... and {len(entries) - 200} more entries (truncated)")
        return "\n".join(lines)
    except FileNotFoundError:
        return f"Error: Directory '{path}' not found."
    except Exception as e:
        return f"Error listing directory: {e}"


@registry.register(
    name="find_files",
    description="Find files matching a glob pattern within the workspace.",
    parameters={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern, e.g. '**/*.py' or 'src/*.ts'"},
            "directory": {"type": "string", "description": "Directory to search in. Defaults to workspace root."}
        },
        "required": ["pattern"]
    }
)
def find_files(pattern: str, directory: str = ".") -> str:
    try:
        search_base = os.path.join(workspace.base_dir, directory)
        full_pattern = os.path.join(search_base, pattern)
        matches = glob.glob(full_pattern, recursive=True)
        if not matches:
            return f"No files found matching '{pattern}' in '{directory}'."
        # Return paths relative to workspace base
        rel_matches = [os.path.relpath(m, workspace.base_dir) for m in sorted(matches)[:100]]
        result = f"Found {len(matches)} match(es):\n" + "\n".join(rel_matches)
        if len(matches) > 100:
            result += f"\n... (showing first 100 of {len(matches)})"
        return result
    except Exception as e:
        return f"Error finding files: {e}"


@registry.register(
    name="grep",
    description="Search for a text pattern across files in the workspace. Returns matching lines with file and line number.",
    parameters={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Text pattern to search for (case-insensitive)."},
            "directory": {"type": "string", "description": "Directory to search. Defaults to workspace root."},
            "file_glob": {"type": "string", "description": "Glob to filter files, e.g. '**/*.py'. Defaults to '**/*'."}
        },
        "required": ["pattern"]
    }
)
def grep(pattern: str, directory: str = ".", file_glob: str = "**/*") -> str:
    try:
        search_base = os.path.join(workspace.base_dir, directory)
        full_glob = os.path.join(search_base, file_glob)
        files = [f for f in glob.glob(full_glob, recursive=True) if os.path.isfile(f)]
        matches = []
        pattern_lower = pattern.lower()
        for filepath in files:
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    for lineno, line in enumerate(f, 1):
                        if pattern_lower in line.lower():
                            rel_path = os.path.relpath(filepath, workspace.base_dir)
                            matches.append(f"{rel_path}:{lineno}: {line.rstrip()}")
                            if len(matches) >= 50:
                                break
            except Exception:
                continue
            if len(matches) >= 50:
                break

        if not matches:
            return f"No matches found for '{pattern}'."
        result = f"Found {len(matches)} match(es) for '{pattern}':\n" + "\n".join(matches)
        if len(matches) >= 50:
            result += "\n... (showing first 50 matches)"
        return result
    except Exception as e:
        return f"Error during grep: {e}"


@registry.register(
    name="patch_file",
    description="Apply a unified diff patch to a file. Safer than full rewrite for targeted edits.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to patch."},
            "patch": {"type": "string", "description": "Unified diff content (output of 'diff -u')."}
        },
        "required": ["path", "patch"]
    }
)
def patch_file(path: str, patch: str) -> str:
    abs_path = os.path.join(workspace.base_dir, path)
    if not os.path.isfile(abs_path):
        return f"Error: File '{path}' not found."
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False, encoding="utf-8") as tmp:
            tmp.write(patch)
            tmp_path = tmp.name
        result = subprocess.run(
            ["patch", "-u", abs_path, tmp_path],
            capture_output=True, text=True
        )
        os.unlink(tmp_path)
        if result.returncode == 0:
            return f"Patch applied successfully to '{path}'.\n{result.stdout}"
        return f"Patch failed (code {result.returncode}):\n{result.stderr}\nTip: ensure the patch was generated against the current file content."
    except FileNotFoundError:
        return "Error: 'patch' utility not found. Install it (e.g. 'sudo apt install patch' on Linux) or use write_file for full rewrites."
    except Exception as e:
        return f"Error applying patch: {e}"


@registry.register(
    name="append_file",
    description="Append content to the end of a file without overwriting existing content.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to append to."},
            "content": {"type": "string", "description": "Content to append."}
        },
        "required": ["path", "content"]
    }
)
def append_file(path: str, content: str) -> str:
    try:
        abs_path = os.path.join(workspace.base_dir, path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "a", encoding="utf-8") as f:
            f.write(content)
        return f"Content appended to '{path}'."
    except Exception as e:
        return f"Error appending to file: {e}"


@registry.register(
    name="delete_file",
    description="Delete a file from the workspace.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to delete."}
        },
        "required": ["path"]
    }
)
def delete_file(path: str) -> str:
    try:
        abs_path = os.path.join(workspace.base_dir, path)
        if not os.path.exists(abs_path):
            return f"File '{path}' does not exist."
        os.remove(abs_path)
        return f"File '{path}' deleted successfully."
    except Exception as e:
        return f"Error deleting file: {e}"


@registry.register(
    name="git_status",
    description="Get the current git status of the workspace (short format).",
    parameters={
        "type": "object",
        "properties": {
            "cwd": {"type": "string", "description": "Optional subdirectory to run git in."}
        },
        "required": []
    }
)
def git_status(cwd: str = None) -> str:
    exit_code, output = workspace.run_command("git status --short", cwd)
    if exit_code != 0:
        return f"git status failed:\n{output}"
    return output.strip() if output.strip() else "Working tree is clean."


@registry.register(
    name="git_diff",
    description="Show git diff for unstaged or staged changes.",
    parameters={
        "type": "object",
        "properties": {
            "staged": {"type": "boolean", "description": "If true, show staged (--cached) diff. Default false."},
            "cwd": {"type": "string", "description": "Optional subdirectory."}
        },
        "required": []
    }
)
def git_diff(staged: bool = False, cwd: str = None) -> str:
    cmd = "git diff --staged" if staged else "git diff"
    exit_code, output = workspace.run_command(cmd, cwd)
    if exit_code != 0:
        return f"git diff failed:\n{output}"
    return output.strip() if output.strip() else "No differences found."


@registry.register(
    name="git_commit",
    description="Stage all changes and create a git commit with the given message.",
    parameters={
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "The commit message."},
            "cwd": {"type": "string", "description": "Optional subdirectory."}
        },
        "required": ["message"]
    }
)
def git_commit(message: str, cwd: str = None) -> str:
    exit_code, output = workspace.run_command(f'git add -A && git commit -m "{message}"', cwd)
    if exit_code != 0:
        return f"git commit failed:\n{output}"
    return f"Committed successfully:\n{output.strip()}"


@registry.register(
    name="git_log",
    description="Show recent git commit history in one-line format.",
    parameters={
        "type": "object",
        "properties": {
            "n": {"type": "integer", "description": "Number of commits to show. Default 10."},
            "cwd": {"type": "string", "description": "Optional subdirectory."}
        },
        "required": []
    }
)
def git_log(n: int = 10, cwd: str = None) -> str:
    exit_code, output = workspace.run_command(f"git log --oneline -n {n}", cwd)
    if exit_code != 0:
        return f"git log failed:\n{output}"
    return output.strip() if output.strip() else "No commits found."
