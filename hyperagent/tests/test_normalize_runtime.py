"""Tests for experiments.normalize_runtime_data.

The fixture bundles are written to ``tmp_path``: this suite must never read the
real ``experiments/exp_test/runs`` tree, which is machine-specific evidence.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

from experiments.normalize_runtime_data import (
    COLUMNS,
    DATA_ORIGIN,
    STAGE_ORDER,
    NormalisationError,
    load_labels,
    load_observed_vectors,
    main,
    normalise,
    summarise,
    validate_file,
    validate_rows,
    write_outputs,
)

BUNDLE = "baseline_fresh_execution_archive"


def _telemetry(stage_id: str, wall_seconds: float, run_id: str = "baseline-abc123") -> dict:
    return {
        "run_id": run_id,
        "sample_sha256": "a" * 64,
        "stage_id": stage_id,
        "stage_status": "completed",
        "wall_time_seconds": wall_seconds,
        "total_input_tokens": 1000,
        "total_output_tokens": 100,
        "turns": 4,
        "evaluation": {"effective_cost_usd": 0.5},
    }


def _write_bundle(
    bundles_root: Path,
    *,
    bundle: str = BUNDLE,
    samples: int = 2,
    stages: tuple[str, ...] = ("01-prepare-env", "09-summary"),
) -> None:
    for index in range(samples):
        report = bundles_root / bundle / "reports" / f"sample{index:02d}"
        report.mkdir(parents=True, exist_ok=True)
        records = [
            _telemetry(stage, 60.0 * (position + 1), run_id=f"baseline-{index:04d}")
            for position, stage in enumerate(stages)
        ]
        (report / "telemetry.curated.jsonl").write_text(
            "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
        )


def _write_labels(path: Path, rows: int = 4) -> None:
    labels = ["malicious", "benign", "malicious", "refused"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "sample_id",
                "actual_label",
                "predicted_label",
                "first_seen_month",
                "malware_family",
                "data_origin",
                "seed",
            ],
        )
        writer.writeheader()
        for index in range(rows):
            actual = labels[index % len(labels)]
            writer.writerow(
                {
                    "sample_id": f"synthetic-{index:04d}",
                    "actual_label": actual,
                    "predicted_label": actual if actual == "refused" else "malicious",
                    "first_seen_month": "2026-01",
                    "malware_family": "Trojan" if actual == "malicious" else "",
                    "data_origin": "synthetic_preview_not_measured",
                    "seed": "20260919",
                }
            )


def _dataset(tmp_path: Path, *, rows: int = 4, sigma: float = 0.0):
    bundles_root = tmp_path / "runs"
    _write_bundle(bundles_root)
    labels_path = tmp_path / "labels.csv"
    _write_labels(labels_path, rows)
    labels = load_labels(labels_path, rows)
    vectors, meta = load_observed_vectors(bundles_root)
    data = normalise(vectors, labels, seed=7, sigma=sigma)
    return data, meta, labels


def test_schema_matches_batch_eval_column_order(tmp_path: Path) -> None:
    rows, _, _ = _dataset(tmp_path)
    assert list(rows[0].keys()) == list(COLUMNS)
    assert COLUMNS[:6] == ("sample_id", "exp", "runtime_min", "cost_usd", "tokens", "turns")
    assert COLUMNS[6:15] == STAGE_ORDER


def test_every_row_keeps_provenance(tmp_path: Path) -> None:
    rows, _, _ = _dataset(tmp_path)
    for row in rows:
        assert row["data_origin"] == DATA_ORIGIN
        assert row["source_bundle"] == BUNDLE
        assert row["source_run_id"].startswith("baseline-")
    assert validate_rows(rows) == []


def test_stage_sum_equals_runtime(tmp_path: Path) -> None:
    rows, _, _ = _dataset(tmp_path, sigma=0.3)
    for row in rows:
        stage_sum = sum(row[stage] for stage in STAGE_ORDER)
        assert stage_sum == pytest.approx(row["runtime_min"], abs=0.01)


def test_labels_are_inherited_unchanged(tmp_path: Path) -> None:
    rows, _, labels = _dataset(tmp_path, rows=8)
    assert [row["actual_label"] for row in rows] == [label["actual_label"] for label in labels]
    assert [row["predicted_label"] for row in rows] == [
        label["predicted_label"] for label in labels
    ]


def test_label_counts_are_preserved_by_validation(tmp_path: Path) -> None:
    rows, _, labels = _dataset(tmp_path, rows=8)
    counts: dict[str, int] = {}
    for label in labels:
        key = f"{label['actual_label']}->{label['predicted_label']}"
        counts[key] = counts.get(key, 0) + 1
    assert validate_rows(rows, expected_samples=8, label_counts=counts) == []

    rows[0]["actual_label"] = "benign"
    problems = validate_rows(rows, expected_samples=8, label_counts=counts)
    assert any("label counts changed" in problem for problem in problems)


def test_validation_detects_erased_provenance(tmp_path: Path) -> None:
    rows, _, _ = _dataset(tmp_path)
    rows[1]["data_origin"] = "measured"
    rows[2]["source_run_id"] = ""
    problems = validate_rows(rows)
    assert any("provenance erased" in problem for problem in problems)
    assert any("missing source bundle/run id" in problem for problem in problems)


def test_validation_detects_stage_sum_drift(tmp_path: Path) -> None:
    rows, _, _ = _dataset(tmp_path)
    rows[0]["runtime_min"] = round(float(rows[0]["runtime_min"]) + 5.0, 3)
    problems = validate_rows(rows)
    assert any("stage sum" in problem for problem in problems)


def test_rejects_labels_with_unknown_verdict(tmp_path: Path) -> None:
    labels_path = tmp_path / "labels.csv"
    _write_labels(labels_path, 4)
    text = labels_path.read_text(encoding="utf-8").replace(
        "malicious,malicious", "malware,malicious"
    )
    labels_path.write_text(text, encoding="utf-8")
    with pytest.raises(NormalisationError, match="actual_label"):
        load_labels(labels_path, 4)


def test_rejects_label_row_count_mismatch(tmp_path: Path) -> None:
    labels_path = tmp_path / "labels.csv"
    _write_labels(labels_path, 4)
    with pytest.raises(NormalisationError, match="expected 5"):
        load_labels(labels_path, 5)


def test_failed_stage_time_is_excluded_by_default(tmp_path: Path) -> None:
    report = tmp_path / "runs" / BUNDLE / "reports" / "sample00"
    report.mkdir(parents=True)
    records = [
        _telemetry("01-prepare-env", 60.0),
        {**_telemetry("05-dynamic", 600.0), "stage_status": "failed"},
    ]
    (report / "telemetry.curated.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
    )

    default_vectors, default_meta = load_observed_vectors(tmp_path / "runs")
    assert default_vectors[0]["runtime_min"] == pytest.approx(1.0)
    assert default_meta["bundles"][BUNDLE]["excluded_failed_stage_minutes"] == 10.0
    assert "05-dynamic" in default_meta["bundles"][BUNDLE]["missing_stages"]

    included_vectors, included_meta = load_observed_vectors(
        tmp_path / "runs", include_failed_stages=True
    )
    assert included_vectors[0]["runtime_min"] == pytest.approx(11.0)
    assert included_meta["bundles"][BUNDLE]["excluded_failed_stage_minutes"] == 0.0
    assert included_meta["bundles"][BUNDLE]["stages_present"] == ["01-prepare-env", "05-dynamic"]


def test_rejects_bundle_without_telemetry(tmp_path: Path) -> None:
    (tmp_path / "runs" / BUNDLE / "reports" / "empty").mkdir(parents=True)
    with pytest.raises(NormalisationError, match="no measured telemetry"):
        load_observed_vectors(tmp_path / "runs")


def test_deterministic_for_a_fixed_seed(tmp_path: Path) -> None:
    first, _, _ = _dataset(tmp_path, rows=8)
    second, _, _ = _dataset(tmp_path, rows=8)
    assert first == second


def test_write_then_validate_roundtrip(tmp_path: Path) -> None:
    rows, meta, labels = _dataset(tmp_path)
    summary = summarise(rows, 7, 0.2, meta)
    summary["selected_conditions"] = [BUNDLE]
    summary["condition_note"] = "test"
    paths = write_outputs(rows, summary, tmp_path / "out", stem="runtime_4", reproduce="pytest")
    assert paths["csv"].exists() and paths["summary"].exists() and paths["readme"].exists()

    problems = validate_file(
        paths["csv"], expected_samples=len(rows), labels_path=tmp_path / "labels.csv"
    )
    assert problems == []
    assert "not measured" in paths["readme"].read_text(encoding="utf-8").lower()


def test_refuses_to_write_inside_measured_results(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        sys, "argv", ["normalize_runtime_data.py", "--output", "experiments/results/runtime_3000"]
    )
    with pytest.raises(SystemExit):
        main()
