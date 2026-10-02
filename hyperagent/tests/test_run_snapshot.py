"""Tests for hyperagent.run_snapshot."""

from __future__ import annotations

import json
from pathlib import Path

from hyperagent import pipeline_state
from hyperagent.run_snapshot import JsonFileCache, load_snapshot
from hyperagent.tests.live_fixtures import ESCAPE, SHA, build_run_dir, write_json


def _statuses(snapshot) -> dict[str, str]:
    return {stage.stage_id: stage.status for stage in snapshot.stages}


def test_missing_state_reports_nonexistent_run(tmp_path: Path):
    snapshot = load_snapshot(tmp_path / SHA)

    assert snapshot.exists is False
    assert snapshot.stages == ()
    assert snapshot.sha256 == SHA


def test_snapshot_reads_stage_progress_findings_and_indicators(tmp_path: Path):
    report_dir = build_run_dir(tmp_path)

    snapshot = load_snapshot(report_dir)

    assert snapshot.exists is True
    statuses = _statuses(snapshot)
    assert statuses["01-prepare-env"] == "completed"
    assert statuses["02-static-pass1"] == "completed"
    # Without a live console, STATE.json's "running" cannot be told apart from
    # a checkpoint waiting to resume, so it is reported as written.
    assert statuses["03-unpack"] == "running"
    assert statuses["04-static-pass2"] == "pending"
    assert snapshot.completed_count == 3

    static = next(stage for stage in snapshot.stages if stage.stage_id == "02-static-pass1")
    assert (static.findings, static.evidence) == (2, 3)
    dynamic = next(stage for stage in snapshot.stages if stage.stage_id == "05-dynamic")
    assert dynamic.artifact_status == "partial"

    assert snapshot.evidence_total == 6
    assert [item.title for item in snapshot.findings_newest_first] == [
        "Decoded payload executed",
        "Packed PE32 loader",
        "Possible anti-debug check",
    ]
    assert [(item.group, item.value) for item in snapshot.indicators] == [
        ("network", "evil.example.com"),
        ("host", f"C:/Users/Public/drop{ESCAPE}.exe"),
        ("persistence", "HKCU/Software/Microsoft/Windows/CurrentVersion/Run/updater"),
    ]
    assert snapshot.verdict is not None
    assert (snapshot.verdict.value, snapshot.verdict.source) == ("suspicious", "07-deepdive")
    assert snapshot.outcome == "incomplete"


def test_active_stage_separates_running_from_checkpointed(tmp_path: Path):
    report_dir = build_run_dir(tmp_path)

    snapshot = load_snapshot(report_dir, active_stage_id="04-static-pass2")

    statuses = _statuses(snapshot)
    assert statuses["03-unpack"] == "checkpointed"
    assert statuses["04-static-pass2"] == "running"


def test_last_error_marks_stage_failed(tmp_path: Path):
    report_dir = build_run_dir(tmp_path)
    pipeline_state.fail(report_dir, "04-static-pass2", "boom")

    snapshot = load_snapshot(report_dir)

    assert _statuses(snapshot)["04-static-pass2"] == "failed"
    assert snapshot.last_error == "[04-static-pass2] boom"
    assert snapshot.outcome == "failed"


def test_summary_indicators_lead_and_dedupe_and_its_verdict_wins(tmp_path: Path):
    report_dir = build_run_dir(tmp_path, with_summary=True)

    snapshot = load_snapshot(report_dir)

    values = [(item.group, item.value, item.source) for item in snapshot.indicators]
    assert values[0] == ("network", "evil.example.com", "09-summary")
    assert sum(1 for _, value, _ in values if value == "evil.example.com") == 1
    assert (snapshot.verdict.value, snapshot.verdict.confidence, snapshot.verdict.source) == (
        "malicious",
        0.85,
        "09-summary",
    )


def test_stage_ids_limit_the_view_to_the_selected_profile(tmp_path: Path):
    report_dir = build_run_dir(tmp_path)

    snapshot = load_snapshot(
        report_dir, stage_ids=("01-prepare-env", "02-static-pass1", "07-deepdive")
    )

    assert [stage.stage_id for stage in snapshot.stages] == [
        "01-prepare-env",
        "02-static-pass1",
        "07-deepdive",
    ]
    # 05-dynamic was not selected, so its leftover artifact is not this run's evidence.
    assert snapshot.indicators == ()
    assert {item.stage_id for item in snapshot.findings} == {"02-static-pass1"}


def test_malformed_artifact_degrades_to_no_data(tmp_path: Path):
    report_dir = build_run_dir(tmp_path)
    (report_dir / "05-dynamic.json").write_text("{ half-written", encoding="utf-8")

    snapshot = load_snapshot(report_dir)

    dynamic = next(stage for stage in snapshot.stages if stage.stage_id == "05-dynamic")
    assert dynamic.status == "completed"
    assert dynamic.findings == 0
    assert snapshot.indicators == ()


def test_recorded_output_path_outside_report_dir_is_ignored(tmp_path: Path):
    report_dir = build_run_dir(tmp_path)
    outside = tmp_path / "elsewhere.json"
    write_json(outside, {"findings": [{"id": "x", "title": "Should not be read", "evidence": []}]})
    state_path = pipeline_state.state_path_for(report_dir)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["stages"]["02-static-pass1"]["output_path"] = str(outside)
    state_path.write_text(json.dumps(state), encoding="utf-8")

    snapshot = load_snapshot(report_dir)

    assert "Should not be read" not in [item.title for item in snapshot.findings]
    assert "Packed PE32 loader" in [item.title for item in snapshot.findings]


def test_json_cache_reparses_only_changed_files(tmp_path: Path):
    path = tmp_path / "a.json"
    write_json(path, {"n": 1})
    cache = JsonFileCache()

    first = cache.load(path)
    assert cache.load(path) is first

    write_json(path, {"n": 2, "pad": "x" * 10})
    assert cache.load(path) == {"n": 2, "pad": "x" * 10}
    assert cache.load(tmp_path / "missing.json") is None


def test_to_dict_is_json_serializable(tmp_path: Path):
    report_dir = build_run_dir(tmp_path)

    payload = load_snapshot(report_dir).to_dict()

    assert json.loads(json.dumps(payload))["completed_count"] == 3
    assert payload["outcome"] == "incomplete"
