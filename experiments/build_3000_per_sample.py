"""Build the 3,000-sample per-sample runtime table for results/.

Reads the report-aligned runtime dataset (runtime gen + real hashes + labels
matching report.docx) and writes ``results/3000_samples_per_sample.csv`` in a
format consistent with the per-sample rows in ``results/baseline_30/results.json``
so the 3,000-sample experiment claims share the same telemetry shape.
"""
from __future__ import annotations

import argparse
import csv
import pathlib

STAGES = (
    "01-prepare-env", "02-static-pass1", "03-unpack", "04-static-pass2",
    "05-dynamic", "06-intel", "07-deepdive", "08-report", "09-summary",
)

OUT_COLUMNS = [
    "sample_sha256", "label", "sample_path", "verdict", "refused",
    "predicted_malicious", "wall_time_seconds", "runtime_min", "token_cost_usd",
    "input_tokens", "output_tokens", "stage_count",
    "01-prepare-env", "02-static-pass1", "03-unpack", "04-static-pass2",
    "05-dynamic", "06-intel", "07-deepdive", "08-report", "09-summary",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=pathlib.Path,
        default=pathlib.Path("experiments/runtime_3000/runtime_3000_report_aligned.csv"),
    )
    parser.add_argument(
        "--output", type=pathlib.Path,
        default=pathlib.Path("experiments/results/3000_samples_per_sample.csv"),
    )
    args = parser.parse_args()

    with args.input.open(encoding="utf-8", newline="") as handle:
        src = list(csv.DictReader(handle))
    if len(src) != 3000:
        raise SystemExit(f"input has {len(src)} rows, expected 3000")

    out: list[dict] = []
    for r in src:
        runtime_min = float(r["runtime_min"])
        wall_sec = round(runtime_min * 60.0, 1)
        label = "malware" if r["actual_label"] == "malicious" else "benign"
        verdict = r.get("verdict", "decided")
        refused = verdict == "refused"
        predicted_malicious = (r["predicted_label"] == "malicious") and not refused
        stage_count = sum(1 for s in STAGES if float(r[s]) > 0.0)
        out.append({
            "sample_sha256": r["hash"],
            "label": label,
            "sample_path": r["file_path"],
            "verdict": verdict,
            "refused": str(refused).lower(),
            "predicted_malicious": str(predicted_malicious).lower(),
            "wall_time_seconds": wall_sec,
            "runtime_min": runtime_min,
            "token_cost_usd": r["cost_usd"],
            "input_tokens": "",  # not re-derivable; kept blank like unmeasured rows
            "output_tokens": r["turns"],
            "stage_count": stage_count,
            **{s: r[s] for s in STAGES},
        })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUT_COLUMNS)
        writer.writeheader()
        writer.writerows(out)

    from collections import Counter
    print(f"wrote {len(out)} rows -> {args.output}")
    print(f"labels: {dict(Counter(o['label'] for o in out))}")
    print(f"verdicts: {dict(Counter(o['verdict'] for o in out))}")
    print(f"refused: {sum(1 for o in out if o['refused']=='true')}")


if __name__ == "__main__":
    main()