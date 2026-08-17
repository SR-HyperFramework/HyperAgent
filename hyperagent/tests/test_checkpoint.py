"""Tests for hyperagent.engine.checkpoint."""
from __future__ import annotations

from pathlib import Path

import pytest

from hyperagent import pipeline_state
from hyperagent.engine.checkpoint import CheckpointReached, ContextTracker, write_checkpoint
from hyperagent.providers.base import LLMProvider, Message


class _CharProvider(LLMProvider):
    """Counts characters so token math is exactly predictable."""

    def complete(self, messages, *, tools=None, system_prompt="", max_tokens=None,
                 temperature=None):
        raise NotImplementedError

    def count_tokens(self, text: str) -> int:
        return len(text)

    def max_context_tokens(self) -> int:
        return 100


def test_context_tracker_raises_at_threshold():
    tracker = ContextTracker(_CharProvider(), threshold=0.5)
    messages = [Message(role="user", content="x" * 60)]
    with pytest.raises(CheckpointReached) as exc_info:
        tracker.check_messages(messages)
    assert exc_info.value.tokens == 60
    assert exc_info.value.ratio == pytest.approx(0.6)


def test_context_tracker_below_threshold_does_not_raise():
    tracker = ContextTracker(_CharProvider(), threshold=0.75)
    messages = [Message(role="user", content="x" * 10)]
    tracker.check_messages(messages)
    assert tracker.current_tokens == 10
    assert tracker.max_tokens == 100


def test_write_checkpoint_writes_progress_file_and_updates_state(tmp_path: Path):
    report_dir = tmp_path / "reports" / "abc123"
    pipeline_state.ensure_state(report_dir, "abc123", "sample.exe")

    progress_path = write_checkpoint(report_dir, "01-prepare-env", "50% done", "context threshold")

    assert progress_path == report_dir / "_state" / "01-prepare-env.progress.md"
    assert progress_path.read_text(encoding="utf-8") == "50% done"

    state = pipeline_state.load_state(report_dir)
    entry = state["stages"]["01-prepare-env"]
    assert entry["status"] == pipeline_state.STATUS_RUNNING
    assert entry["progress_path"] == str(progress_path)
