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


def test_resolve_recorded_path_collapses_repo_relative_report_path(report_dir: Path) -> None:
    # Skills describe artifacts as reports/<sha256>/<file>; joined onto the
    # report dir that used to record report_dir/reports/<sha256>/<file>.
    relative = f"reports/{VALID_SHA256}/07-deepdive.json"
    assert pipeline_state.resolve_recorded_path(report_dir, relative) == str(
        report_dir / "07-deepdive.json"
    )
    doubled = report_dir / "reports" / VALID_SHA256 / "08-report.md"
    assert pipeline_state.resolve_recorded_path(report_dir, str(doubled)) == str(
        report_dir / "08-report.md"
    )


def test_load_state_repairs_doubled_output_paths(report_dir: Path) -> None:
    pipeline_state.ensure_state(report_dir, VALID_SHA256, "sample.exe")
    state = json.loads(pipeline_state.state_path_for(report_dir).read_text(encoding="utf-8"))
    state["stages"]["07-deepdive"]["status"] = "completed"
    state["stages"]["07-deepdive"]["output_path"] = str(
        report_dir / "reports" / VALID_SHA256 / "07-deepdive.json"
    )
    pipeline_state.state_path_for(report_dir).write_text(json.dumps(state), encoding="utf-8")

    loaded = pipeline_state.load_state(report_dir)
    assert loaded["stages"]["07-deepdive"]["output_path"] == str(report_dir / "07-deepdive.json")


def test_complete_falls_back_to_canonical_artifact(report_dir: Path, tmp_path: Path) -> None:
    pipeline_state.ensure_state(report_dir, VALID_SHA256, "sample.exe")
    (report_dir / "07-deepdive.json").write_text("{}", encoding="utf-8")
    wrong = tmp_path / "elsewhere" / "07-deepdive.json"
    pipeline_state.complete(report_dir, "07-deepdive", str(wrong))
    state = pipeline_state.load_state(report_dir)
    assert state["stages"]["07-deepdive"]["output_path"] == str(report_dir / "07-deepdive.json")


def test_fail_demotes_completed_stage(report_dir: Path) -> None:
    pipeline_state.ensure_state(report_dir, VALID_SHA256, "sample.exe")
    pipeline_state.complete(report_dir, "01-prepare-env", str(report_dir / "01-prepare-env.json"))
    pipeline_state.fail(report_dir, "01-prepare-env", "artifact failed validation")
    state = pipeline_state.load_state(report_dir)
    _assert_schema_valid(state)
    assert state["stages"]["01-prepare-env"]["status"] == pipeline_state.STATUS_PENDING
    assert state["recommend_next_stage"]["action"] == pipeline_state.RECOMMEND_ACTION_RETRY_STAGE


def test_stale_recommendation_is_reinferred(report_dir: Path) -> None:
    pipeline_state.ensure_state(report_dir, VALID_SHA256, "sample.exe")
    state = json.loads(pipeline_state.state_path_for(report_dir).read_text(encoding="utf-8"))
    state["stages"]["01-prepare-env"]["status"] = "completed"
    state["stages"]["01-prepare-env"]["output_path"] = str(report_dir / "01-prepare-env.json")
    # Still says "run 01 next" although 01 is completed.
    pipeline_state.state_path_for(report_dir).write_text(json.dumps(state), encoding="utf-8")
    loaded = pipeline_state.load_state(report_dir)
    assert loaded["recommend_next_stage"]["stage_id"] == "02-static-pass1"


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
