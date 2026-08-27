"""
tests/test_llm_backend.py — Tests for forge.llm.backend (offline, no real server).
"""
from __future__ import annotations

from unittest.mock import MagicMock

from forge.llm.backend import LLMBackend, TOOL_CALLS_SENTINEL


class TestLLMBackendInit:
    def test_defaults(self):
        b = LLMBackend()
        assert "localhost" in b.base_url
        assert b.model == "qwen2.5-coder-7b"

    def test_trailing_slash_stripped(self):
        b = LLMBackend(base_url="http://localhost:8080/v1/")
        assert not b.base_url.endswith("/")


class TestCountTokens:
    def test_empty(self):
        b = LLMBackend()
        assert b.count_tokens("") == 0

    def test_estimate(self):
        b = LLMBackend()
        result = b.count_tokens("hello world")
        assert result == int(2 * 1.3)  # 2

    def test_delegates_to_utils(self):
        """count_tokens should produce same result as forge.utils.count_tokens."""
        from forge.utils import count_tokens
        b = LLMBackend()
        text = "the quick brown fox jumps"
        assert b.count_tokens(text) == count_tokens(text)


class TestCheckHealth:
    def test_healthy(self):
        b = LLMBackend()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        b.client.get = MagicMock(return_value=mock_resp)
        assert b.check_health() is True

    def test_unhealthy_on_exception(self):
        b = LLMBackend()
        b.client.get = MagicMock(side_effect=Exception("refused"))
        assert b.check_health() is False


class TestGenerate:
    def test_returns_json(self):
        b = LLMBackend()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"choices": [{"message": {"content": "hi"}}]}
        mock_resp.raise_for_status = MagicMock()
        b.client.post = MagicMock(return_value=mock_resp)
        result = b.generate([{"role": "user", "content": "hello"}])
        assert result["choices"][0]["message"]["content"] == "hi"

    def test_includes_tools_in_payload(self):
        b = LLMBackend()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"choices": [{"message": {}}]}
        mock_resp.raise_for_status = MagicMock()
        b.client.post = MagicMock(return_value=mock_resp)
        tools = [{"type": "function", "function": {"name": "read_file"}}]
        b.generate([], tools=tools)
        call_kwargs = b.client.post.call_args
        payload = call_kwargs[1]["json"]
        assert "tools" in payload
        assert payload["tool_choice"] == "auto"
