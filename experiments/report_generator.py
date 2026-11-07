"""Scientific report generator for HyperAgent ablation study results.

Reads accumulated ``telemetry.jsonl`` and ablation JSONL files, computes
aggregate statistics, performs non-parametric significance testing, and
renders publication-ready markdown tables.

Usage::

    python -m experiments.report_generator \\
        --results experiments/results/ \\
        --output  experiments/report.md
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_ablation_jsonl(results_dir: Path) -> list[dict[str, Any]]:
    """Load all ``*_ablation.jsonl`` files from *results_dir*."""
    records: list[dict[str, Any]] = []
    for path in sorted(results_dir.glob("*_ablation.jsonl")):
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError as exc:
                        logger.warning("Parse error in %s: %s", path.name, exc)
    logger.info("Loaded %d ablation records from %s", len(records), results_dir)
    return records


def load_telemetry_jsonl(results_dir: Path) -> list[dict[str, Any]]:
    """Load all ``telemetry.jsonl`` files under *results_dir*."""
    records: list[dict[str, Any]] = []
    for path in results_dir.rglob("telemetry.jsonl"):
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError as exc:
                        logger.warning("Parse error in %s: %s", path, exc)
    return records


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

def group_by(records: list[dict], key: str) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        groups[r.get(key, "unknown")].append(r)
    return dict(groups)


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = mean(values)
    variance = sum((v - m) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


# ---------------------------------------------------------------------------
# Mann-Whitney U test (non-parametric, no scipy dependency)
# ---------------------------------------------------------------------------

def mann_whitney_u(x: list[float], y: list[float]) -> tuple[float, float]:
    """Compute the Mann-Whitney U statistic and an approximate p-value.

    Returns
    -------
    (U, p_value)

    The p-value is computed using the normal approximation (valid for n ≥ 8).
    For small samples it is only approximate; flag results with n < 8 as
    "insufficient power".
    """
    n1, n2 = len(x), len(y)
    if n1 == 0 or n2 == 0:
        return 0.0, 1.0

    # Rank all combined values
    combined = [(v, 0) for v in x] + [(v, 1) for v in y]
    combined.sort(key=lambda t: t[0])

    # Assign average ranks for ties
    ranks: list[float] = []
    i = 0
    while i < len(combined):
        j = i
        while j < len(combined) and combined[j][0] == combined[i][0]:
            j += 1
        avg_rank = (i + 1 + j) / 2  # average of 1-indexed positions
        for _ in range(j - i):
            ranks.append(avg_rank)
        i = j

    r1 = sum(ranks[k] for k in range(len(combined)) if combined[k][1] == 0)

    u1 = r1 - n1 * (n1 + 1) / 2
    u2 = n1 * n2 - u1
    u = min(u1, u2)

    # Normal approximation
    mean_u = n1 * n2 / 2
    sigma_u = math.sqrt(n1 * n2 * (n1 + n2 + 1) / 12)
    if sigma_u == 0:
        return u, 1.0

    z = (u - mean_u) / sigma_u
    # Two-tailed p-value via error function approximation
    p = 2 * (1 - _norm_cdf(abs(z)))
    return u, p


def _norm_cdf(z: float) -> float:
    """Standard normal CDF via Horner's method (Abramowitz & Stegun 26.2.17)."""
    t = 1.0 / (1.0 + 0.2316419 * abs(z))
    poly = t * (0.319381530
                + t * (-0.356563782
                       + t * (1.781477937
                              + t * (-1.821255978
                                     + t * 1.330274429))))
    p = 1.0 - (1.0 / math.sqrt(2 * math.pi)) * math.exp(-0.5 * z * z) * poly
    return p if z >= 0 else 1.0 - p


# ---------------------------------------------------------------------------
# Report sections
# ---------------------------------------------------------------------------

def section_ablation_table(records: list[dict]) -> str:
    """Build the main ablation comparison table (mean ± std across samples)."""
    by_config = group_by(records, "ablation_config")

    columns = [
        "ablation_config",
        "n_samples",
        "agg_precision",
        "agg_recall",
        "agg_f1",
        "total_cost_usd",
        "cache_savings_pct",
        "total_input_tokens",
        "total_wall_time_s",
    ]

    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join(["---"] * len(columns)) + " |"
    rows = [header, sep]

    for config_name in sorted(by_config):
        entries = by_config[config_name]
        summaries = [e.get("run_summary", {}) for e in entries if e.get("success")]

        def _extract(key: str) -> list[float]:
            return [float(s[key]) for s in summaries if key in s]

        def _fmt(vals: list[float]) -> str:
            if not vals:
                return "N/A"
            m = mean(vals)
            s = std(vals)
            return f"{m:.4f} ± {s:.4f}" if len(vals) > 1 else f"{m:.4f}"

        n = len(summaries)
        row = [
            config_name,
            str(n),
            _fmt(_extract("aggregate_precision")),
            _fmt(_extract("aggregate_recall")),
            _fmt(_extract("aggregate_f1")),
            _fmt(_extract("total_cost_usd")),
            _fmt(_extract("cache_savings_percent")),
            _fmt(_extract("total_input_tokens")),
            _fmt(_extract("total_wall_time_seconds")),
        ]
        rows.append("| " + " | ".join(row) + " |")

    return "\n".join(rows)


def section_rq1_leakage(telemetry: list[dict]) -> str:
    """RQ1: compare context leakage proxy between A3_no_isolation and FULL."""
    # Leakage proxy: tool_error_rate as a stand-in until cross-task reference
    # scoring is implemented. Replace this with actual leakage scores when
    # the adversarial evaluation is complete.
    full_records = [r for r in telemetry if r.get("ablation_config") == "FULL"]
    a3_records   = [r for r in telemetry if r.get("ablation_config") == "A3_no_isolation"]

    def tool_error_rate(records: list[dict]) -> list[float]:
        rates = []
        for r in records:
            tc = r.get("tool_calls", 0)
            te = r.get("tool_errors", 0)
            if tc > 0:
                rates.append(te / tc)
        return rates

    full_rates = tool_error_rate(full_records)
    a3_rates   = tool_error_rate(a3_records)

    u, p = mann_whitney_u(full_rates, a3_rates) if full_rates and a3_rates else (0, 1.0)
    sig = "✓ significant (p < 0.05)" if p < 0.05 else "✗ not significant"

    lines = [
        "### RQ1 — Context Isolation (A3 vs FULL)",
        "",
        "| Condition | n | Mean Tool-Error Rate | Median |",
        "| --- | --- | --- | --- |",
        f"| FULL | {len(full_rates)} | {mean(full_rates):.4f} | {median(full_rates):.4f} |",
        f"| A3_no_isolation | {len(a3_rates)} | {mean(a3_rates):.4f} | {median(a3_rates):.4f} |",
        "",
        f"Mann-Whitney U = {u:.1f}, p = {p:.4f} — {sig}",
        "",
        "> [!NOTE]",
        "> Tool-error rate is a proxy metric. Replace with cross-task reference leakage",
        "> scores once adversarial evaluation (§3.3 of research_framework.md) is complete.",
    ]
    return "\n".join(lines)


def section_rq2_cache_savings(telemetry: list[dict]) -> str:
    """RQ2: prompt caching cost savings (A4_no_cache vs FULL)."""
    full = [r for r in telemetry if r.get("ablation_config") == "FULL"]
    a4   = [r for r in telemetry if r.get("ablation_config") == "A4_no_cache"]

    def cache_savings(records: list[dict]) -> list[float]:
        savings = []
        for r in records:
            ev = r.get("evaluation", {})
            s = ev.get("cache_savings_percent", 0.0)
            if s > 0:
                savings.append(float(s))
        return savings

    full_savings = cache_savings(full)
    a4_savings   = cache_savings(a4)

    lines = [
        "### RQ2 — Prompt Caching Cost Savings (FULL vs A4_no_cache)",
        "",
        "| Condition | n stages | Mean Cache Savings % | Std |",
        "| --- | --- | --- | --- |",
        f"| FULL (cache on)   | {len(full_savings)} | {mean(full_savings):.2f}% | {std(full_savings):.2f}% |",
        f"| A4_no_cache       | {len(a4_savings)}   | {mean(a4_savings):.2f}%  | {std(a4_savings):.2f}%  |",
        "",
        "**Interpretation**: Cache savings % for FULL condition measures what fraction of",
        "the effective cost was eliminated by Anthropic prompt caching vs the uncached rate.",
        "A4 condition should show ~0% savings by construction (cache disabled).",
    ]
    return "\n".join(lines)


def section_token_efficiency(telemetry: list[dict]) -> str:
    """Token efficiency across ablation conditions."""
    by_config = group_by(telemetry, "ablation_config")

    lines = [
        "### Token Efficiency (TP / 1 000 input tokens)",
        "",
        "| Ablation | n stages | Mean TE | Std TE |",
        "| --- | --- | --- | --- |",
    ]
    for config in sorted(by_config):
        records = by_config[config]
        efficiencies = [
            float(r["evaluation"]["token_efficiency"])
            for r in records
            if r.get("evaluation", {}).get("token_efficiency") is not None
        ]
        if efficiencies:
            lines.append(
                f"| {config} | {len(efficiencies)} "
                f"| {mean(efficiencies):.4f} "
                f"| {std(efficiencies):.4f} |"
            )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Full report
# ---------------------------------------------------------------------------

def generate_report(
    results_dir: Path,
    output_path: Path,
) -> str:
    """Generate the full markdown report and write it to *output_path*.

    Returns the report text.
    """
    ablation_records = load_ablation_jsonl(results_dir)
    telemetry_records = load_telemetry_jsonl(results_dir)

    sections: list[str] = [
        "# HyperAgent Ablation Study — Scientific Report",
        "",
        f"> Generated from `{results_dir}` — {len(ablation_records)} ablation runs, "
        f"{len(telemetry_records)} stage telemetry records.",
        "",
        "---",
        "",
        "## 1. Ablation Comparison Table",
        "",
        "Values are **mean ± std** across all samples in the corpus.",
        "",
        section_ablation_table(ablation_records),
        "",
        "---",
        "",
        "## 2. Research Question Analyses",
        "",
        section_rq1_leakage(telemetry_records),
        "",
        section_rq2_cache_savings(telemetry_records),
        "",
        "---",
        "",
        "## 3. Token Efficiency",
        "",
        section_token_efficiency(telemetry_records),
        "",
        "---",
        "",
        "## 4. Interpretation Guide",
        "",
        "| Ablation | Expected finding if hypothesis holds |",
        "| --- | --- |",
        "| A1 −Static | F1 ↓ for PE-structure IOCs; Dynamic alone misses import-based indicators |",
        "| A2 −Dynamic | Recall ↓ on process/network/registry behaviors |",
        "| A3 −Isolation | Cross-task leakage ↑ (tool-error proxy increases) |",
        "| A4 −Cache | cache_savings_percent ≈ 0; effective_cost_usd ↑ by predicted model |",
        "| A5 −Guard | Injection success ↑ in adversarial samples |",
        "| A6 −Checkpoint | Accuracy ↓ for long-context stages (degradation curve) |",
        "",
    ]

    report = "\n".join(sections)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    logger.info("Report written to %s", output_path)
    return report


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate HyperAgent ablation study report"
    )
    parser.add_argument(
        "--results",
        type=Path,
        default=Path("experiments/results"),
        help="Directory containing *_ablation.jsonl and telemetry.jsonl files",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("experiments/report.md"),
        help="Output path for the markdown report",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    report = generate_report(results_dir=args.results, output_path=args.output)
    print(report[:2000])  # Preview first 2000 chars in terminal
    return 0


if __name__ == "__main__":
    sys.exit(_main())
