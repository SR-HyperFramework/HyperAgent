"""Tests for hyperagent.engine.subagent."""
from __future__ import annotations

import pytest

from hyperagent.engine.subagent import SubagentResult, spawn_subagent
from hyperagent.providers.base import CompletionResult, LLMProvider, Message
from hyperagent.tools.registry import ToolRegistry


class _RecordingProvider(LLMProvider):
    """Records every `messages` array it's called with, then ends the turn."""

    def __init__(self) -> None:
        self.calls: list[list[Message]] = []

    def complete(self, messages, *, tools=None, system_prompt="", max_tokens=None,
                 temperature=None):
        self.calls.append(list(messages))
        return CompletionResult(
            content="done",
            tool_calls=[],
            stop_reason="end_turn",
            input_tokens=10,
            output_tokens=5,
        )

    def count_tokens(self, text: str) -> int:
        return len(text)

    def max_context_tokens(self) -> int:
        return 100_000


def _flatten(messages: list[Message]) -> str:
    return " ".join(
        m.content if isinstance(m.content, str) else str(m.content) for m in messages
    )


def test_isolated_subagent_excludes_parent_messages():
    provider = _RecordingProvider()
    registry = ToolRegistry()
    parent_messages = [Message(role="user", content="PARENT_SECRET_CONTEXT")]

    result = spawn_subagent(
        provider,
        registry,
        "do the sub-task",
        stage_tools=[],
        parent_messages=parent_messages,
        isolated=True,
    )

    assert isinstance(result, SubagentResult)
    assert len(provider.calls) == 1
    first_call_text = _flatten(provider.calls[0])
    assert "PARENT_SECRET_CONTEXT" not in first_call_text
    assert "do the sub-task" in first_call_text
    assert result.final_text == "done"
    assert result.turns_used == 1
    assert result.input_tokens == 10
    assert result.output_tokens == 5


def test_non_isolated_subagent_includes_parent_messages():
    provider = _RecordingProvider()
    registry = ToolRegistry()
    parent_messages = [Message(role="user", content="PARENT_SECRET_CONTEXT")]

    result = spawn_subagent(
        provider,
        registry,
        "do the sub-task",
        stage_tools=[],
        parent_messages=parent_messages,
        isolated=False,
    )

    first_call_text = _flatten(provider.calls[0])
    assert "PARENT_SECRET_CONTEXT" in first_call_text
    assert "do the sub-task" in first_call_text
    assert result.final_text == "done"


def test_isolated_is_default():
    provider = _RecordingProvider()
    registry = ToolRegistry()
    parent_messages = [Message(role="user", content="PARENT_SECRET_CONTEXT")]

    spawn_subagent(
        provider,
        registry,
        "task",
        stage_tools=[],
        parent_messages=parent_messages,
    )

    assert "PARENT_SECRET_CONTEXT" not in _flatten(provider.calls[0])
