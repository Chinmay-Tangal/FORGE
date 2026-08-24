import json
import httpx
import logging
from typing import List, Dict, Any, Optional, Generator

logger = logging.getLogger(__name__)


class LLMBackend:
    """Backend for local model via llama-server (OpenAI compatible endpoint)."""

    def __init__(self, base_url: str = "http://localhost:8080/v1", model: str = "qwen2.5-coder-7b"):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.client = httpx.Client(timeout=120.0)

    def check_health(self) -> bool:
        try:
            r = self.client.get(f"{self.base_url}/models")
            return r.status_code == 200
        except Exception:
            return False

    def generate(self, messages: List[Dict[str, str]], tools: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Calls the chat completions endpoint (non-streaming)."""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        r = self.client.post(f"{self.base_url}/chat/completions", json=payload)
        r.raise_for_status()
        return r.json()

    def stream_generate(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Generator[str, None, None]:
        """
        Streaming chat completions via SSE.
        Yields plain text chunks as they arrive from the model.
        Tool calls are NOT streamed chunk-by-chunk — the full message is
        buffered and yielded as a single JSON-encoded chunk when the
        stream ends (for compatibility with tool-call parsing in agent.py).
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        collected_tool_calls: Dict[int, Dict] = {}
        content_buffer = []

        try:
            with self.client.stream(
                "POST", f"{self.base_url}/chat/completions", json=payload, timeout=120.0
            ) as response:
                response.raise_for_status()
                for raw_line in response.iter_lines():
                    raw_line = raw_line.strip()
                    if not raw_line or raw_line == "data: [DONE]":
                        continue
                    if raw_line.startswith("data: "):
                        raw_line = raw_line[6:]
                    try:
                        chunk = json.loads(raw_line)
                    except json.JSONDecodeError:
                        continue

                    delta = chunk.get("choices", [{}])[0].get("delta", {})

                    # Plain text content chunk
                    if "content" in delta and delta["content"]:
                        text = delta["content"]
                        content_buffer.append(text)
                        yield text

                    # Tool call deltas — accumulate
                    for tc_delta in delta.get("tool_calls", []):
                        idx = tc_delta.get("index", 0)
                        if idx not in collected_tool_calls:
                            collected_tool_calls[idx] = {
                                "id": "",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            }
                        tc = collected_tool_calls[idx]
                        if tc_delta.get("id"):
                            tc["id"] += tc_delta["id"]
                        fn = tc_delta.get("function", {})
                        if fn.get("name"):
                            tc["function"]["name"] += fn["name"]
                        if fn.get("arguments"):
                            tc["function"]["arguments"] += fn["arguments"]

        except Exception as e:
            logger.error(f"Streaming error: {e}")
            raise

        # After stream ends, if we collected tool calls, yield them as a
        # special sentinel so the agent can process them.
        if collected_tool_calls:
            tool_calls_list = [collected_tool_calls[i] for i in sorted(collected_tool_calls)]
            yield "\x00TOOL_CALLS\x00" + json.dumps(tool_calls_list)

    def count_tokens(self, text: str) -> int:
        """
        Rough token count estimate without a tokenizer dependency.
        Uses a 1.3 word-to-token multiplier (typical for code-heavy content).
        """
        return int(len(text.split()) * 1.3)


class RouterLLM:
    """Routes cheap tasks to small local model, complex tasks to optional frontier model."""

    def __init__(self, local_llm: LLMBackend, frontier_llm: Optional[LLMBackend] = None):
        self.local_llm = local_llm
        self.frontier_llm = frontier_llm

    def _pick(self, require_frontier: bool) -> LLMBackend:
        if require_frontier and self.frontier_llm:
            return self.frontier_llm
        return self.local_llm

    def generate(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        require_frontier: bool = False,
    ) -> Dict[str, Any]:
        return self._pick(require_frontier).generate(messages, tools)

    def stream_generate(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        require_frontier: bool = False,
    ) -> Generator[str, None, None]:
        yield from self._pick(require_frontier).stream_generate(messages, tools)

    def count_tokens(self, text: str) -> int:
        return self.local_llm.count_tokens(text)
