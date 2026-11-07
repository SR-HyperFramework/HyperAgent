"""Batch evaluation pipeline for HyperAgent v4.

Runs the full analysis pipeline across a labeled corpus (malware + benign)
and reports detection quality (precision / recall / F1 / FPR) plus token
cost, with an optional temporal split to check for concept drift.

Two distinct false-positive-rate concepts exist in this codebase; keep them
apart. The one computed here is ``pipeline_fpr``: the fraction of
*benign-labeled samples* the pipeline verdicts as malicious. It is unrelated
to ``hyperagent.tools.rule_verifier.RuleVerifier``'s FPR, which measures how
often a *generated detection rule* fires on a benign corpus.

Ground truth comes from which directory a sample was found in
(``malware_dir`` vs ``benign_dir``), not from anything the pipeline emits.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from hyperagent import pipeline_state
from hyperagent.config import HyperAgentConfig, load_config
from hyperagent.engine.launcher import _sha256_of, run_pipeline_with_config
from hyperagent.telemetry.metrics import RunMetrics

from .ablation_runner import AblationConfig

logger = logging.getLogger(__name__)

LABEL_MALWARE = "malware"
LABEL_BENIGN = "benign"

#: stage whose JSON artifact carries the pipeline's final verdict.
VERDICT_STAGE_ID = "09-summary"

#: Verdict strings that count as "the pipeline called this malicious".
MALICIOUS_VERDICTS = frozenset({"malicious", "malware", "suspicious", "positive", "true"})

#: How many samples per class ``--quick-test`` keeps.
QUICK_TEST_PER_CLASS = 5


@dataclass
class SampleMeta:
    """One corpus sample plus its ground-truth label."""

    path: Path
    label: str  # "malware" | "benign"
    first_seen: date | None = None


@dataclass
class EvaluationReport:
    """Result of evaluating a whole corpus."""

    per_sample: list[dict] = field(default_factory=list)
    aggregate: dict = field(default_factory=dict)
    temporal_drift: dict | None = None

    def to_dict(self) -> dict:
        return {
            "per_sample": self.per_sample,
            "aggregate": self.aggregate,
            "temporal_drift": self.temporal_drift,
        }


# ---------------------------------------------------------------------------
# Corpus discovery
# ---------------------------------------------------------------------------

def _parse_first_seen(value: Any) -> date | None:
    """Parse a first-seen date, returning None for anything unusable."""
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            logger.warning("Unparseable first_seen value %r; treating as missing", value)
            return None


def _load_first_seen_index(directory: Path) -> dict[str, date | None]:
    """Read an optional ``first_seen.json`` sidecar mapping filename -> date.

    A corpus directory may ship ``first_seen.json`` like::

        {"a.exe": "2025-01-15", "b.exe": "2025-09-02"}

    Samples absent from it (or with an unparseable date) get ``first_seen=None``
    and are reported by :meth:`BatchEvaluator.temporal_split`.
    """
    index_path = directory / "first_seen.json"
    if not index_path.exists():
        return {}
    try:
        raw = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not read %s; treating all first_seen as missing", index_path)
        return {}
    if not isinstance(raw, dict):
        logger.warning("%s is not a JSON object; ignoring", index_path)
        return {}
    return {str(name): _parse_first_seen(value) for name, value in raw.items()}


def discover_samples(directory: Path, label: str) -> list[SampleMeta]:
    """Collect every file in *directory* as a labeled sample.

    Sidecar metadata (``first_seen.json``) is not itself a sample.
    """
    directory = Path(directory)
    if not directory.is_dir():
        logger.warning("Corpus directory does not exist: %s", directory)
        return []

    first_seen_index = _load_first_seen_index(directory)
    samples = [
        SampleMeta(
            path=entry,
            label=label,
            first_seen=first_seen_index.get(entry.name),
        )
        for entry in sorted(directory.iterdir())
        if entry.is_file() and entry.name != "first_seen.json"
    ]
    logger.info("Discovered %d %s sample(s) in %s", len(samples), label, directory)
    return samples


# ---------------------------------------------------------------------------
# Verdict extraction
# ---------------------------------------------------------------------------

def _deep_find_verdict(payload: Any, depth: int = 0) -> str | None:
    """Search a decoded JSON payload for a verdict-ish string field."""
    if depth > 6:
        return None
    if isinstance(payload, dict):
        for key in ("verdict", "classification", "final_verdict", "assessment"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().lower()
        for value in payload.values():
            found = _deep_find_verdict(value, depth + 1)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _deep_find_verdict(item, depth + 1)
            if found:
                return found
    return None


def read_verdict(report_dir: Path) -> str | None:
    """Read the pipeline's verdict from ``<report_dir>/09-summary.json``.

    Returns the lowercased verdict string, or ``None`` if the summary stage
    never produced a readable artifact (the sample is then counted as an
    error, not as a benign verdict).
    """
    summary_path = Path(
        pipeline_state.default_output_path(report_dir, VERDICT_STAGE_ID)
        or (report_dir / f"{VERDICT_STAGE_ID}.json")
    )
    if not summary_path.exists():
        logger.warning("No %s artifact at %s", VERDICT_STAGE_ID, summary_path)
        return None
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not parse %s", summary_path, exc_info=True)
        return None
    return _deep_find_verdict(payload)


def verdict_is_malicious(verdict: str | None) -> bool | None:
    """Map a raw verdict string to a boolean, or ``None`` when unavailable."""
    if verdict is None:
        return None
    return verdict.strip().lower() in MALICIOUS_VERDICTS


# ---------------------------------------------------------------------------
# Metric math
# ---------------------------------------------------------------------------

def _safe_ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def compute_aggregate(rows: list[dict]) -> dict:
    """Confusion-matrix metrics over per-sample rows.

    Rows whose verdict is missing (``predicted_malicious is None``) are counted
    as ``errors`` and excluded from the confusion matrix rather than silently
    scored as benign.
    """
    scored = [row for row in rows if row.get("predicted_malicious") is not None]
    errors = len(rows) - len(scored)
    refusals = sum(1 for row in rows if row.get("refused"))
    refused_malware = sum(
        1 for row in rows if row.get("refused") and row.get("label") == LABEL_MALWARE
    )

    tp = sum(1 for r in scored if r["label"] == LABEL_MALWARE and r["predicted_malicious"])
    fn = sum(1 for r in scored if r["label"] == LABEL_MALWARE and not r["predicted_malicious"])
    fp = sum(1 for r in scored if r["label"] == LABEL_BENIGN and r["predicted_malicious"])
    tn = sum(1 for r in scored if r["label"] == LABEL_BENIGN and not r["predicted_malicious"])

    precision = _safe_ratio(tp, tp + fp)
    recall = _safe_ratio(tp, tp + fn)
    f1 = _safe_ratio(2 * precision * recall, precision + recall) if (precision + recall) else 0.0

    return {
        "sample_count": len(rows),
        "scored_count": len(scored),
        "error_count": errors,
        # Refusals are a subset of error_count, broken out because they are the
        # one failure mode that correlates with the label: read the two numbers
        # together before trusting recall. A refusal rate that is much higher on
        # malware than on benign means the scored subset is not a random sample
        # of the corpus, and every metric below is conditioned on surviving it.
        "refusal_count": refusals,
        "refused_malware_count": refused_malware,
        "refusal_rate": _safe_ratio(refusals, len(rows)),
        "true_positives": tp,
        "false_positives": fp,
        "true_negatives": tn,
        "false_negatives": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        # Pipeline-level FPR: benign samples the pipeline called malicious.
        # Distinct from RuleVerifier's rule-level FPR (Phase 4).
        "pipeline_fpr": _safe_ratio(fp, fp + tn),
        "accuracy": _safe_ratio(tp + tn, len(scored)),
        "total_token_cost_usd": sum(float(r.get("token_cost_usd") or 0.0) for r in rows),
        "total_input_tokens": sum(int(r.get("input_tokens") or 0) for r in rows),
        "total_output_tokens": sum(int(r.get("output_tokens") or 0) for r in rows),
        "total_cache_creation_input_tokens": sum(
            int(r.get("cache_creation_input_tokens") or 0) for r in rows
        ),
        "total_cache_read_input_tokens": sum(
            int(r.get("cache_read_input_tokens") or 0) for r in rows
        ),
        # Fraction of cacheable input tokens actually served from cache across the
        # whole batch. Near 0 despite cache_control being sent means the request
        # path (e.g. a proxy/gateway in front of the real provider) is dropping
        # the cache breakpoints rather than the pipeline failing to set them.
        "cache_hit_rate": _safe_ratio(
            sum(int(r.get("cache_read_input_tokens") or 0) for r in rows),
            sum(int(r.get("cache_read_input_tokens") or 0) for r in rows)
            + sum(int(r.get("cache_creation_input_tokens") or 0) for r in rows),
        ),
    }


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

RunFn = Callable[..., Awaitable[RunMetrics]]


class BatchEvaluator:
    """Runs the pipeline over a labeled corpus and scores its verdicts."""

    def __init__(
        self,
        config: HyperAgentConfig,
        run_fn: RunFn | None = None,
    ) -> None:
        self.config = config
        self._run_fn = run_fn or run_pipeline_with_config

    # -- temporal split ---------------------------------------------------

    def temporal_split(
        self, samples: list[SampleMeta], split_date: date
    ) -> tuple[list[SampleMeta], list[SampleMeta]]:
        """Split by first-seen date.

        Samples missing ``first_seen`` go in neither half — a warning naming
        each dropped sample is logged so they are never silently excluded.
        """
        before: list[SampleMeta] = []
        after: list[SampleMeta] = []
        dropped: list[SampleMeta] = []

        for sample in samples:
            if sample.first_seen is None:
                dropped.append(sample)
            elif sample.first_seen < split_date:
                before.append(sample)
            else:
                after.append(sample)

        if dropped:
            logger.warning(
                "temporal_split dropped %d sample(s) with no first_seen date "
                "(in neither half): %s",
                len(dropped),
                ", ".join(str(sample.path) for sample in dropped),
            )
        return before, after

    # -- per-sample run ---------------------------------------------------

    async def _evaluate_sample(
        self,
        sample: SampleMeta,
        ablation_config: AblationConfig | None,
    ) -> dict:
        sample_hash = _sha256_of(sample.path)
        row: dict[str, Any] = {
            "sample_path": str(sample.path),
            "sample_sha256": sample_hash,
            "label": sample.label,
            "first_seen": sample.first_seen.isoformat() if sample.first_seen else "",
            "verdict": "",
            "predicted_malicious": None,
            "input_tokens": 0,
            "output_tokens": 0,
            "token_cost_usd": 0.0,
            "wall_time_seconds": 0.0,
            "stage_count": 0,
            "refused": False,
            "error": "",
        }

        try:
            metrics = await self._run_fn(
                sample.path,
                self.config,
                ablation_config,
                run_id=sample_hash,
            )
        except Exception as exc:  # one bad sample must not abort the corpus
            logger.exception("Pipeline failed for %s", sample.path)
            row["error"] = f"{type(exc).__name__}: {exc}"
            return row

        row.update(
            {
                "input_tokens": metrics.total_input_tokens,
                "output_tokens": metrics.total_output_tokens,
                "token_cost_usd": metrics.total_effective_cost_usd,
                "wall_time_seconds": metrics.total_wall_time_seconds,
                "stage_count": len(metrics.stages),
            }
        )

        # A refusal is not an exception: the launcher records it and returns
        # normally, so it arrives here as a run that simply produced no verdict.
        # Name it explicitly — "the model declined" and "the pipeline ran and
        # found nothing" must not share the same empty cell.
        refused_stages = getattr(metrics, "refused_stages", [])
        if refused_stages:
            row["refused"] = True
            row["error"] = f"model refused at: {', '.join(refused_stages)}"

        report_dir = self._report_dir_for(sample.path, sample_hash)
        verdict = read_verdict(report_dir)
        row["verdict"] = verdict or ""
        row["predicted_malicious"] = verdict_is_malicious(verdict)
        if verdict is None:
            row["error"] = row["error"] or "no verdict artifact"
        return row

    def _report_dir_for(self, sample_path: Path, sample_hash: str) -> Path:
        """Mirror the launcher's report-dir layout: <reports_root>/<sha256>."""
        root = getattr(self.config, "reports_root", None) or (Path(sample_path).parent / "reports")
        return Path(root) / sample_hash

    # -- corpus -----------------------------------------------------------

    async def evaluate_corpus(
        self,
        malware_dir: Path,
        benign_dir: Path,
        output_dir: Path,
        ablation_config: AblationConfig | None = None,
        quick_test: bool = False,
        split_date: date | None = None,
    ) -> EvaluationReport:
        """Run the pipeline over both corpora and write CSV + JSONL results."""
        malware = discover_samples(Path(malware_dir), LABEL_MALWARE)
        benign = discover_samples(Path(benign_dir), LABEL_BENIGN)

        if quick_test:
            if len(malware) > QUICK_TEST_PER_CLASS or len(benign) > QUICK_TEST_PER_CLASS:
                logger.info(
                    "--quick-test: capping corpus at %d sample(s) per class "
                    "(%d malware, %d benign available)",
                    QUICK_TEST_PER_CLASS,
                    len(malware),
                    len(benign),
                )
            malware = malware[:QUICK_TEST_PER_CLASS]
            benign = benign[:QUICK_TEST_PER_CLASS]

        samples = malware + benign
        if not samples:
            logger.warning("No samples found in %s or %s", malware_dir, benign_dir)

        rows: list[dict] = []
        for index, sample in enumerate(samples, start=1):
            logger.info("[%d/%d] Evaluating %s (%s)", index, len(samples), sample.path, sample.label)
            rows.append(await self._evaluate_sample(sample, ablation_config))

        report = EvaluationReport(per_sample=rows, aggregate=compute_aggregate(rows))

        if split_date is not None:
            report.temporal_drift = self._temporal_drift(samples, rows, split_date)

        self._write_outputs(report, Path(output_dir))
        return report

    def _temporal_drift(
        self, samples: list[SampleMeta], rows: list[dict], split_date: date
    ) -> dict:
        before, after = self.temporal_split(samples, split_date)
        before_paths = {str(sample.path) for sample in before}
        after_paths = {str(sample.path) for sample in after}

        before_metrics = compute_aggregate([r for r in rows if r["sample_path"] in before_paths])
        after_metrics = compute_aggregate([r for r in rows if r["sample_path"] in after_paths])

        return {
            "split_date": split_date.isoformat(),
            "before": before_metrics,
            "after": after_metrics,
            "excluded_no_first_seen": [
                str(sample.path) for sample in samples if sample.first_seen is None
            ],
            "f1_delta": after_metrics["f1"] - before_metrics["f1"],
        }

    # -- output -----------------------------------------------------------

    def _write_outputs(self, report: EvaluationReport, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)

        csv_path = output_dir / "batch_eval_per_sample.csv"
        fieldnames = [
            "sample_path",
            "sample_sha256",
            "label",
            "first_seen",
            "verdict",
            "predicted_malicious",
            "input_tokens",
            "output_tokens",
            "token_cost_usd",
            "wall_time_seconds",
            "stage_count",
            "refused",
            "error",
        ]
        with csv_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(report.per_sample)

        jsonl_path = output_dir / "batch_eval.jsonl"
        with jsonl_path.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(report.to_dict(), ensure_ascii=False, default=str) + "\n")

        logger.info("Wrote %s and %s", csv_path, jsonl_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Batch-evaluate HyperAgent over a labeled malware/benign corpus"
    )
    parser.add_argument("--malware-dir", type=Path, required=True, help="Directory of malware-labeled samples")
    parser.add_argument("--benign-dir", type=Path, required=True, help="Directory of benign-labeled samples")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("experiments/results"),
        help="Where to write batch_eval_per_sample.csv and batch_eval.jsonl",
    )
    parser.add_argument("--config", type=Path, default=None, help="Path to a HyperAgent config file")
    parser.add_argument(
        "--quick-test",
        action="store_true",
        help=f"Cap the corpus at {QUICK_TEST_PER_CLASS} sample(s) per class",
    )
    parser.add_argument(
        "--split-date",
        type=date.fromisoformat,
        default=None,
        help="ISO date (YYYY-MM-DD) for the temporal drift split",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    config = load_config(args.config)
    evaluator = BatchEvaluator(config)
    report = asyncio.run(
        evaluator.evaluate_corpus(
            malware_dir=args.malware_dir,
            benign_dir=args.benign_dir,
            output_dir=args.output_dir,
            quick_test=args.quick_test,
            split_date=args.split_date,
        )
    )
    print(json.dumps(report.aggregate, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
