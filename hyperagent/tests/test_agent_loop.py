"""Tests for hyperagent.engine.agent_loop.AgentLoop."""
from __future__ import annotations

import logging

import pytest

from hyperagent.engine.agent_loop import AgentLoop
from hyperagent.engine.checkpoint import CheckpointReached
from hyperagent.providers.base import CompletionResult, LLMProvider, Message, ToolCall
from hyperagent.telemetry.metrics import MetricsCollector
from hyperagent.tools.base import ToolDefinition, ToolResult
from hyperagent.tools.registry import ToolRegistry


class _ScriptedProvider(LLMProvider):
    """Returns a pre-scripted sequence of CompletionResults, one per call."""

    def __init__(self, results: list[CompletionResult], max_tokens: int = 100_000) -> None:
        self._results = list(results)
        self._max_tokens = max_tokens
        self.calls: list[list[Message]] = []

    def complete(self, messages, *, tools=None, system_prompt="", max_tokens=None,
                 temperature=None):
        self.calls.append(list(messages))
        if not self._results:
            raise AssertionError("no more scripted results")
        return self._results.pop(0)

    def count_tokens(self, text: str) -> int:
        return len(text)

    def max_context_tokens(self) -> int:
        return self._max_tokens


def _registry_with_echo_tool() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="echo",
            description="echo back",
            handler=lambda **kwargs: ToolResult(content=f"echoed:{kwargs.get('msg', '')}"),
        )
    )
    return registry


def test_run_returns_final_text_on_end_turn():
    provider = _ScriptedProvider([
        CompletionResult(content="all done", tool_calls=[], stop_reason="end_turn",
                          input_tokens=10, output_tokens=5),
    ])
    loop = AgentLoop(provider, ToolRegistry())

    result = loop.run(
        skill_instructions="You are a test agent.",
        initial_prompt="do the thing",
        stage_tools=[],
    )

    assert result == "all done"
    assert loop.turns_used == 1
    assert loop.total_input_tokens == 10
    assert loop.total_output_tokens == 5
    assert len(provider.calls) == 1


def test_run_executes_tool_calls_then_returns_final_text():
    provider = _ScriptedProvider([
        CompletionResult(
            content="",
            tool_calls=[ToolCall(id="tc1", name="echo", arguments={"msg": "hi"})],
            stop_reason="tool_use",
            input_tokens=20, output_tokens=8,
        ),
        CompletionResult(content="finished", tool_calls=[], stop_reason="end_turn",
                          input_tokens=15, output_tokens=6),
    ])
    loop = AgentLoop(provider, _registry_with_echo_tool())

    result = loop.run(
        skill_instructions="You are a test agent.",
        initial_prompt="use the echo tool",
        stage_tools=["echo"],
    )

    assert result == "finished"
    assert loop.turns_used == 2
    assert loop.total_input_tokens == 35
    assert loop.total_output_tokens == 14

    # Second call's messages must include the tool_result from the first turn.
    second_call_messages = provider.calls[1]
    tool_result_msg = second_call_messages[-1]
    assert tool_result_msg.role == "user"
    assert tool_result_msg.content[0]["type"] == "tool_result"
    assert tool_result_msg.content[0]["tool_use_id"] == "tc1"
    assert "echoed:hi" in tool_result_msg.content[0]["content"]


def test_run_reports_tool_error_without_raising():
    def _boom(**kwargs):
        raise RuntimeError("kaboom")

    registry = ToolRegistry()
    registry.register(ToolDefinition(name="boom", description="fails", handler=_boom))

    provider = _ScriptedProvider([
        CompletionResult(
            content="",
            tool_calls=[ToolCall(id="tc1", name="boom", arguments={})],
            stop_reason="tool_use",
            input_tokens=1, output_tokens=1,
        ),
        CompletionResult(content="recovered", tool_calls=[], stop_reason="end_turn",
                          input_tokens=1, output_tokens=1),
    ])
    loop = AgentLoop(provider, registry)

    result = loop.run(
        skill_instructions="test",
        initial_prompt="trigger the failing tool",
        stage_tools=["boom"],
    )

    assert result == "recovered"
    second_call_messages = provider.calls[1]
    tool_result = second_call_messages[-1].content[0]
    assert tool_result["is_error"] is True
    assert "kaboom" in tool_result["content"]


def test_run_blocks_tool_calls_not_allowed_for_stage():
    executed = []
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="fetch_vt_report",
            description="should not run",
            parameters={},
            handler=lambda **kwargs: executed.append(kwargs) or ToolResult(content="fetched"),
        )
    )
    provider = _ScriptedProvider([
        CompletionResult(
            content="",
            tool_calls=[ToolCall(id="tc1", name="fetch_vt_report", arguments={"file_id": "a" * 64})],
            stop_reason="tool_use",
            input_tokens=1,
            output_tokens=1,
        ),
        CompletionResult(content="recovered", tool_calls=[], stop_reason="end_turn", input_tokens=1, output_tokens=1),
    ])
    loop = AgentLoop(provider, registry)

    result = loop.run(
        skill_instructions="report",
        initial_prompt="render report",
        stage_tools=[],
        stage_id="08-report",
    )

    assert result == "recovered"
    assert executed == []
    tool_result = provider.calls[1][-1].content[0]
    assert tool_result["is_error"] is True
    assert "unauthorized_tool_for_stage" in tool_result["content"]
    assert "08-report" in tool_result["content"]
    assert "fetch_vt_report" in tool_result["content"]


def test_run_seeds_conversation_with_initial_messages():
    provider = _ScriptedProvider([
        CompletionResult(content="done", tool_calls=[], stop_reason="end_turn",
                          input_tokens=1, output_tokens=1),
    ])
    loop = AgentLoop(provider, ToolRegistry())
    seed = [Message(role="user", content="PARENT_CONTEXT")]

    loop.run(
        skill_instructions="test",
        initial_prompt="continue the task",
        stage_tools=[],
        initial_messages=seed,
    )

    first_call = provider.calls[0]
    assert first_call[0].content == "PARENT_CONTEXT"
    assert first_call[1].content == "continue the task"


def test_run_without_initial_messages_starts_with_just_prompt():
    provider = _ScriptedProvider([
        CompletionResult(content="done", tool_calls=[], stop_reason="end_turn",
                          input_tokens=1, output_tokens=1),
    ])
    loop = AgentLoop(provider, ToolRegistry())

    loop.run(
        skill_instructions="test",
        initial_prompt="just this",
        stage_tools=[],
    )

    first_call = provider.calls[0]
    assert len(first_call) == 1
    assert first_call[0].content == "just this"


def test_run_raises_checkpoint_reached_when_threshold_exceeded():
    provider = _ScriptedProvider([], max_tokens=10)
    loop = AgentLoop(provider, ToolRegistry(), checkpoint_threshold=0.5)

    with pytest.raises(CheckpointReached):
        loop.run(
            skill_instructions="test",
            initial_prompt="x" * 20,
            stage_tools=[],
        )

    # No completion call should have happened — checkpoint check runs first.
    assert provider.calls == []
    assert loop.last_messages[0].content == "x" * 20

def test_run_compacts_context_before_checkpointing():
    provider = _ScriptedProvider([
        CompletionResult(content="facts summarized", tool_calls=[], stop_reason="end_turn",
                         input_tokens=30, output_tokens=10, model="compact-model"),
        CompletionResult(content="all done", tool_calls=[], stop_reason="end_turn",
                         input_tokens=12, output_tokens=4, model="answer-model"),
    ], max_tokens=500)
    seed = [Message(role="assistant", content="x" * 300)]
    loop = AgentLoop(
        provider,
        ToolRegistry(),
        checkpoint_threshold=0.5,
        compact_target_ratio=0.9,
    )

    result = loop.run(
        skill_instructions="test",
        initial_prompt="continue",
        stage_tools=[],
        stage_id="02-static-pass1",
        initial_messages=seed,
    )

    assert result == "all done"
    assert len(provider.calls) == 2
    second_call_text = provider.calls[1][0].content
    assert isinstance(second_call_text, str)
    assert "# Compacted conversation state for 02-static-pass1" in second_call_text
    assert "facts summarized" in second_call_text
    assert loop.total_input_tokens == 42
    assert loop.total_output_tokens == 14


def test_run_checkpoint_behavior_unchanged_when_compaction_disabled():
    provider = _ScriptedProvider([], max_tokens=10)
    loop = AgentLoop(
        provider,
        ToolRegistry(),
        checkpoint_threshold=0.5,
        compact_enabled=False,
    )

    with pytest.raises(CheckpointReached):
        loop.run(
            skill_instructions="test",
            initial_prompt="x" * 20,
            stage_tools=[],
        )

    assert provider.calls == []


def test_run_raises_checkpoint_when_compaction_remains_too_large():
    provider = _ScriptedProvider([
        CompletionResult(content="y" * 80, tool_calls=[], stop_reason="end_turn",
                         input_tokens=30, output_tokens=10),
    ], max_tokens=100)
    seed = [Message(role="assistant", content="x" * 80)]
    loop = AgentLoop(
        provider,
        ToolRegistry(),
        checkpoint_threshold=0.5,
        compact_target_ratio=0.4,
    )

    with pytest.raises(CheckpointReached):
        loop.run(
            skill_instructions="test",
            initial_prompt="continue",
            stage_tools=[],
            initial_messages=seed,
        )

    assert len(provider.calls) == 1



    results = [
        CompletionResult(
            content="",
            tool_calls=[ToolCall(id=f"tc{i}", name="echo", arguments={"msg": str(i)})],
            stop_reason="tool_use",
            input_tokens=1, output_tokens=1,
        )
        for i in range(3)
    ]
    provider = _ScriptedProvider(results)
    loop = AgentLoop(provider, _registry_with_echo_tool(), max_turns=3)

    result = loop.run(
        skill_instructions="test",
        initial_prompt="loop forever",
        stage_tools=["echo"],
    )

    assert result == "ERROR: Max iterations reached without a final answer."
    assert loop.turns_used == 3


def test_run_records_turn_metrics_via_metrics_collector(tmp_path):
    provider = _ScriptedProvider([
        CompletionResult(content="ok", tool_calls=[], stop_reason="end_turn",
                          input_tokens=7, output_tokens=3),
    ])
    collector = MetricsCollector(
        run_id="run1", sample_sha256="a" * 64, output_path=tmp_path / "telemetry.jsonl",
    )
    loop = AgentLoop(provider, ToolRegistry(), metrics=collector)

    loop.run(
        skill_instructions="test",
        initial_prompt="go",
        stage_tools=[],
        stage_id="01-prepare-env",
    )

    sm = collector.get_stage("01-prepare-env")
    assert sm is not None
    assert sm.turns == 1
    assert sm.total_input_tokens == 7
    assert sm.total_output_tokens == 3


def test_run_records_checkpoint_via_metrics_collector(tmp_path):
    provider = _ScriptedProvider([], max_tokens=10)
    collector = MetricsCollector(
        run_id="run1", sample_sha256="a" * 64, output_path=tmp_path / "telemetry.jsonl",
    )
    collector.start_stage("05-dynamic")
    loop = AgentLoop(provider, ToolRegistry(), checkpoint_threshold=0.5, metrics=collector)

    with pytest.raises(CheckpointReached):
        loop.run(
            skill_instructions="test",
            initial_prompt="x" * 20,
            stage_tools=[],
            stage_id="05-dynamic",
        )

    sm = collector.get_stage("05-dynamic")
    assert sm is not None
    assert sm.checkpoint_triggered is True



def test_run_logs_context_window_usage_next_to_turn_counter(caplog):
    provider = _ScriptedProvider([
        CompletionResult(content="done", tool_calls=[], stop_reason="end_turn",
                          input_tokens=1, output_tokens=1),
    ], max_tokens=200)
    loop = AgentLoop(provider, ToolRegistry())

    with caplog.at_level(logging.INFO):
        loop.run(
            skill_instructions="test",
            initial_prompt="abcd",
            stage_tools=[],
        )

    assert "Agent turn 1/100 (context 4/200 tokens, 2.0%)" in caplog.text


class _FakeRunConsole:
    def __init__(self) -> None:
        self.context_calls = []
        self.tool_results = []

    def set_context(self, **kwargs):
        self.context_calls.append(kwargs)

    def tool_result(self, content, *, is_error=False):
        self.tool_results.append((content, is_error))


def test_run_updates_minimal_console_context_and_tool_results():
    provider = _ScriptedProvider([
        CompletionResult(
            content="",
            tool_calls=[ToolCall(id="tc1", name="echo", arguments={"msg": "hi"})],
            stop_reason="tool_use",
            input_tokens=20,
            output_tokens=8,
        ),
        CompletionResult(content="finished", tool_calls=[], stop_reason="end_turn",
                          input_tokens=15, output_tokens=6),
    ], max_tokens=200)
    console = _FakeRunConsole()
    loop = AgentLoop(
        provider,
        _registry_with_echo_tool(),
        console_mode="minimal",
        run_console=console,  # type: ignore[arg-type]
    )

    result = loop.run(
        skill_instructions="test",
        initial_prompt="abcd",
        stage_tools=["echo"],
    )

    assert result == "finished"
    assert console.context_calls[0] == {"turn": 1, "max_turns": 100, "tokens": 4, "cap": 200}
    assert console.context_calls[1]["turn"] == 2
    assert console.tool_results == [("echoed:hi", False)]
