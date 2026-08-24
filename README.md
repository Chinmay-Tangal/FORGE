# Forge - Local Agentic Coding Assistant

Forge is a terminal-native, agentic coding assistant architecturally equivalent to Claude Code / OpenHands / Antigravity CLI, but designed from the ground up to run fully locally on a consumer machine (e.g., RTX 5060, 8GB VRAM).

## Mission
To provide a fast, offline, privacy-first alternative to cloud-based agentic coders, with optional escalation to hosted frontier models via `RouterLLM`.

## Hardware-Tuned Install (8GB VRAM Target)

1. **Install llama.cpp** and download the model:
   ```bash
   # Download Qwen2.5-Coder-7B-Instruct (Q4_K_M)
   wget https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/main/qwen2.5-coder-7b-instruct-q4_k_m.gguf
   ```

2. **Start the Inference Server**:
   You must use `llama-server` directly to maintain full control over context length and KV caching.
   ```bash
   llama-server -m qwen2.5-coder-7b-instruct-q4_k_m.gguf \
       --n-gpu-layers 35 \
       --ctx-size 8192 \
       --cache-type-k q8_0 \
       --cache-type-v q8_0 \
       --port 8080
   ```
   *Note: `--cache-type-k q8_0` is crucial for stretching the context window on 8GB VRAM.*

3. **Install Forge**:
   ```bash
   pip install -e .
   ```

4. **Run**:
   ```bash
   forge --url http://localhost:8080/v1
   ```

## Hardware Tiers Upgrade Path

| Hardware | VRAM | Recommended Model | Notes |
|----------|------|-------------------|-------|
| Target (RTX 5060) | 8GB | Qwen2.5-Coder-7B (Q4_K_M) | Maximize KV cache quantization. 8k context limit. |
| Mid-range (RTX 4070) | 12GB | Qwen2.5-Coder-7B (Q8_0) | Unquantized KV cache, 16k context limit. |
| High-end (RTX 3090/4090) | 24GB | Qwen3-Coder-30B-A3B (MoE) | Hybrid CPU/GPU offload. 32k+ context. |

## Features
- **Event-Sourced State**: Crash-safe resume, immutable event log (`forge_core/events.py`).
- **MemGPT-Style Memory**: OS-style memory hierarchy with archival and recall memory (`forge_core/memory.py`).
- **Security Analyzer**: Configurable confirmation policies for risky commands (`forge_core/security.py`).
- **RouterLLM**: Route complex tasks to a frontier model if needed (`forge_core/llm.py`).
