"""
forge/llm/backend.py — OpenAI-compatible LLM backend.

Talks to any OpenAI-format server (llama-server, vLLM, LM Studio, etc.)
via httpx. Supports both blocking and server-sent-event streaming.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Generator, List, Optional

import httpx

from forge.utils import count_tokens as _count_tokens

logger = logging.getLogger(__name__)

# Sentinel injected into the streaming generator when buffered tool calls
# are ready to be consumed by the caller.
TOOL_CALLS_SENTINEL = "\x00TOOL_CALLS\x00"


class LLMBackend:
    """
    Thin wrapper around an OpenAI-compatible `/v1/chat/completions` endpoint.

    Parameters
    ----------
    base_url:
        Base URL of the inference server, e.g. ``http://localhost:8080/v1``.
    model:
        Model identifier sent in every request payload.
    timeout:
        Per-request timeout in seconds (default 120 — local inference is slow).
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8080/v1",
        model: str = "qwen2.5-coder-7b",
        timeout: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.client = httpx.Client(timeout=timeout)

    # Health
    def check_health(self) -> bool:
        """Return True if the server responds to GET /models."""
        try:
            r = self.client.get(f"{self.base_url}/models", timeout=5.0)
            return r.status_code == 200
        except Exception:
            return False

    # Blocking generation
    def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Blocking chat-completion request.

        Returns the raw JSON response dict from the server.
        Raises ``httpx.HTTPStatusError`` on non-2xx responses.
        """
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "options": {"num_ctx": 8192},
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        r = self.client.post(f"{self.base_url}/chat/completions", json=payload)
        r.raise_for_status()
        data = r.json()
        # Ensure all tool calls have a valid non-empty id
        for choice in data.get("choices", []):
            msg = choice.get("message", {})
            for idx, tc in enumerate(msg.get("tool_calls") or []):
                if not tc.get("id"):
                    fn_name = tc.get("function", {}).get("name", "tool")
                    tc["id"] = f"call_{idx}_{fn_name}"
        return data

    # Streaming generation
    def stream_generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Generator[str, None, None]:
        """
        Streaming chat-completion via server-sent events.

        Yields plain text delta chunks as the model generates them.
        When the stream ends and tool calls were accumulated, yields a single
        ``TOOL_CALLS_SENTINEL + json.dumps(tool_calls_list)`` string so the
        caller can detect and dispatch tool calls without a second round-trip.
        """
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "temperature": 0.1,
            "options": {"num_ctx": 8192},
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        # Accumulate incomplete tool-call deltas across SSE chunks
        collected: Dict[int, Dict[str, Any]] = {}

        try:
            with self.client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json=payload,
                timeout=120.0,
            ) as resp:
                resp.raise_for_status()
                for raw in resp.iter_lines():
                    raw = raw.strip()
                    if not raw or raw == "data: [DONE]":
                        continue
                    if raw.startswith("data: "):
                        raw = raw[6:]
                    try:
                        chunk = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    delta = chunk.get("choices", [{}])[0].get("delta", {})

                    if delta.get("content"):
                        yield delta["content"]

                    for tc_delta in delta.get("tool_calls", []):
                        idx = tc_delta.get("index", 0)
                        if idx not in collected:
                            collected[idx] = {
                                "id": "",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            }
                        tc = collected[idx]
                        if tc_delta.get("id"):
                            tc["id"] += tc_delta["id"]
                        fn = tc_delta.get("function", {})
                        tc["function"]["name"] += fn.get("name", "")
                        tc["function"]["arguments"] += fn.get("arguments", "")

        except Exception as exc:
            logger.error("Streaming error: %s", exc)
            raise

        if collected:
            tool_list = []
            for i in sorted(collected):
                tc_item = collected[i]
                if not tc_item.get("id"):
                    fn_name = tc_item.get("function", {}).get("name", "tool")
                    tc_item["id"] = f"call_{i}_{fn_name}"
                tool_list.append(tc_item)
            yield TOOL_CALLS_SENTINEL + json.dumps(tool_list)

    # Token estimation
    def count_tokens(self, text: str) -> int:
        """
        Rough token estimate without a tokenizer dependency.

        Delegates to :func:`forge.utils.count_tokens`.
        """
        return _count_tokens(text)
