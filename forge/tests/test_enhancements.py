"""
forge/tests/test_enhancements.py — Unit tests for grounding, edit_file, condenser upgrades, and agent loop enhancements.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from forge.agent.builder import build_messages
from forge.agent.loop import Agent, _parse_text_tool_calls
from forge.core.condenser import LLMSummarizingCondenser, format_event_for_summary
from forge.core.events import (
    ConfirmationRequiredEvent,
    Message,
    ShellCommandObservation,
    ToolCallAction,
    ToolResultObservation,
)
from forge.core.state import ConversationState
from forge.security.analyzer import SecurityAnalyzer
from forge.tools import registry
from forge.workspace.grounding import get_git_info, get_workspace_grounding
from forge.workspace.local import LocalWorkspace


class TestEditFileTool:
    def test_edit_file_success(self, tmp_path):
        test_file = tmp_path / "sample.txt"
        test_file.write_text("Hello world\nThis is Forge.\nGoodbye world\n", encoding="utf-8")

        res = registry.execute("edit_file", {
            "path": str(test_file),
            "old_string": "This is Forge.",
            "new_string": "This is Forge 2.0!",
        })
        assert "Successfully edited" in res
        assert test_file.read_text(encoding="utf-8") == "Hello world\nThis is Forge 2.0!\nGoodbye world\n"

    def test_edit_file_not_found(self, tmp_path):
        test_file = tmp_path / "sample.txt"
        test_file.write_text("Alpha Beta Gamma", encoding="utf-8")

        res = registry.execute("edit_file", {
            "path": str(test_file),
            "old_string": "Delta",
            "new_string": "Epsilon",
        })
        assert "Error: `old_string` was not found" in res

    def test_edit_file_multiple_occurrences_guard(self, tmp_path):
        test_file = tmp_path / "sample.txt"
        test_file.write_text("foo bar foo baz", encoding="utf-8")

        # Without replace_all=True, multiple occurrences should return an error asking for uniqueness
        res = registry.execute("edit_file", {
            "path": str(test_file),
            "old_string": "foo",
            "new_string": "qux",
        })
        assert "occurs 2 times" in res

        # With replace_all=True, it should replace all occurrences
        res_all = registry.execute("edit_file", {
            "path": str(test_file),
            "old_string": "foo",
            "new_string": "qux",
            "replace_all": True,
        })
        assert "Successfully edited" in res_all
        assert test_file.read_text(encoding="utf-8") == "qux bar qux baz"


class TestReadFileLineRange:
    def test_read_file_line_range(self, tmp_path):
        test_file = tmp_path / "lines.txt"
        test_file.write_text("\n".join(f"Line {i}" for i in range(1, 21)), encoding="utf-8")

        res = registry.execute("read_file", {
            "path": str(test_file),
            "start_line": 3,
            "end_line": 5,
        })
        assert "Line 3" in res
        assert "Line 4" in res
        assert "Line 5" in res
        assert "Line 1" not in res
        assert "Line 6" not in res


class TestWorkspaceGrounding:
    def test_get_workspace_grounding(self):
        grounding = get_workspace_grounding(".")
        assert "Active Project & Workspace Grounding" in grounding
        assert "Root Path" in grounding
        assert "Project Name" in grounding

    def test_get_git_info(self):
        info = get_git_info(".")
        assert isinstance(info, dict)
        assert "is_repo" in info
        assert "branch" in info


class TestCondenserFormatting:
    def test_format_event_for_summary(self):
        msg = Message(role="user", content="Hello test")
        assert "[User] Hello test" == format_event_for_summary(msg)

        tc_action = ToolCallAction(tool_name="read_file", tool_args={"path": "README.md"})
        assert "read_file" in format_event_for_summary(tc_action)

        obs = ToolResultObservation(tool_name="read_file", tool_call_id="call_1", content="File content here")
        assert "[Tool Result: read_file - Success]" in format_event_for_summary(obs)

        shell_obs = ShellCommandObservation(command="git status", exit_code=0, content="clean")
        assert "[Shell Exit 0] git status" == format_event_for_summary(shell_obs)

    def test_condenser_fallback_does_not_dump_raw_json(self):
        llm_mock = MagicMock()
        llm_mock.generate.side_effect = Exception("HTTP 400 Bad Request")
        condenser = LLMSummarizingCondenser(llm=llm_mock)

        events = [
            Message(role="user", content="Show files"),
            ToolCallAction(tool_name="list_dir", tool_args={"path": "."}),
            ToolResultObservation(tool_name="list_dir", tool_call_id="call_0", content="Contents: foo.py"),
        ]
        summary = condenser.condense(events, previous_summary="Initial goal")
        assert "{" not in summary or "model_dump" not in summary
        assert "[User] Show files" in summary or "list_dir" in summary


class TestLocalWorkspaceCd:
    def test_cd_command_updates_base_dir(self, tmp_path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        ws = LocalWorkspace(str(tmp_path))
        code, out = ws.run_command(f"cd {sub}")
        assert code == 0
        assert "Working directory changed to" in out
        assert os.path.samefile(ws.base_dir, str(sub))


class TestAgentToolNudges:
    def test_agent_nudges_when_refusing_access(self):
        state = ConversationState()
        llm = MagicMock()
        llm.count_tokens.return_value = 10
        llm.generate.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "I don't have access to the current files or repository."}}]
        }
        registry_mock = MagicMock()
        registry_mock.to_openai_schema.return_value = []
        security = SecurityAnalyzer(policy="auto")

        agent = Agent(state=state, llm=llm, registry=registry_mock, security=security)
        events = list(agent.step())

        # Should yield a system guidance nudge event to keep the agent in execution mode
        assert len(events) == 1
        assert isinstance(events[0], Message)
        assert "System Guidance" in events[0].content
        assert "tools" in events[0].content

    def test_agent_nudges_when_outputting_code_without_writing(self):
        state = ConversationState()
        llm = MagicMock()
        llm.count_tokens.return_value = 10
        llm.generate.return_value = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "Sure, I'll update the index.html file with this:\n```html\n<h1>Hello</h1>\n```"
                }
            }]
        }
        registry_mock = MagicMock()
        registry_mock.to_openai_schema.return_value = []
        security = SecurityAnalyzer(policy="auto")

        agent = Agent(state=state, llm=llm, registry=registry_mock, security=security)
        agent._last_user_message = "make the landing page more beautiful in index.html"
        events = list(agent.step())

        assert len(events) == 1
        assert isinstance(events[0], Message)
        assert "write_file" in events[0].content
        assert "NOT been updated" in events[0].content
