"""
tests/test_agent_builder.py — Tests for forge.agent.builder helpers.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from forge.agent.builder import build_messages, maybe_condense
from forge.core.events import Message
from forge.core.state import ConversationState


def _make_agent(working_context="", context_limit=6000):
    """Build a minimal mock Agent for builder tests."""
    agent = MagicMock()
    agent.system_prompt = "You are Forge."
    agent._last_user_message = ""
    agent.skill_loader.build_system_context.return_value = ""
    agent.state = ConversationState()
    agent.state.working_context = working_context
    agent.context_limit = context_limit
    agent.llm.count_tokens.return_value = 0
    agent.condenser.condense.return_value = "summary"
    return agent


class TestBuildMessages:
    def test_always_includes_system_prompt(self):
        agent = _make_agent()
        msgs = build_messages(agent)
        assert msgs[0]["role"] == "system"
        assert "Forge" in msgs[0]["content"]

    def test_includes_working_context(self):
        agent = _make_agent(working_context="previous summary")
        msgs = build_messages(agent)
        contents = [m["content"] for m in msgs]
        assert any("previous summary" in c for c in contents)

    def test_includes_skill_context_when_present(self):
        agent = _make_agent()
        agent.skill_loader.build_system_context.return_value = "skill content"
        msgs = build_messages(agent)
        assert any("skill content" in m["content"] for m in msgs)

    def test_no_working_context_block_when_empty(self):
        agent = _make_agent(working_context="")
        msgs = build_messages(agent)
        # Only system prompt (and maybe skill) — no condensed history block
        for m in msgs:
            assert "Condensed history" not in m.get("content", "")


class TestMaybeCondense:
    def test_no_condense_under_limit(self):
        agent = _make_agent(context_limit=6000)
        agent.llm.count_tokens.return_value = 100
        maybe_condense(agent)
        agent.condenser.condense.assert_not_called()

    def test_condense_fires_over_limit(self):
        agent = _make_agent(context_limit=10)
        agent.llm.count_tokens.return_value = 9999
        for i in range(9):
            agent.state.append_event(Message(role="user", content=f"msg {i}"))
        maybe_condense(agent)
        agent.condenser.condense.assert_called_once()
        assert agent.state.working_context == "summary"
