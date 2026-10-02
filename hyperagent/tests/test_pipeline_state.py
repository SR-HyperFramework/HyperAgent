"""Tests for hyperagent.pipeline_state."""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from hyperagent import pipeline_state

REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_SCHEMA = REPO_ROOT / "skill" / "_hyperagent-common" / "schemas" / "state.schema.json"
VALID_SHA256 = "a" * 64


@pytest.fixture()
def report_dir(tmp_path: Path) -> Path:
    return tmp_path / "reports" / VALID_SHA256


def _assert_schema_valid(state: dict) -> None:
    schema = json.loads(STATE_SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(state, schema)


def test_ensure_state_creates_file(report_dir: Path) -> None:
    pipeline_state.ensure_state(report_dir, VALID_SHA256, "sample.exe")
    assert pipeline_state.state_path_for(report_dir).exists()
    state = pipeline_state.load_state(report_dir)
    _assert_schema_valid(state)
    assert state["sample_sha256"] == VALID_SHA256
    assert state["input_path"] == "sample.exe"
    assert state["report_dir"] == str(report_dir)
    assert state["current_stage_id"] == "01-prepare-env"
    assert state["last_error"] is None
    assert state["recommend_next_stage"]["action"] == pipeline_state.RECOMMEND_ACTION_RUN_NEXT
    for stage_id in pipeline_state.STAGE_IDS:
        assert state["stages"][stage_id]["skill"]
        assert state["stages"][stage_id]["status"] == pipeline_state.STATUS_PENDING


def test_ensure_state_is_idempotent(report_dir: Path) -> None:
    pipeline_state.ensure_state(report_dir, VALID_SHA256, "sample.exe")
    pipeline_state.checkpoint(
        report_dir, "01-prepare-env", str(report_dir / "_state" / "01-prepare-env.progress.md")
    )
    pipeline_state.ensure_state(report_dir, VALID_SHA256, "sample.exe")
    state = pipeline_state.load_state(report_dir)
    _assert_schema_valid(state)
    assert state["stages"]["01-prepare-env"]["status"] == pipeline_state.STATUS_RUNNING


def test_checkpoint_sets_running_and_progress_path(report_dir: Path) -> None:
    pipeline_state.ensure_state(report_dir, VALID_SHA256, "sample.exe")
    progress_path = report_dir / "_state" / "01-prepare-env.progress.md"
    pipeline_state.checkpoint(report_dir, "01-prepare-env", str(progress_path), "test")
    state = pipeline_state.load_state(report_dir)
    _assert_schema_valid(state)
    entry = state["stages"]["01-prepare-env"]
    assert entry["status"] == pipeline_state.STATUS_RUNNING
    assert entry["progress_path"] == str(progress_path)
    assert state["recommend_next_stage"]["action"] == pipeline_state.RECOMMEND_ACTION_RESUME_CURRENT
    assert state["recommend_next_stage"]["progress_path"] == str(progress_path)
    assert state["recommend_next_stage"]["reason"] == "test"


def test_complete_sets_completed_and_output_path(report_dir: Path) -> None:
    pipeline_state.ensure_state(report_dir, VALID_SHA256, "sample.exe")
    output_path = report_dir / "01-prepare-env.json"
    pipeline_state.complete(report_dir, "01-prepare-env", str(output_path), "done")
    state = pipeline_state.load_state(report_dir)
    _assert_schema_valid(state)
    entry = state["stages"]["01-prepare-env"]
    assert entry["status"] == pipeline_state.STATUS_COMPLETED
    assert entry["output_path"] == str(output_path)
    assert state["last_error"] is None
    assert state["recommend_next_stage"]["action"] == pipeline_state.RECOMMEND_ACTION_RUN_NEXT
    assert state["recommend_next_stage"]["stage_id"] == "02-static-pass1"
    assert state["recommend_next_stage"]["reason"] == "done"


def test_fail_records_retry_recommendation_without_schema_invalid_status(report_dir: Path) -> None:
    pipeline_state.ensure_state(report_dir, VALID_SHA256, "sample.exe")
    pipeline_state.fail(report_dir, "01-prepare-env", "boom")
    state = pipeline_state.load_state(report_dir)
    _assert_schema_valid(state)
    entry = state["stages"]["01-prepare-env"]
    assert entry["status"] == pipeline_state.STATUS_PENDING
    assert state["last_error"] == "[01-prepare-env] boom"
    assert state["recommend_next_stage"]["action"] == pipeline_state.RECOMMEND_ACTION_RETRY_STAGE
    assert state["recommend_next_stage"]["stage_id"] == "01-prepare-env"
    assert "boom" in state["recommend_next_stage"]["reason"]


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


def test_normalizes_legacy_v4_state_shape(report_dir: Path) -> None:
    report_dir.mkdir(parents=True)
    legacy = {
        "schema_version": "1.0",
        "timestamp_utc": "2026-08-19T00:00:00Z",
        "sample_sha256": VALID_SHA256,
        "input_path": "sample.exe",
        "stages": {
            "01-prepare-env": {
                "status": "failed",
                "output_path": None,
                "progress_path": None,
                "error": "boom",
                "updated_at": "2026-08-19T00:00:01Z",
            }
        },
    }
    pipeline_state.state_path_for(report_dir).write_text(json.dumps(legacy), encoding="utf-8")

    state = pipeline_state.load_state(report_dir)
    _assert_schema_valid(state)
    assert state["report_dir"] == str(report_dir)
    assert state["stages"]["01-prepare-env"]["skill"] == "hyperagent-prepare-env"
    assert state["stages"]["01-prepare-env"]["status"] == pipeline_state.STATUS_PENDING
    assert state["last_error"] == "[01-prepare-env] boom"


def test_load_state_missing_raises(report_dir: Path) -> None:
    with pytest.raises(FileNotFoundError):
        pipeline_state.load_state(report_dir)


def test_invalid_stage_id_raises(report_dir: Path) -> None:
    pipeline_state.ensure_state(report_dir, VALID_SHA256, "sample.exe")
    with pytest.raises(ValueError):
        pipeline_state.complete(report_dir, "not-a-stage", "x.json")
