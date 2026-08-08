"""Scientific metrics collection for HyperAgent research evaluation.

This module defines the data models and collection infrastructure for:
- Token efficiency (input/output/cache usage per stage and per run)
- Detection quality (Precision, Recall, F1, FPR) against a ground-truth corpus
- Cost accounting (effective USD cost with Anthropic prompt caching applied)
- Ablation study tracking (which configuration produced each measurement)

All metrics are persisted as JSONL to ``reports/<sha256>/telemetry.jsonl`` so
that offline analysis tools can process them without re-running the pipeline.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Anthropic model pricing table (USD per token, as of 2025-08)
# Keys match the model identifiers returned by the Messages API.
# ---------------------------------------------------------------------------

_PRICING: dict[str, dict[str, float]] = {
    # claude-opus-5 / claude-opus-4
    "claude-opus": {
        "input":       15.00 / 1_000_000,
        "output":      75.00 / 1_000_000,
        "cache_write":  3.75 / 1_000_000,  # 25 % surcharge vs input
        "cache_read":   1.50 / 1_000_000,  # 90 % discount vs input
    },
    # claude-sonnet-4-5 / claude-sonnet-4
    "claude-sonnet": {
        "input":        3.00 / 1_000_000,
        "output":      15.00 / 1_000_000,
        "cache_write":  3.75 / 1_000_000,
        "cache_read":   0.30 / 1_000_000,
    },
    # claude-haiku-3-5 / claude-haiku-3
    "claude-haiku": {
        "input":        0.80 / 1_000_000,
        "output":       4.00 / 1_000_000,
        "cache_write":  1.00 / 1_000_000,
        "cache_read":   0.08 / 1_000_000,
    },
}

_PRICING_FALLBACK = _PRICING["claude-sonnet"]


def _price_table(model_id: str) -> dict[str, float]:
    """Return the pricing table for *model_id*, falling back to Sonnet."""
    for key, table in _PRICING.items():
        if key in model_id.lower():
            return table
    logger.warning("No pricing table for model %r — using claude-sonnet rates", model_id)
    return _PRICING_FALLBACK


# ---------------------------------------------------------------------------
# Stage-level metrics (one record per pipeline stage per run)
# ---------------------------------------------------------------------------

@dataclass
class StageMetrics:
    """Telemetry for a single pipeline stage execution.

    Fields are populated incrementally during ``AgentLoop.run()`` and
    frozen when the stage completes or checkpoints.
    """

    run_id: str
    """UUID4 that groups all stages belonging to one pipeline invocation."""

    sample_sha256: str
    """SHA-256 of the analyzed sample — links to the report directory."""

    stage_id: str
    """E.g. ``"05-dynamic"``."""

    ablation_config: str = "FULL"
    """Name of the active ablation condition (``"FULL"``, ``"A1_no_static"``, …)."""

    provider: str = ""
    """Model identifier as returned by the API (e.g. ``"claude-opus-5-20260101"``)."""

    # -- timing ---------------------------------------------------------------

    start_time: float = field(default_factory=time.monotonic)
    end_time: float = 0.0

    @property
    def wall_time_seconds(self) -> float:
        return (self.end_time - self.start_time) if self.end_time > 0 else 0.0

    # -- token counters -------------------------------------------------------

    total_input_tokens: int = 0
    """Cumulative input tokens charged across all turns in this stage."""

    total_output_tokens: int = 0
    """Cumulative output tokens charged across all turns in this stage."""

    cache_creation_input_tokens: int = 0
    """Tokens written to Anthropic's prompt cache (billed at 1.25× input rate)."""

    cache_read_input_tokens: int = 0
    """Tokens served from Anthropic's prompt cache (billed at 0.10× input rate)."""

    # -- execution counters ---------------------------------------------------

    turns: int = 0
    """Number of LLM completion calls made."""

    tool_calls: int = 0
    """Total tool invocations requested by the LLM."""

    tool_errors: int = 0
    """Tool invocations that returned ``is_error=True``."""

    checkpoint_triggered: bool = False
    """Whether this stage raised a ``CheckpointReached`` exception."""

    stage_status: str = "running"
    """Final status: ``"completed"``, ``"checkpointed"``, ``"failed"``."""

    # -- detection quality (populated post-evaluation) ------------------------

    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0

    # -- derived properties ---------------------------------------------------

    @property
    def precision(self) -> float:
        """TP / (TP + FP) — of all predicted findings, how many are correct?"""
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom > 0 else 0.0

    @property
    def recall(self) -> float:
        """TP / (TP + FN) — of all real indicators, how many were found?"""
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom > 0 else 0.0

    @property
    def f1_score(self) -> float:
        """Harmonic mean of Precision and Recall."""
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0

    @property
    def token_efficiency(self) -> float:
        """True positives per 1 000 input tokens consumed.

        Higher is better — measures how many correct findings the pipeline
        produces per unit of token spend.
        """
        if self.total_input_tokens <= 0:
            return 0.0
        return self.true_positives / self.total_input_tokens * 1_000

    @property
    def cache_hit_rate(self) -> float:
        """Fraction of cacheable input tokens served from cache (0–1).

        A value of 0 either means caching is disabled or only the first
        (write) turn has run.  A value close to 1 is ideal for long stages.
        """
        total_cache = self.cache_creation_input_tokens + self.cache_read_input_tokens
        return self.cache_read_input_tokens / total_cache if total_cache > 0 else 0.0

    @property
    def effective_cost_usd(self) -> float:
        """Estimated USD cost for this stage with prompt caching applied."""
        p = _price_table(self.provider)
        plain_input = max(
            0,
            self.total_input_tokens
            - self.cache_creation_input_tokens
            - self.cache_read_input_tokens,
        )
        return (
            plain_input                        * p["input"]
            + self.cache_creation_input_tokens * p["cache_write"]
            + self.cache_read_input_tokens     * p["cache_read"]
            + self.total_output_tokens         * p["output"]
        )

    @property
    def effective_cost_no_cache_usd(self) -> float:
        """Estimated USD cost *without* caching (all tokens at base input rate).

        Used to compute ``cache_savings_percent`` for RQ2.
        """
        p = _price_table(self.provider)
        return (
            self.total_input_tokens * p["input"]
            + self.total_output_tokens * p["output"]
        )

    @property
    def cache_savings_percent(self) -> float:
        """Percentage cost reduction due to prompt caching.

        ``(cost_no_cache - cost_cached) / cost_no_cache × 100``
        Returns 0.0 if no caching occurred.
        """
        no_cache = self.effective_cost_no_cache_usd
        if no_cache <= 0:
            return 0.0
        return (no_cache - self.effective_cost_usd) / no_cache * 100.0

    # -- serialization --------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a flat dict suitable for JSONL output."""
        d: dict[str, Any] = {
            "run_id":                        self.run_id,
            "timestamp":                     time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "sample_sha256":                 self.sample_sha256,
            "stage_id":                      self.stage_id,
            "ablation_config":               self.ablation_config,
            "provider":                      self.provider,
            "turns":                         self.turns,
            "total_input_tokens":            self.total_input_tokens,
            "total_output_tokens":           self.total_output_tokens,
            "cache_creation_input_tokens":   self.cache_creation_input_tokens,
            "cache_read_input_tokens":       self.cache_read_input_tokens,
            "tool_calls":                    self.tool_calls,
            "tool_errors":                   self.tool_errors,
            "checkpoint_triggered":          self.checkpoint_triggered,
            "wall_time_seconds":             round(self.wall_time_seconds, 3),
            "stage_status":                  self.stage_status,
            "evaluation": {
                "true_positives":        self.true_positives,
                "false_positives":       self.false_positives,
                "false_negatives":       self.false_negatives,
                "precision":             round(self.precision, 4),
                "recall":                round(self.recall, 4),
                "f1_score":              round(self.f1_score, 4),
                "token_efficiency":      round(self.token_efficiency, 4),
                "cache_hit_rate":        round(self.cache_hit_rate, 4),
                "effective_cost_usd":    round(self.effective_cost_usd, 6),
                "cache_savings_percent": round(self.cache_savings_percent, 2),
            },
        }
        return d

    def to_jsonl(self) -> str:
        """Serialize to a single JSON line (no trailing newline)."""
        return json.dumps(self.to_dict(), ensure_ascii=False)


# ---------------------------------------------------------------------------
# Run-level aggregate (one record summarising all stages for one invocation)
# ---------------------------------------------------------------------------

@dataclass
class RunMetrics:
    """Aggregate metrics for a complete pipeline run (all 9 stages).

    Built by ``MetricsCollector.finalize_run()`` after all stages complete.
    """

    run_id: str
    sample_sha256: str
    ablation_config: str
    stages: list[StageMetrics] = field(default_factory=list)

    @property
    def total_input_tokens(self) -> int:
        return sum(s.total_input_tokens for s in self.stages)

    @property
    def total_output_tokens(self) -> int:
        return sum(s.total_output_tokens for s in self.stages)

    @property
    def total_cache_creation_tokens(self) -> int:
        return sum(s.cache_creation_input_tokens for s in self.stages)

    @property
    def total_cache_read_tokens(self) -> int:
        return sum(s.cache_read_input_tokens for s in self.stages)

    @property
    def total_effective_cost_usd(self) -> float:
        return sum(s.effective_cost_usd for s in self.stages)

    @property
    def total_wall_time_seconds(self) -> float:
        return sum(s.wall_time_seconds for s in self.stages)

    @property
    def aggregate_precision(self) -> float:
        tp = sum(s.true_positives for s in self.stages)
        fp = sum(s.false_positives for s in self.stages)
        return tp / (tp + fp) if (tp + fp) > 0 else 0.0

    @property
    def aggregate_recall(self) -> float:
        tp = sum(s.true_positives for s in self.stages)
        fn = sum(s.false_negatives for s in self.stages)
        return tp / (tp + fn) if (tp + fn) > 0 else 0.0

    @property
    def aggregate_f1(self) -> float:
        p, r = self.aggregate_precision, self.aggregate_recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0

    @property
    def overall_cache_savings_percent(self) -> float:
        no_cache = sum(s.effective_cost_no_cache_usd for s in self.stages)
        cached = sum(s.effective_cost_usd for s in self.stages)
        if no_cache <= 0:
            return 0.0
        return (no_cache - cached) / no_cache * 100.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id":                    self.run_id,
            "sample_sha256":             self.sample_sha256,
            "ablation_config":           self.ablation_config,
            "total_input_tokens":        self.total_input_tokens,
            "total_output_tokens":       self.total_output_tokens,
            "total_cache_creation":      self.total_cache_creation_tokens,
            "total_cache_read":          self.total_cache_read_tokens,
            "total_cost_usd":            round(self.total_effective_cost_usd, 6),
            "cache_savings_percent":     round(self.overall_cache_savings_percent, 2),
            "total_wall_time_seconds":   round(self.total_wall_time_seconds, 3),
            "aggregate_precision":       round(self.aggregate_precision, 4),
            "aggregate_recall":          round(self.aggregate_recall, 4),
            "aggregate_f1":              round(self.aggregate_f1, 4),
            "stage_count":               len(self.stages),
        }


# ---------------------------------------------------------------------------
# MetricsCollector — thread-safe accumulator + JSONL writer
# ---------------------------------------------------------------------------

class MetricsCollector:
    """Accumulates stage metrics and persists them to a JSONL file.

    One collector is created per pipeline run.  The ``AgentLoop`` calls
    :meth:`record_turn` after every LLM completion, and the launcher calls
    :meth:`finalize_stage` after each stage finishes.

    Thread-safe: the JSONL file is written under a lock so that concurrent
    FastAPI jobs never corrupt each other's telemetry.

    Usage::

        collector = MetricsCollector(
            run_id="abc123",
            sample_sha256="deadbeef...",
            output_path=report_dir / "telemetry.jsonl",
            ablation_config="FULL",
        )

        # Inside AgentLoop:
        collector.record_turn(stage_id, result)

        # After stage completes:
        collector.finalize_stage(stage_id, status="completed")

        # After all stages complete:
        run_metrics = collector.finalize_run()
    """

    def __init__(
        self,
        run_id: str,
        sample_sha256: str,
        output_path: Path,
        ablation_config: str = "FULL",
    ) -> None:
        self._run_id = run_id
        self._sample_sha256 = sample_sha256
        self._output_path = output_path
        self._ablation_config = ablation_config
        self._lock = threading.Lock()
        self._stages: dict[str, StageMetrics] = {}

    # -- Stage lifecycle ------------------------------------------------------

    def start_stage(self, stage_id: str, provider: str = "") -> StageMetrics:
        """Create and register a new ``StageMetrics`` for *stage_id*."""
        sm = StageMetrics(
            run_id=self._run_id,
            sample_sha256=self._sample_sha256,
            stage_id=stage_id,
            ablation_config=self._ablation_config,
            provider=provider,
            start_time=time.monotonic(),
        )
        with self._lock:
            self._stages[stage_id] = sm
        return sm

    def get_stage(self, stage_id: str) -> StageMetrics | None:
        """Return the active ``StageMetrics`` for *stage_id*, or ``None``."""
        return self._stages.get(stage_id)

    # -- Turn-level recording -------------------------------------------------

    def record_turn(
        self,
        stage_id: str,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
        tool_calls: int = 0,
        tool_errors: int = 0,
        provider: str = "",
    ) -> None:
        """Accumulate token counts from one LLM completion turn.

        Called by ``AgentLoop`` after every ``provider.complete()`` call.
        """
        sm = self._stages.get(stage_id)
        if sm is None:
            sm = self.start_stage(stage_id, provider=provider)

        with self._lock:
            sm.turns += 1
            sm.total_input_tokens += input_tokens
            sm.total_output_tokens += output_tokens
            sm.cache_creation_input_tokens += cache_creation_input_tokens
            sm.cache_read_input_tokens += cache_read_input_tokens
            sm.tool_calls += tool_calls
            sm.tool_errors += tool_errors
            if provider:
                sm.provider = provider

    def record_checkpoint(self, stage_id: str) -> None:
        """Mark that a context checkpoint was triggered for this stage."""
        sm = self._stages.get(stage_id)
        if sm is not None:
            sm.checkpoint_triggered = True

    # -- Stage finalization ---------------------------------------------------

    def finalize_stage(
        self,
        stage_id: str,
        *,
        status: str,
        true_positives: int = 0,
        false_positives: int = 0,
        false_negatives: int = 0,
    ) -> StageMetrics:
        """Mark a stage as finished and flush its record to JSONL.

        Parameters
        ----------
        stage_id:
            The stage being finalized (e.g. ``"05-dynamic"``).
        status:
            ``"completed"``, ``"checkpointed"``, or ``"failed"``.
        true_positives, false_positives, false_negatives:
            Detection quality counters, populated when a ground-truth record
            is available for this sample.  Pass 0 for real-time operation
            (metrics can be back-filled offline via ``patch_evaluation()``).
        """
        sm = self._stages.get(stage_id)
        if sm is None:
            logger.warning("finalize_stage(%s): no active StageMetrics — creating empty", stage_id)
            sm = self.start_stage(stage_id)

        with self._lock:
            sm.end_time = time.monotonic()
            sm.stage_status = status
            sm.true_positives = true_positives
            sm.false_positives = false_positives
            sm.false_negatives = false_negatives

        self._append_jsonl(sm.to_jsonl())
        logger.debug("Telemetry flushed for stage %s (%s)", stage_id, status)
        return sm

    def patch_evaluation(
        self,
        stage_id: str,
        *,
        true_positives: int,
        false_positives: int,
        false_negatives: int,
    ) -> None:
        """Back-fill detection quality counters after offline evaluation.

        Writes an updated record to the JSONL file (the original entry is
        not deleted — the last entry for a stage_id wins during analysis).
        """
        sm = self._stages.get(stage_id)
        if sm is None:
            logger.warning("patch_evaluation(%s): stage not found", stage_id)
            return
        with self._lock:
            sm.true_positives = true_positives
            sm.false_positives = false_positives
            sm.false_negatives = false_negatives
        self._append_jsonl(sm.to_jsonl())

    # -- Run finalization ------------------------------------------------------

    def finalize_run(self) -> RunMetrics:
        """Build and return aggregate ``RunMetrics`` for the entire pipeline."""
        return RunMetrics(
            run_id=self._run_id,
            sample_sha256=self._sample_sha256,
            ablation_config=self._ablation_config,
            stages=list(self._stages.values()),
        )

    # -- I/O ------------------------------------------------------------------

    def _append_jsonl(self, line: str) -> None:
        """Append *line* + newline to the JSONL output file (thread-safe)."""
        self._output_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self._output_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
