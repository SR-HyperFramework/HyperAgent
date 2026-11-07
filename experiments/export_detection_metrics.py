"""Export detection-quality metrics from the curated ``exp_test`` bundles.

Two outputs per condition:

* **observed** — confusion matrix computed from the curated sample rows only.
* **amplified** — the same rows bootstrapped to ``--samples`` with the same seed
  as ``amplify_runtime.py``, so runtime and detection previews share one seed.

This is a planning aid.  Amplified rows reuse real verdicts and are not new
measurements.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
RUNS = ROOT / "exp_test" / "runs"

BUNDLES = (
    "baseline_fresh_execution_archive",
    "llm_compare_gpt_5_6_luna",
    "ablation_no_intel_completed",
    "synthesis_only_gpt_5_6_terra",
    "synthesis_only_gpt_5_6_sol",
    "synthesis_only_minimax_m3",
)


def ratio(num: float, den: float) -> float:
    return num / den if den else 0.0


def confusion(pairs: list[tuple[bool, bool]]) -> dict[str, Any]:
    """Compute metrics from (actual_malicious, predicted_malicious) pairs."""
    tp = sum(1 for a, p in pairs if a and p)
    fn = sum(1 for a, p in pairs if a and not p)
    fp = sum(1 for a, p in pairs if not a and p)
    tn = sum(1 for a, p in pairs if not a and not p)

    precision = ratio(tp, tp + fp)
    recall = ratio(tp, tp + fn)
    f1 = ratio(2 * precision * recall, precision + recall)
    accuracy = ratio(tp + tn, tp + tn + fp + fn)

    return {
        "true_positives": tp,
        "false_positives": fp,
        "true_negatives": tn,
        "false_negatives": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "accuracy": round(accuracy, 4),
        "false_positive_rate": round(ratio(fp, fp + tn), 4),
        "false_negative_rate": round(ratio(fn, fn + tp), 4),
        "scored": tp + fp + tn + fn,
    }


def load_pairs(bundle: str) -> tuple[list[tuple[bool, bool]], dict[str, Any]]:
    curated = json.loads((RUNS / bundle / "curated_results.json").read_text(encoding="utf-8"))
    pairs: list[tuple[bool, bool]] = []
    refused = 0

    for row in curated["included_samples"]:
        if row.get("refused"):
            refused += 1
        predicted = row.get("predicted_malicious")
        label = row.get("label")
        if predicted is None or label not in {"malware", "benign"}:
            continue
        pairs.append((label == "malware", bool(predicted)))

    meta = {
        "included_rows": len(curated["included_samples"]),
        "refused_rows": refused,
        "malware_rows": sum(1 for a, _ in pairs if a),
        "benign_rows": sum(1 for a, _ in pairs if not a),
        "report_status": curated.get("report_status"),
        "scope": curated.get("scope"),
    }
    return pairs, meta


def wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval — stable for small n and extreme proportions."""
    if total == 0:
        return 0.0, 0.0
    phat = successes / total
    denom = 1 + z * z / total
    centre = (phat + z * z / (2 * total)) / denom
    spread = z * math.sqrt(phat * (1 - phat) / total + z * z / (4 * total * total)) / denom
    return max(0.0, centre - spread), min(1.0, centre + spread)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=32849123)
    parser.add_argument("--output", type=Path, default=ROOT / "exp_test" / "detection_metrics")
    args = parser.parse_args()

    measured = (ROOT / "results").resolve()
    if args.output.resolve().is_relative_to(measured):
        parser.error("output must not be written inside experiments/results")

    args.output.mkdir(parents=True, exist_ok=True)
    stem = f"detection_{args.samples}_seed_{args.seed}"
    report: dict[str, Any] = {
        "label": "DETECTION METRICS — observed rows plus amplified preview",
        "seed": args.seed,
        "amplified_samples_per_condition": args.samples,
        "observed_rows_are_measured": True,
        "amplified_rows_are_not_new_measurements": True,
        "conditions": {},
    }
    csv_rows: list[dict[str, Any]] = []

    for bundle in BUNDLES:
        pairs, meta = load_pairs(bundle)
        observed = confusion(pairs)

        # Wilson intervals quantify how little a handful of rows constrains the rate.
        tp_lo, tp_hi = wilson(observed["true_positives"], observed["true_positives"] + observed["false_negatives"])
        fp_lo, fp_hi = wilson(observed["false_positives"], observed["false_positives"] + observed["true_negatives"])

        rng = random.Random(args.seed)
        amplified = confusion([rng.choice(pairs) for _ in range(args.samples)]) if pairs else confusion([])

        report["conditions"][bundle] = {
            "observed": {
                **meta,
                **observed,
                "recall_95ci": [round(tp_lo, 4), round(tp_hi, 4)],
                "false_positive_rate_95ci": [round(fp_lo, 4), round(fp_hi, 4)],
            },
            "amplified_preview": amplified,
        }

        csv_rows.append({
            "condition": bundle,
            "scope": meta["scope"],
            "observed_n": observed["scored"],
            "observed_tp": observed["true_positives"],
            "observed_fp": observed["false_positives"],
            "observed_tn": observed["true_negatives"],
            "observed_fn": observed["false_negatives"],
            "observed_precision": observed["precision"],
            "observed_recall": observed["recall"],
            "observed_f1": observed["f1"],
            "observed_accuracy": observed["accuracy"],
            "observed_fpr": observed["false_positive_rate"],
            "amplified_tp": amplified["true_positives"],
            "amplified_fp": amplified["false_positives"],
            "amplified_tn": amplified["true_negatives"],
            "amplified_fn": amplified["false_negatives"],
            "amplified_precision": amplified["precision"],
            "amplified_recall": amplified["recall"],
            "amplified_f1": amplified["f1"],
            "amplified_accuracy": amplified["accuracy"],
        })

    with (args.output / f"{stem}.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(csv_rows[0].keys()))
        writer.writeheader()
        writer.writerows(csv_rows)

    (args.output / f"{stem}_summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# Detection metrics — observed rows and amplified preview",
        "",
        f"Seed `{args.seed}`; amplified rows per condition: `{args.samples}`.",
        "",
        "Observed columns come from the curated sample rows. Amplified columns",
        "bootstrap those same verdicts; they are not new measurements and carry no",
        "new information about model behaviour.",
        "",
        "| Condition | n | TP | FP | TN | FN | Precision | Recall | F1 | Accuracy |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in csv_rows:
        lines.append(
            f"| `{row['condition']}` | {row['observed_n']} | {row['observed_tp']} | {row['observed_fp']} "
            f"| {row['observed_tn']} | {row['observed_fn']} | {row['observed_precision']:.3f} "
            f"| {row['observed_recall']:.3f} | {row['observed_f1']:.3f} | {row['observed_accuracy']:.3f} |"
        )
    lines += [
        "",
        "## Limits",
        "",
        "- Small denominators: intervals are wide, so read every rate as indicative.",
        "- `baseline` rows exclude six reused-verdict samples, so this is not the",
        "  30-sample figure quoted elsewhere.",
        "- Synthesis-only conditions classify on seeded evidence; they are not",
        "  end-to-end detection results.",
        "- Refusals and errors are excluded from the matrix, not counted as benign.",
        "",
    ]
    (args.output / f"{stem}_README.md").write_text("\n".join(lines), encoding="utf-8")

    for row in csv_rows:
        print(f"{row['condition']:38s} n={row['observed_n']:3d} TP={row['observed_tp']:3d} FP={row['observed_fp']:3d} "
              f"FN={row['observed_fn']:3d} P={row['observed_precision']:.3f} R={row['observed_recall']:.3f} "
              f"F1={row['observed_f1']:.3f} Acc={row['observed_accuracy']:.3f}")
    print(f"Wrote detection metrics to {args.output}")


if __name__ == "__main__":
    main()
