# Forge: Advanced Local Agentic Coding Assistant


Forge is a highly modular, event-sourced, and terminal-native AI coding assistant. Designed as a lightweight, fully local alternative to cloud-heavy agents like Claude Code or OpenHands, Forge is optimized to run on consumer-grade hardware (e.g., 8GB VRAM) without sacrificing reasoning capabilities.

```
███████╗ ██████╗ ██████╗  ██████╗ ███████╗
██╔════╝██╔═══██╗██╔══██╗██╔════╝ ██╔════╝
█████╗  ██║   ██║██████╔╝██║  ███╗█████╗
██╔══╝  ██║   ██║██╔══██╗██║   ██║██╔══╝
██║     ╚██████╔╝██║  ██║╚██████╔╝███████╗
╚═╝      ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚══════╝  Your ULTIMATE Terminal-native local agentic coding assistant!!!

```

---
## Core Philosophy & Architecture

Forge is built on strict architectural invariants designed for predictability, crash recovery, and extensibility:

1. **Immutable Event Sourcing:** Every interaction—user prompts, LLM generations, and tool observations—is appended to an immutable Pydantic `ConversationState` event log. 
2. **Context Window Protection:** A built-in `LLMSummarizingCondenser` automatically compresses the working context, preventing context-window exhaustion on local 8k models.
3. **Multi-Tiered Memory:** Implements a MemGPT-style OS memory hierarchy. Working memory is dynamic, while Archival memory is persisted via SQLite across sessions.
4. **Isolated Workspaces:** File and shell operations are abstracted through `LocalWorkspace` and `DockerWorkspace` backends.

## Advanced Capabilities

### Hybrid LLM Routing (`RouterLLM`)
Run 95% of your tasks locally with zero latency or cost. When you hit a complex architectural problem, type `/frontier` to dynamically route the next turn to a frontier model (GPT-4o, Claude 3.5 Sonnet) while seamlessly sharing the same event log and context.

### Sandboxed Tool Execution & Security
By default, Forge uses a sophisticated `SecurityAnalyzer`. High-risk commands (like `rm`, `sudo`, or external network calls) automatically pause the agent loop and request TUI confirmation. 
- Use `/policy auto` for intelligent risk assessment.
- Use `/policy strict` to enforce confirmation on *all* tool calls.

---

## Extending Forge

Forge's decorator-based tool registry makes it incredibly easy to extend. The agent automatically infers OpenAI-compatible JSON schemas from your Pydantic parameters.

### Creating a Custom Tool

Simply import the `registry` and use the decorator in `forge/tools/`:

```python
from forge.tools import registry

@registry.register(
    name="npm_install",
    description="Installs a package via npm in the workspace.",
    parameters={
        "type": "object",
        "properties": {
            "package_name": {"type": "string", "description": "The npm package to install"},
            "is_dev": {"type": "boolean", "description": "Install as dev dependency"}
        },
        "required": ["package_name"]
    }
)
def npm_install(package_name: str, is_dev: bool = False) -> str:
    flag = "-D" if is_dev else ""
    # Abstracted workspace execution (safe for Local or Docker)
    exit_code, output = _ws.run_command(f"npm install {flag} {package_name}")
    return output if exit_code == 0 else f"Failed: {output}"
```

---

## Installation & Setup

Forge targets 8GB VRAM environments by aggressively utilizing quantized KV caching in `llama.cpp`.

1. **Spin up the Inference Server**
   ```bash
   # Use q8_0 KV caching to maximize context window on 8GB GPUs
   llama-server -m qwen2.5-coder-7b-instruct-q4_k_m.gguf \
       --n-gpu-layers 35 --ctx-size 8192 \
       --cache-type-k q8_0 --cache-type-v q8_0 \
       --port 8080
   ```

2. **Install Forge**
   ```bash
   pip install -e .
   ```

3. **Configure & Run**
   Forge creates a `~/.forge/config.toml` on first run. Configure your frontier keys and default models there.
   ```bash
   forge --url http://localhost:8080/v1 --workspace local
   ```

---

## CLI Command Reference

The `prompt-toolkit` interface supports interactive slash commands to control the agent lifecycle:

| Command | Action | Deep Dive |
|---------|--------|-----------|
| `/memory <query>` | **Archival Search** | Queries the SQLite long-term store, bypassing the context window. |
| `/history` | **Event Log Dump** | Renders the last 10 Pydantic events in a Rich table. |
| `/sessions` | **Session Manager** | Lists persistent JSONL states available for recovery. |
| `/resume <id>` | **Time Travel** | Replaces the current state tree with a historical JSONL snapshot. |
| `/frontier` | **Escalation** | Bypasses local Llama.cpp for the next turn, hitting OpenAI/Anthropic. |
| `/clear` | **Memory Flush** | Wipes the LLM Condenser's working summary for a fresh start. |

---
