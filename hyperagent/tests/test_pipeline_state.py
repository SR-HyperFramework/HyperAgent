"""Tests for hyperagent.pipeline_state."""
from __future__ import annotations

from pathlib import Path

import pytest

from hyperagent import pipeline_state


@pytest.fixture()
def report_dir(tmp_path: Path) -> Path:
    return tmp_path / "reports" / "abc123"


def test_ensure_state_creates_file(report_dir: Path) -> None:
    pipeline_state.ensure_state(report_dir, "abc123", "sample.exe")
    assert pipeline_state.state_path_for(report_dir).exists()
    state = pipeline_state.load_state(report_dir)
    assert state["sample_sha256"] == "abc123"
    assert state["input_path"] == "sample.exe"
    for stage_id in pipeline_state.STAGE_IDS:
        assert state["stages"][stage_id]["status"] == pipeline_state.STATUS_PENDING


def test_ensure_state_is_idempotent(report_dir: Path) -> None:
    pipeline_state.ensure_state(report_dir, "abc123", "sample.exe")
    pipeline_state.checkpoint(
        report_dir, "01-prepare-env", str(report_dir / "_state" / "01-prepare-env.progress.md")
    )
    pipeline_state.ensure_state(report_dir, "abc123", "sample.exe")
    state = pipeline_state.load_state(report_dir)
    assert state["stages"]["01-prepare-env"]["status"] == pipeline_state.STATUS_RUNNING


def test_checkpoint_sets_running_and_progress_path(report_dir: Path) -> None:
    pipeline_state.ensure_state(report_dir, "abc123", "sample.exe")
    progress_path = report_dir / "_state" / "01-prepare-env.progress.md"
    pipeline_state.checkpoint(report_dir, "01-prepare-env", str(progress_path), "test")
    state = pipeline_state.load_state(report_dir)
    entry = state["stages"]["01-prepare-env"]
    assert entry["status"] == pipeline_state.STATUS_RUNNING
    assert entry["progress_path"] == str(progress_path)


def test_complete_sets_completed_and_output_path(report_dir: Path) -> None:
    pipeline_state.ensure_state(report_dir, "abc123", "sample.exe")
    output_path = report_dir / "01-prepare-env.json"
    pipeline_state.complete(report_dir, "01-prepare-env", str(output_path))
    state = pipeline_state.load_state(report_dir)
    entry = state["stages"]["01-prepare-env"]
    assert entry["status"] == pipeline_state.STATUS_COMPLETED
    assert entry["output_path"] == str(output_path)
    assert entry["error"] is None


def test_fail_sets_failed_and_records_error(report_dir: Path) -> None:
    pipeline_state.ensure_state(report_dir, "abc123", "sample.exe")
    pipeline_state.fail(report_dir, "01-prepare-env", "boom")
    state = pipeline_state.load_state(report_dir)
    entry = state["stages"]["01-prepare-env"]
    assert entry["status"] == pipeline_state.STATUS_FAILED
    assert entry["error"] == "boom"


def test_default_output_path(report_dir: Path) -> None:
    assert pipeline_state.default_output_path(report_dir, "01-prepare-env") == str(
        report_dir / "01-prepare-env.json"
    )


def test_resolve_recorded_path_relative(report_dir: Path) -> None:
    resolved = pipeline_state.resolve_recorded_path(report_dir, "foo.json")
    assert resolved == str(report_dir / "foo.json")


def test_resolve_recorded_path_absolute(report_dir: Path, tmp_path: Path) -> None:
    abs_path = tmp_path / "elsewhere" / "foo.json"
    resolved = pipeline_state.resolve_recorded_path(report_dir, str(abs_path))
    assert resolved == str(abs_path)


def test_load_state_missing_raises(report_dir: Path) -> None:
    with pytest.raises(FileNotFoundError):
        pipeline_state.load_state(report_dir)


def test_invalid_stage_id_raises(report_dir: Path) -> None:
    pipeline_state.ensure_state(report_dir, "abc123", "sample.exe")
    with pytest.raises(ValueError):
        pipeline_state.complete(report_dir, "not-a-stage", "x.json")
