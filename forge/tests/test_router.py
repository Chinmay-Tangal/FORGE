"""
tests/test_router.py — Tests for forge.llm.router.RouterLLM.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from forge.llm.router import RouterLLM


def _mock_backend(name="local"):
    b = MagicMock()
    b.name = name
    return b


class TestRouterLLM:
    def test_picks_local_by_default(self):
        local = _mock_backend("local")
        router = RouterLLM(local_llm=local)
        router.generate([], require_frontier=False)
        local.generate.assert_called_once()

    def test_picks_frontier_when_requested_and_available(self):
        local = _mock_backend("local")
        frontier = _mock_backend("frontier")
        router = RouterLLM(local_llm=local, frontier_llm=frontier)
        router.generate([], require_frontier=True)
        frontier.generate.assert_called_once()
        local.generate.assert_not_called()

    def test_falls_back_to_local_when_no_frontier(self):
        local = _mock_backend("local")
        router = RouterLLM(local_llm=local, frontier_llm=None)
        router.generate([], require_frontier=True)
        local.generate.assert_called_once()

    def test_count_tokens_delegates_to_local(self):
        local = _mock_backend("local")
        local.count_tokens.return_value = 42
        router = RouterLLM(local_llm=local)
        assert router.count_tokens("hello") == 42

    def test_check_health_delegates_to_local(self):
        local = _mock_backend("local")
        local.check_health.return_value = True
        router = RouterLLM(local_llm=local)
        assert router.check_health() is True
