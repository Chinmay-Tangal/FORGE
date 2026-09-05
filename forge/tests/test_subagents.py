"""
Tests for SubAgentRunner and task delegation.
"""
import pytest
from forge.agent.subagent import SubAgentRunner, set_subagent_runner, _SUBAGENT_ROLES
from forge.core.state import ConversationState
from forge.llm.backend import LLMBackend
from forge.llm.router import RouterLLM
from forge.security.analyzer import SecurityAnalyzer
from forge.tools.registry import ToolRegistry


class TestSubAgents:
    def test_subagent_roles_defined(self):
        assert "researcher" in _SUBAGENT_ROLES
        assert "tester" in _SUBAGENT_ROLES
        assert "reviewer" in _SUBAGENT_ROLES
        assert "general" in _SUBAGENT_ROLES

    def test_subagent_runner_init(self):
        local_llm = LLMBackend()
        router = RouterLLM(local_llm=local_llm)
        reg = ToolRegistry()
        sec = SecurityAnalyzer()

        runner = SubAgentRunner(llm=router, tool_registry=reg, security=sec, max_iterations=5)
        assert runner.max_iterations == 5

    def test_delegate_task_registered(self):
        from forge.tools import registry
        assert "delegate_task" in registry
