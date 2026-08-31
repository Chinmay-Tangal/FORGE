# Forge

A terminal-native agentic coding assistant designed to run locally against open-weights models (Ollama, llama.cpp, vLLM) with optional hybrid routing to frontier APIs.

Forge connects directly to your workspace. It reads files, plans changes, performs precise code edits, executes tests via shell commands, and commits changes—without sending code to third-party servers unless you explicitly ask it to.

```
  ███████╗ ██████╗ ██████╗  ██████╗ ███████╗
  ██╔════╝██╔═══██╗██╔══██╗██╔════╝ ██╔════╝
  █████╗  ██║   ██║██████╔╝██║  ███╗█████╗
  ██╔══╝  ██║   ██║██╔══██╗██║   ██║██╔══╝
  ██║     ╚██████╔╝██║  ██║╚██████╔╝███████╗
  ╚═╝      ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚══════╝
```

---

## Features

- **Autonomous Tool Execution**: Discovers workspace layout, reads source files, applies targeted edits, and runs test commands directly.
- **Repository Grounding**: Automatically detects Git branch, commit status, top-level directories, and project overview on startup.
- **Local-First Architecture**: Compatible with any OpenAI-compliant local server (`/v1/chat/completions`), optimized for models like `Qwen2.5-Coder` and `DeepSeek-Coder`.
- **Hybrid Frontier Routing (`/frontier`)**: Run daily tasks on local hardware for zero cost. Toggle `/frontier` to route complex architectural turns to hosted models (Claude 3.5 Sonnet, GPT-4o).
- **Context Condensation**: Automatically summarizes older turns to prevent context overflow on consumer GPUs with 8k–32k context windows.
- **Event-Sourced State**: Append-only JSONL session logging. Supports session resumption (`/resume`), history audits (`/history`), and crash recovery.
- **Configurable Security**: Built-in risk analyzer with `auto` (confirms high-risk actions like `rm` or `sudo`) and `strict` (confirms any file modification) policies.
- **Project Rules & Skills**: Reads `AGENTS.md`, `.cursorrules`, and custom `.forge/skills/` to adapt to your project conventions.

---

## Installation

### 1. Requirements
- Python 3.10+
- A local inference server: [Ollama](https://ollama.com/), [llama.cpp (llama-server)](https://github.com/ggerganov/llama.cpp), or [vLLM](https://github.com/vllm-project/vllm).

### 2. Install Forge
```bash
git clone https://github.com/Chinmay-Tangal/FORGE.git
cd FORGE
pip install -e .
```

---

## Quickstart

### 1. Start your local LLM
Using Ollama:
```bash
ollama run qwen2.5-coder
```

Or using `llama-server`:
```bash
llama-server -m ./models/qwen2.5-coder-7b-instruct-q4_k_m.gguf --port 8080 -c 8192
```

### 2. Launch Forge in your project
```bash
cd /path/to/your/project

# Connect to Ollama
forge --url http://localhost:11434/v1 --model qwen2.5-coder

# Or connect to llama-server
forge --url http://localhost:8080/v1 --model qwen2.5-coder-7b
```

---

## Configuration

Forge loads settings from `.forge/config.toml` in your project or home directory. CLI arguments override these defaults.

```toml
# Local backend
local_llm_url   = "http://localhost:11434/v1"
local_model     = "qwen2.5-coder"

# Execution policy
security_policy = "auto"     # "auto" (prompt on high-risk) or "strict" (prompt on medium/high)
context_limit   = 6000       # Token threshold before context compression
max_iterations  = 30         # Maximum autonomous tool iterations per turn

# Optional frontier model (used when /frontier is toggled)
frontier_llm_url = "https://api.openai.com/v1"
frontier_model   = "gpt-4o"
frontier_api_key = "sk-..."  # Or set FORGE_FRONTIER_KEY env var
```

---

## Built-in Tools

Forge equips the agent with 17 built-in tools across 4 categories:

| Category | Tools | Description |
|---|---|---|
| **Filesystem** | `read_file`, `write_file`, `edit_file`, `append_file`, `delete_file`, `list_dir`, `find_files`, `grep`, `patch_file` | Read files (with line ranges), create files, make exact string replacements, list directories, glob, and search text. |
| **Shell** | `shell` | Run shell commands and test suites. Tracks directory changes (`cd`) across turns. |
| **Git** | `git_status`, `git_diff`, `git_log`, `git_commit` | Inspect repository state, view diffs, read log history, and create atomic commits. |
| **Memory** | `memory_search`, `memory_insert`, `memory_evict` | Search and persist long-term notes across sessions via SQLite. |

---

## CLI Slash Commands

Control session lifecycle and model behavior directly inside the REPL:

- `/help` — Display command list and descriptions.
- `/status` — View current session ID, event count, and context size.
- `/history` — Show recent tool actions and outputs in a table.
- `/frontier` — Toggle frontier model routing for the next prompt.
- `/policy [auto|strict]` — Change confirmation security policy.
- `/memory <query>` — Search archival memory database.
- `/sessions` — List saved session logs.
- `/resume <id>` — Load and resume a previous conversation.
- `/skills` — Reload custom skills and rules from disk.
- `/clear` — Clear the running context condensation summary.

---

## Custom Tools & Extensions

Add custom tools in Python using the `@registry.register` decorator:

```python
from forge.tools import registry
from forge.workspace.local import LocalWorkspace

_ws = LocalWorkspace(".")

@registry.register(
    name="run_pytest",
    description="Run pytest on a specific test file or directory.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to test target, e.g. tests/test_api.py"}
        },
        "required": ["path"]
    }
)
def run_pytest(path: str) -> str:
    exit_code, output = _ws.run_command(f"pytest {path}")
    return output if exit_code == 0 else f"Tests failed (exit {exit_code}):\n{output}"
```

---

## Development

Run tests:
```bash
pytest
```

Format and lint:
```bash
ruff check .
ruff format .
```

---

## License

MIT License. See [LICENSE](LICENSE) for details.
