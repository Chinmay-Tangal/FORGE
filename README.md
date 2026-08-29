# Forge: Autonomous Local Agentic Coding Assistant

Forge is a high-performance, event-sourced, terminal-native AI coding assistant designed to give you the autonomous capabilities of **Claude Code** running **100% locally** on consumer hardware (e.g., RTX 4060/5060 8GB VRAM).

```
███████╗ ██████╗ ██████╗  ██████╗ ███████╗
██╔════╝██╔═══██╗██╔══██╗██╔════╝ ██╔════╝
█████╗  ██║   ██║██████╔╝██║  ███╗█████╗  
██╔══╝  ██║   ██║██╔══██╗██║   ██║██╔══╝  
██║     ╚██████╔╝██║  ██║╚██████╔╝███████╗
╚═╝      ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚══════╝  Autonomous Terminal AI Coding Assistant
```

---

## ⚡ Key Highlights

- **Autonomous Proactive Agent**: Inspects directories, reads files, writes patches, executes tests, and verifies output automatically without asking for manual file inputs.
- **Local GPU Acceleration**: Powered by quantized models (e.g. Qwen2.5-Coder 7B) through Ollama or llama.cpp with CUDA compute acceleration.
- **Hybrid Frontier Routing (`/frontier`)**: Run 95% of your coding turns locally for free with zero latency. Type `/frontier` to seamlessly route complex architectural reasoning turns to Claude 3.5 Sonnet or GPT-4o while preserving the same conversation context and event log.
- **Immutable Event Sourcing**: Every interaction, tool invocation, and observation is persisted in an append-only JSONL log. Easily inspect (`/history`), resume (`/resume`), and recover from any crash.
- **Context-Window Protection (`LLMSummarizingCondenser`)**: Automatically summarizes and condenses history to prevent token exhaustion on 8k context models.
- **Multi-Tiered Memory**: Short-term working context + SQLite-backed persistent archival store across sessions (`/memory`).
- **Security & Sandboxing**: Configurable security analyzer (`/policy auto` or `/policy strict`) that identifies high-risk actions (e.g. `rm`, `sudo`, destructive patches) and requests confirmation before execution.

---

## 🛠️ Built-in Tools

Forge comes with a comprehensive set of 16 built-in tools:

| Category | Tools | Description |
| :--- | :--- | :--- |
| **Filesystem** | `read_file`, `write_file`, `append_file`, `delete_file`, `list_dir`, `find_files`, `grep`, `patch_file` | Read, create, search, glob, delete, and apply unified diffs across the workspace with full POSIX & Windows path support. |
| **Shell & Execution** | `shell` | Execute shell commands, test runners (`pytest`, `npm test`), package managers, and build scripts. |
| **Git Integration** | `git_status`, `git_diff`, `git_log`, `git_commit` | Inspect repository state, view staged/unstaged changes, inspect history, and create atomic commits. |
| **Archival Memory** | `memory_search`, `memory_insert`, `memory_evict` | Store and retrieve persistent facts, project rules, and notes across sessions. |

---

## 🚀 Getting Started

### 1. Prerequisites
- Python 3.10+
- [Ollama](https://ollama.com/) (recommended for Windows with NVIDIA GPUs) or [llama.cpp](https://github.com/ggerganov/llama.cpp)

### 2. Import / Download the Model
Download or import `Qwen2.5-Coder-7B-Instruct` (Q4_K_M GGUF):

```powershell
# Create Modelfile pointing to your GGUF
Set-Content Modelfile 'FROM "C:\path\to\qwen2.5-coder-7b-instruct-q4_k_m.gguf"'

# Import into Ollama
ollama create qwen2.5-coder -f Modelfile
```

### 3. Start the Backend Server
```powershell
# In PowerShell (Terminal 1)
ollama serve

# In PowerShell (Terminal 2 - loads model to GPU)
ollama run qwen2.5-coder
```

### 4. Install Forge
```bash
# Clone and install in editable mode
git clone https://github.com/Chinmay-Tangal/FORGE.git
cd FORGE
pip install -e .
```

### 5. Launch Forge in Any Project
```bash
cd /d/your-project-directory
forge --url http://localhost:11434/v1 --model qwen2.5-coder
```

---

## ⚙️ Configuration (`.forge/config.toml`)

Forge automatically looks for `.forge/config.toml` in your project or home directory:

```toml
local_llm_url    = "http://localhost:11434/v1"
local_model      = "qwen2.5-coder"
security_policy  = "auto"           # 'auto' (confirm high-risk) or 'strict' (confirm all)
context_limit    = 6000             # Token threshold before automatic memory condensation
max_iterations   = 30               # Maximum autonomous tool iterations per turn

# Optional Frontier Model
frontier_llm_url = "https://api.anthropic.com/v1"
frontier_model   = "claude-3-5-sonnet-20241022"
frontier_api_key = "sk-ant-..."      # Or set FORGE_FRONTIER_KEY env var
```

---

## ⌨️ CLI Slash Commands

| Command | Action | Description |
| :--- | :--- | :--- |
| `/help` | **Help Menu** | Display all available commands and shortcuts. |
| `/status` | **Session Status** | View event count, token usage, cost, and context size. |
| `/history` | **Event Log** | View the last 10 actions and observations in a formatted table. |
| `/frontier` | **Frontier Toggle** | Escalate the next turn to a frontier model (Claude / GPT-4o). |
| `/policy` | **Security Policy** | Switch between `/policy auto` and `/policy strict`. |
| `/memory` | **Memory Search** | `/memory <query>` to search persistent SQLite archival storage. |
| `/sessions`| **Session List** | List saved session logs and recovery checkpoints. |
| `/resume` | **Session Resume** | `/resume <id>` to resume a past session. |
| `/clear` | **Clear Context** | Flush working-memory summaries for a clean turn. |
| `/skills` | **Reload Skills** | Reload custom Markdown skills from `.forge/skills/`. |

---

## 🧩 Extending Forge (Custom Tools)

Register custom tools in seconds using the `@registry.register` decorator:

```python
from forge.tools import registry

@registry.register(
    name="npm_test",
    description="Runs tests using npm test in the current workspace.",
    parameters={
        "type": "object",
        "properties": {
            "test_path": {"type": "string", "description": "Optional path to a test file."}
        },
        "required": []
    }
)
def npm_test(test_path: str = "") -> str:
    cmd = f"npm test {test_path}" if test_path else "npm test"
    exit_code, output = _ws.run_command(cmd)
    return output if exit_code == 0 else f"Failed:\n{output}"
```

---

## 📄 License

MIT License — free for personal, commercial, and open-source use.
