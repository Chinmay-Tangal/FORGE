"""
tests/test_events.py — Tests for forge.core.events.
"""
from __future__ import annotations

from forge.core.events import (
    Action,
    ConfirmationRequiredEvent,
    Event,
    FileReadAction,
    FileReadObservation,
    Message,
    Observation,
    ShellCommandAction,
    ShellCommandObservation,
    ToolCallAction,
    ToolResultObservation,
)


class TestEventBase:
    def test_auto_id(self):
        e1 = Event(source="agent")
        e2 = Event(source="agent")
        assert e1.id != e2.id

    def test_auto_timestamp(self):
        e = Event(source="user")
        assert e.timestamp is not None

    def test_default_source(self):
        e = Event()
        assert e.source == "agent"


class TestMessage:
    def test_fields(self):
        m = Message(role="user", content="hello")
        assert m.role == "user"
        assert m.content == "hello"

    def test_assistant_role(self):
        m = Message(role="assistant", content="reply")
        assert m.role == "assistant"


class TestToolCallAction:
    def test_action_type_default(self):
        a = ToolCallAction(tool_name="read_file", tool_args={"path": "a.py"})
        assert a.action_type == "tool_call"
        assert a.tool_name == "read_file"


class TestToolResultObservation:
    def test_success_default(self):
        obs = ToolResultObservation(
            tool_name="read_file", tool_call_id="abc", content="contents"
        )
        assert obs.success is True

    def test_failure(self):
        obs = ToolResultObservation(
            tool_name="shell", tool_call_id="xyz", content="error", success=False
        )
        assert obs.success is False


class TestConfirmationRequiredEvent:
    def test_source_is_system(self):
        evt = ConfirmationRequiredEvent(
            tool_name="delete_file",
            tool_args={"path": "x.py"},
            risk="high",
            tool_call_raw={"function": {"name": "delete_file", "arguments": '{"path":"x.py"}'}},
        )
        assert evt.source == "system"
        assert evt.risk == "high"
        assert evt.tool_name == "delete_file"


class TestShellEvents:
    def test_shell_command_action(self):
        a = ShellCommandAction(command="ls", cwd="/tmp")
        assert a.action_type == "shell_command"
        assert a.cwd == "/tmp"

    def test_shell_command_observation(self):
        o = ShellCommandObservation(
            observation_type="shell_command", content="ok", command="ls", exit_code=0
        )
        assert o.exit_code == 0
