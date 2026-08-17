"""Tests for experiments.batch_eval.

``run_pipeline_with_config`` is mocked throughout: the suite must never need a
real sample, VM, or LLM call.
"""
from __future__ import annotations

import asyncio
import csv
import json
import logging
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from experiments.batch_eval import (
    LABEL_BENIGN,
    LABEL_MALWARE,
    BatchEvaluator,
    SampleMeta,
    compute_aggregate,
    discover_samples,
    read_verdict,
    verdict_is_malicious,
)

FIXTURE_CORPUS = Path(__file__).parent / "fixtures" / "corpus"


class _FakeRunMetrics:
    """Stand-in for RunMetrics with only the fields batch_eval reads."""

    def __init__(self) -> None:
        self.total_input_tokens = 1000
        self.total_output_tokens = 200
        self.total_effective_cost_usd = 0.05
        self.total_wall_time_seconds = 12.5
        self.stages = [object(), object()]


@pytest.fixture()
def config(tmp_path: Path):
    return SimpleNamespace(reports_root=tmp_path / "reports")


def _write_summary(reports_root: Path, sample_path: Path, verdict: str) -> None:
    """Write a 09-summary.json where the evaluator will look for it."""
    from experiments.batch_eval import _sha256_of

    report_dir = reports_root / _sha256_of(sample_path)
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "09-summary.json").write_text(
        json.dumps({"verdict": verdict}), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# temporal_split
# ---------------------------------------------------------------------------

def test_temporal_split_buckets_by_first_seen(config):
    evaluator = BatchEvaluator(config)
    samples = [
        SampleMeta(Path("old.exe"), LABEL_MALWARE, date(2025, 1, 1)),
        SampleMeta(Path("new.exe"), LABEL_MALWARE, date(2025, 12, 1)),
        SampleMeta(Path("on_boundary.exe"), LABEL_BENIGN, date(2025, 6, 1)),
    ]

    before, after = evaluator.temporal_split(samples, date(2025, 6, 1))

    assert [s.path.name for s in before] == ["old.exe"]
    # A sample first seen exactly on the split date belongs to the "after" half.
    assert [s.path.name for s in after] == ["new.exe", "on_boundary.exe"]


def test_temporal_split_logs_and_drops_samples_without_first_seen(config, caplog):
    evaluator = BatchEvaluator(config)
    samples = [
        SampleMeta(Path("dated.exe"), LABEL_MALWARE, date(2025, 1, 1)),
        SampleMeta(Path("undated.exe"), LABEL_BENIGN, None),
    ]

    with caplog.at_level(logging.WARNING, logger="experiments.batch_eval"):
        before, after = evaluator.temporal_split(samples, date(2025, 6, 1))

    assert [s.path.name for s in before] == ["dated.exe"]
    assert after == []
    # Dropped samples must be named in the log, not silently excluded.
    assert "undated.exe" in caplog.text
    assert "dated.exe" not in caplog.text.replace("undated.exe", "")


# ---------------------------------------------------------------------------
# corpus discovery
# ---------------------------------------------------------------------------

def test_discover_samples_reads_first_seen_sidecar():
    samples = discover_samples(FIXTURE_CORPUS / "malware", LABEL_MALWARE)

    assert [s.path.name for s in samples] == ["mal_a.exe", "mal_b.exe"]
    assert all(s.label == LABEL_MALWARE for s in samples)
    assert samples[0].first_seen == date(2025, 1, 15)
    # first_seen.json itself is metadata, never a sample.
    assert not any(s.path.name == "first_seen.json" for s in samples)


def test_discover_samples_missing_sidecar_entry_yields_none():
    samples = discover_samples(FIXTURE_CORPUS / "benign", LABEL_BENIGN)
    by_name = {s.path.name: s for s in samples}

    assert by_name["ben_a.exe"].first_seen == date(2025, 2, 20)
    assert by_name["ben_b.exe"].first_seen is None


def test_discover_samples_missing_directory_returns_empty(tmp_path: Path):
    assert discover_samples(tmp_path / "nope", LABEL_MALWARE) == []


# ---------------------------------------------------------------------------
# verdict extraction
# ---------------------------------------------------------------------------

def test_read_verdict_finds_nested_verdict(tmp_path: Path):
    (tmp_path / "09-summary.json").write_text(
        json.dumps({"summary": {"final_verdict": "Malicious"}}), encoding="utf-8"
    )
    assert read_verdict(tmp_path) == "malicious"


def test_read_verdict_returns_none_when_artifact_missing(tmp_path: Path):
    assert read_verdict(tmp_path) is None


@pytest.mark.parametrize(
    ("verdict", "expected"),
    [("malicious", True), ("benign", False), ("suspicious", True), (None, None)],
)
def test_verdict_is_malicious(verdict, expected):
    assert verdict_is_malicious(verdict) is expected


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------

def test_compute_aggregate_confusion_matrix_and_pipeline_fpr():
    rows = [
        {"label": LABEL_MALWARE, "predicted_malicious": True},   # TP
        {"label": LABEL_MALWARE, "predicted_malicious": False},  # FN
        {"label": LABEL_BENIGN, "predicted_malicious": True},    # FP
        {"label": LABEL_BENIGN, "predicted_malicious": False},   # TN
        {"label": LABEL_BENIGN, "predicted_malicious": None},    # error, excluded
    ]

    agg = compute_aggregate(rows)

    assert (agg["true_positives"], agg["false_negatives"]) == (1, 1)
    assert (agg["false_positives"], agg["true_negatives"]) == (1, 1)
    assert agg["error_count"] == 1
    assert agg["scored_count"] == 4
    assert agg["precision"] == pytest.approx(0.5)
    assert agg["recall"] == pytest.approx(0.5)
    assert agg["f1"] == pytest.approx(0.5)
    # Pipeline-level FPR: 1 benign misflagged out of 2 scored benign samples.
    assert agg["pipeline_fpr"] == pytest.approx(0.5)


def test_compute_aggregate_empty_rows_does_not_divide_by_zero():
    agg = compute_aggregate([])
    assert agg["precision"] == 0.0
    assert agg["pipeline_fpr"] == 0.0
    assert agg["sample_count"] == 0


# ---------------------------------------------------------------------------
# evaluate_corpus
# ---------------------------------------------------------------------------

def test_evaluate_corpus_scores_verdicts_and_writes_outputs(tmp_path: Path, config):
    reports_root = Path(config.reports_root)
    malware_dir = FIXTURE_CORPUS / "malware"
    benign_dir = FIXTURE_CORPUS / "benign"

    # Perfect classification except ben_b.exe, which the pipeline misflags.
    _write_summary(reports_root, malware_dir / "mal_a.exe", "malicious")
    _write_summary(reports_root, malware_dir / "mal_b.exe", "malicious")
    _write_summary(reports_root, benign_dir / "ben_a.exe", "benign")
    _write_summary(reports_root, benign_dir / "ben_b.exe", "malicious")

    calls: list[tuple] = []

    async def _fake_run(sample_path, cfg, ablation_config, *, run_id=None):
        calls.append((Path(sample_path).name, run_id))
        return _FakeRunMetrics()

    evaluator = BatchEvaluator(config, run_fn=_fake_run)
    output_dir = tmp_path / "results"
    report = asyncio.run(
        evaluator.evaluate_corpus(
            malware_dir=malware_dir,
            benign_dir=benign_dir,
            output_dir=output_dir,
        )
    )

    assert len(calls) == 4
    assert all(run_id and len(run_id) == 64 for _, run_id in calls)

    agg = report.aggregate
    assert agg["true_positives"] == 2
    assert agg["false_positives"] == 1
    assert agg["recall"] == pytest.approx(1.0)
    assert agg["pipeline_fpr"] == pytest.approx(0.5)
    assert agg["total_token_cost_usd"] == pytest.approx(0.2)

    csv_path = output_dir / "batch_eval_per_sample.csv"
    jsonl_path = output_dir / "batch_eval.jsonl"
    assert csv_path.exists() and jsonl_path.exists()

    with csv_path.open(encoding="utf-8", newline="") as fh:
        csv_rows = list(csv.DictReader(fh))
    assert len(csv_rows) == 4
    assert {row["label"] for row in csv_rows} == {LABEL_MALWARE, LABEL_BENIGN}

    dumped = json.loads(jsonl_path.read_text(encoding="utf-8").strip())
    assert len(dumped["per_sample"]) == 4
    assert dumped["temporal_drift"] is None


def test_evaluate_corpus_records_pipeline_failure_without_aborting(tmp_path: Path, config):
    malware_dir = FIXTURE_CORPUS / "malware"
    benign_dir = FIXTURE_CORPUS / "benign"

    async def _failing_run(sample_path, cfg, ablation_config, *, run_id=None):
        if Path(sample_path).name == "mal_a.exe":
            raise RuntimeError("provider exploded")
        return _FakeRunMetrics()

    evaluator = BatchEvaluator(config, run_fn=_failing_run)
    report = asyncio.run(
        evaluator.evaluate_corpus(
            malware_dir=malware_dir,
            benign_dir=benign_dir,
            output_dir=tmp_path / "results",
        )
    )

    # All 4 samples still produce a row; the failure is recorded, not fatal.
    assert len(report.per_sample) == 4
    failed = next(r for r in report.per_sample if r["sample_path"].endswith("mal_a.exe"))
    assert "provider exploded" in failed["error"]
    assert failed["predicted_malicious"] is None
    assert report.aggregate["error_count"] == 4  # no summary artifacts written


def test_evaluate_corpus_quick_test_caps_sample_count(tmp_path: Path, config, monkeypatch):
    monkeypatch.setattr("experiments.batch_eval.QUICK_TEST_PER_CLASS", 1)

    seen: list[str] = []

    async def _fake_run(sample_path, cfg, ablation_config, *, run_id=None):
        seen.append(Path(sample_path).name)
        return _FakeRunMetrics()

    evaluator = BatchEvaluator(config, run_fn=_fake_run)
    asyncio.run(
        evaluator.evaluate_corpus(
            malware_dir=FIXTURE_CORPUS / "malware",
            benign_dir=FIXTURE_CORPUS / "benign",
            output_dir=tmp_path / "results",
            quick_test=True,
        )
    )

    assert seen == ["mal_a.exe", "ben_a.exe"]


def test_evaluate_corpus_temporal_drift_excludes_undated_sample(tmp_path: Path, config):
    reports_root = Path(config.reports_root)
    malware_dir = FIXTURE_CORPUS / "malware"
    benign_dir = FIXTURE_CORPUS / "benign"

    _write_summary(reports_root, malware_dir / "mal_a.exe", "malicious")
    _write_summary(reports_root, malware_dir / "mal_b.exe", "benign")
    _write_summary(reports_root, benign_dir / "ben_a.exe", "benign")
    _write_summary(reports_root, benign_dir / "ben_b.exe", "benign")

    async def _fake_run(sample_path, cfg, ablation_config, *, run_id=None):
        return _FakeRunMetrics()

    evaluator = BatchEvaluator(config, run_fn=_fake_run)
    report = asyncio.run(
        evaluator.evaluate_corpus(
            malware_dir=malware_dir,
            benign_dir=benign_dir,
            output_dir=tmp_path / "results",
            split_date=date(2025, 6, 1),
        )
    )

    drift = report.temporal_drift
    assert drift is not None
    assert drift["split_date"] == "2025-06-01"
    # mal_a (Jan) + ben_a (Feb) before; mal_b (Nov) after; ben_b undated -> neither.
    assert drift["before"]["sample_count"] == 2
    assert drift["after"]["sample_count"] == 1
    assert any(p.endswith("ben_b.exe") for p in drift["excluded_no_first_seen"])
    # Recall drops from 1.0 (mal_a caught) to 0.0 (mal_b missed) after the split.
    assert drift["f1_delta"] < 0
