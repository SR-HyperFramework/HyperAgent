"""Tests for experiments.label_eval (read-only verdict vs DikeDataset scoring)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiments.label_eval import (
    LABEL_BENIGN,
    LABEL_MALWARE,
    collect,
    confusion_metrics,
    evaluate,
    load_labels,
    mcnemar_exact,
    roc_auc,
    verdict_score,
    wilson_interval,
)

MAL = "a" * 64
BEN = "b" * 64
MAL2 = "c" * 64
HEADER = "type,hash,malice,generic,trojan,ransomware,worm,backdoor,spyware,rootkit,encrypter,downloader\n"


@pytest.fixture()
def labels_dir(tmp_path: Path) -> Path:
    d = tmp_path / "labels"
    d.mkdir()
    (d / "benign.csv").write_text(HEADER + f"0,{BEN},0,0,0,0,0,0,0,0,0,0\n", encoding="utf-8")
    (d / "malware.csv").write_text(
        HEADER
        + f"0,{MAL},0.95,0.1,0.8,0,0,0,0,0,0.1,0\n"
        + f"0,{MAL2},0.70,0.2,0.1,0,0,0.7,0,0,0,0\n",
        encoding="utf-8",
    )
    return d


def _summary(root: Path, sha: str, verdict: str, *, confidence: float = 0.9,
             path: str | None = None, intel: bool = False) -> None:
    d = root / sha
    d.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "completed",
        "sample": {"sha256": sha, "absolute_path": path or f"D:\\corpus\\{sha}.bin"},
        "executive_summary": {"verdict": verdict, "confidence": confidence,
                              "one_sentence_summary": "x"},
        # A nested verdict must never be read instead of the executive one.
        "confirmed_findings": [{"verdict": "benign"}],
    }
    (d / "09-summary.json").write_text(json.dumps(payload), encoding="utf-8")
    if intel:
        (d / "06-intel.json").write_text("{}", encoding="utf-8")


def test_load_labels_reads_class_malice_and_category(labels_dir: Path) -> None:
    labels = load_labels(labels_dir)
    assert labels[BEN].label == LABEL_BENIGN and labels[BEN].category == ""
    assert labels[MAL].label == LABEL_MALWARE and labels[MAL].category == "trojan"
    assert labels[MAL2].malice == pytest.approx(0.70)


def test_load_labels_drops_hash_listed_in_both_files(labels_dir: Path) -> None:
    with (labels_dir / "benign.csv").open("a", encoding="utf-8") as fh:
        fh.write(f"0,{MAL},0,0,0,0,0,0,0,0,0,0\n")
    assert MAL not in load_labels(labels_dir)


def test_collect_reads_executive_verdict_and_flags(tmp_path: Path, labels_dir: Path) -> None:
    root = tmp_path / "cond" / "reports"
    _summary(root, MAL, "malicious", intel=True)
    _summary(root, BEN, "benign", path=f"H:\\Dataset\\files\\b\\{BEN}.exe")
    rows = {r.sha256: r for r in collect({"cond": root}, load_labels(labels_dir))}

    assert rows[MAL].verdict == "malicious"
    assert rows[MAL].intel_present and not rows[MAL].controlled
    assert rows[BEN].verdict == "benign"
    assert rows[BEN].path_reveals_label and rows[BEN].controlled and not rows[BEN].blind


def test_collect_marks_reused_and_missing_from_progress(tmp_path: Path, labels_dir: Path) -> None:
    cond = tmp_path / "cond"
    _summary(cond / "reports", MAL, "malicious")
    progress = [
        {"sample_sha256": MAL, "input_tokens": 0, "stage_count": 0, "error": ""},
        {"sample_sha256": BEN, "input_tokens": 500, "stage_count": 8, "error": ""},
    ]
    (cond / "progress.jsonl").write_text("\n".join(json.dumps(r) for r in progress), encoding="utf-8")
    rows = {r.sha256: r for r in collect({"cond": cond / "reports"}, load_labels(labels_dir))}

    assert rows[MAL].reused and not rows[MAL].controlled
    assert rows[BEN].error == "no 09-summary.json"
    assert not rows[BEN].controlled and not rows[BEN].blind


def test_abstention_is_never_scored_as_benign(tmp_path: Path, labels_dir: Path) -> None:
    root = tmp_path / "cond" / "reports"
    _summary(root, MAL, "malicious")
    _summary(root, BEN, "inconclusive")
    rows = collect({"cond": root}, load_labels(labels_dir))

    decided = confusion_metrics(rows, "lenient", abstain_as_error=False)
    assert (decided["tp"], decided["tn"], decided["fp"], decided["abstained"]) == (1, 0, 0, 1)
    assert decided["coverage"] == 0.5

    worst = confusion_metrics(rows, "lenient", abstain_as_error=True)
    assert (worst["tp"], worst["tn"], worst["fp"]) == (1, 0, 1)
    assert worst["accuracy"] == 0.5


def test_policies_differ_only_on_suspicious(tmp_path: Path, labels_dir: Path) -> None:
    root = tmp_path / "cond" / "reports"
    _summary(root, MAL, "suspicious")
    _summary(root, BEN, "suspicious")
    rows = collect({"cond": root}, load_labels(labels_dir))

    lenient = confusion_metrics(rows, "lenient", abstain_as_error=True)
    strict = confusion_metrics(rows, "strict", abstain_as_error=True)
    assert (lenient["tp"], lenient["fp"]) == (1, 1)
    assert (strict["fn"], strict["tn"]) == (1, 1)


def test_verdict_score_orders_classes() -> None:
    ordered = [verdict_score("benign", 0.9), verdict_score("benign", 0.2),
               verdict_score("inconclusive", 0.9), verdict_score("suspicious", 0.9),
               verdict_score("malicious", 0.9)]
    assert ordered == sorted(ordered)
    assert verdict_score("banana", 0.5) is None


def test_statistics_helpers() -> None:
    assert roc_auc([(True, 0.9), (False, 0.1)]) == 1.0
    assert roc_auc([(True, 0.5), (False, 0.5)]) == 0.5
    assert roc_auc([(True, 0.9)]) is None
    lo, hi = wilson_interval(10, 10)
    assert hi == 1.0 and 0.69 < lo < 0.73
    assert wilson_interval(0, 0) is None
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(0, 5) == pytest.approx(0.0625)


def test_evaluate_pairs_conditions_on_shared_samples(tmp_path: Path, labels_dir: Path) -> None:
    labels = load_labels(labels_dir)
    for name, verdicts in (("a", ("malicious", "benign", "malicious")),
                           ("b", ("benign", "benign", "unknown"))):
        root = tmp_path / name / "reports"
        for sha, verdict in zip((MAL, BEN, MAL2), verdicts):
            _summary(root, sha, verdict)
    rows = collect({"a": tmp_path / "a" / "reports", "b": tmp_path / "b" / "reports"}, labels)
    result = evaluate(rows)
    assert result["paired"] == []  # fewer than 5 shared samples

    from experiments.label_eval import paired_comparisons
    pair = paired_comparisons(rows, min_shared=1)[0]
    assert (pair["a_correct"], pair["b_correct"], pair["only_a_correct"]) == (3, 1, 2)
