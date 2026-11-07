"""Malware-category evaluation.

Matches HyperAgent's own predicted ``classification.malware_type`` /
``malware_family`` (free text, written by ``09-summary``'s skill --
see ``skill/hyperagent-summary/schema.json``) against the DikeDataset
ground-truth ``dominant_category`` recorded per malware sample in
``experiments/results/sample_selection.json`` (itself the argmax over the
per-category AV-consensus score columns in the dataset's ``malware.csv``:
generic/trojan/ransomware/worm/backdoor/spyware/rootkit/encrypter/downloader).

The pipeline's classification text is unconstrained prose, not the dataset's
fixed vocabulary, so this maps text -> category via keyword search
(``CATEGORY_KEYWORDS``) rather than exact string equality. Samples with no
classification text at all (stage never ran, or both fields null) are
excluded from the confusion matrix as unscored -- never silently counted as
a wrong guess. Benign samples have no ground-truth category and are not
part of this evaluation; use ``batch_eval.compute_aggregate`` for the
malicious/benign question.

Read-only: this does not invoke the pipeline, it only reads whatever
09-summary.json artifacts already exist under each sample's report dir.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from hyperagent import pipeline_state
from hyperagent.config import load_config

logger = logging.getLogger(__name__)

MANIFEST_PATH = Path("experiments/results/sample_selection.json")
VERDICT_STAGE_ID = "09-summary"

# Checked top-to-bottom, first match wins. More specific / less ambiguous
# signals sit above "trojan", since that word alone is a near-universal
# substring of other families' names (e.g. "Trojan-Downloader").
CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "ransomware": ("ransomware", "ransom"),
    "worm": ("worm",),
    "rootkit": ("rootkit",),
    "backdoor": ("backdoor", "remote access trojan", "remote-access trojan", " rat "),
    "spyware": ("spyware", "infostealer", "info-stealer", "info stealer", "keylogger", "stealer"),
    "downloader": ("downloader", "download trojan", "dropper"),
    "encrypter": ("encrypter", "encryptor", "crypter"),
    "trojan": ("trojan",),
}
#: No keyword hit -> mirrors the dataset's own "generic" bucket (AV
#: consensus malicious, no specific family signal).
FALLBACK_CATEGORY = "generic"


def load_ground_truth(manifest_path: Path = MANIFEST_PATH) -> dict[str, str]:
    """sha256 -> dominant_category, malware samples only (benign has none)."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for entry in manifest.get("malware", []):
        category = entry.get("dominant_category")
        if category:
            out[entry["hash"]] = category
    return out


def _report_dir_for_hash(sample_hash: str, sample_path: str, reports_root: Path | None) -> Path:
    root = reports_root or (Path(sample_path).parent / "reports")
    return Path(root) / sample_hash


def read_classification(report_dir: Path) -> dict[str, Any] | None:
    """Read the ``classification`` object out of ``<report_dir>/09-summary.json``."""
    summary_path = Path(
        pipeline_state.default_output_path(report_dir, VERDICT_STAGE_ID)
        or (report_dir / f"{VERDICT_STAGE_ID}.json")
    )
    if not summary_path.exists():
        return None
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not parse %s", summary_path, exc_info=True)
        return None
    classification = payload.get("classification")
    return classification if isinstance(classification, dict) else None


def predict_category(classification: dict[str, Any] | None) -> str | None:
    """Map free-text malware_type/malware_family to the ground-truth vocabulary.

    Returns ``None`` when there is no classification text to match against
    (caller must treat that as unscored, not as a miss).
    """
    if not classification:
        return None
    text = " ".join(
        str(classification.get(field) or "") for field in ("malware_type", "malware_family")
    ).lower()
    if not text.strip():
        return None
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return category
    return FALLBACK_CATEGORY


def _per_category_metrics(rows: list[dict], categories: list[str]) -> dict[str, dict[str, Any]]:
    per_category: dict[str, dict[str, Any]] = {}
    for cat in categories:
        actual = [r for r in rows if r["true_category"] == cat]
        predicted_as = [r for r in rows if r["predicted_category"] == cat]
        tp = sum(1 for r in actual if r["predicted_category"] == cat)
        precision = tp / len(predicted_as) if predicted_as else 0.0
        recall = tp / len(actual) if actual else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        per_category[cat] = {
            "support": len(actual),
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
    return per_category


def evaluate(manifest_path: Path = MANIFEST_PATH, reports_root: Path | None = None) -> dict[str, Any]:
    ground_truth = load_ground_truth(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_hash = {entry["hash"]: entry for entry in manifest.get("malware", [])}

    rows: list[dict[str, Any]] = []
    for sample_hash, true_category in ground_truth.items():
        entry = by_hash[sample_hash]
        report_dir = _report_dir_for_hash(sample_hash, entry["path"], reports_root)
        classification = read_classification(report_dir)
        predicted = predict_category(classification)
        rows.append(
            {
                "sample_sha256": sample_hash,
                "true_category": true_category,
                "predicted_category": predicted,
                "malware_type_text": (classification or {}).get("malware_type"),
                "malware_family_text": (classification or {}).get("malware_family"),
                "family_status": (classification or {}).get("family_status"),
                "match": (predicted == true_category) if predicted is not None else None,
            }
        )

    scored = [r for r in rows if r["predicted_category"] is not None]
    matches = sum(1 for r in scored if r["match"])

    categories = sorted({r["true_category"] for r in rows} | {r["predicted_category"] for r in scored})
    confusion: dict[str, dict[str, int]] = {t: {p: 0 for p in categories} for t in categories}
    for r in scored:
        confusion[r["true_category"]][r["predicted_category"]] += 1

    return {
        "sample_count": len(rows),
        "scored_count": len(scored),
        "unscored_count": len(rows) - len(scored),
        "category_accuracy": (matches / len(scored)) if scored else 0.0,
        "confusion_matrix": confusion,
        "per_category": _per_category_metrics(scored, categories),
        "per_sample": rows,
    }


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Match HyperAgent's predicted malware_type/malware_family against DikeDataset dominant_category"
    )
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--output", type=Path, default=Path("experiments/results/category_eval.json"))
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    config = load_config()
    report = evaluate(args.manifest, config.reports_root)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    summary = {k: v for k, v in report.items() if k != "per_sample"}
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    logger.info("Wrote %s", args.output)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
