"""Ablation study runner for HyperAgent scientific evaluation.

This module implements the 6-axis ablation study described in the research
framework.  Each ablation condition modifies one component of the pipeline
while holding everything else constant, allowing marginal contribution
measurement for each architectural decision.

Ablation matrix (see research_framework.md §2.2):

    =========  ========  =========  ==========  =====  =====  ==========
    Condition  Static    Dynamic    Isolation   Cache  Guard  Checkpoint
    =========  ========  =========  ==========  =====  =====  ==========
    FULL        ✓         ✓          ✓           ✓      ✓      ✓
    A1          ✗         ✓          ✓           ✓      ✓      ✓
    A2          ✓         ✗          ✓           ✓      ✓      ✓
    A3          ✓         ✓          ✗           ✓      ✓      ✓
    A4          ✓         ✓          ✓           ✗      ✓      ✓
    A5          ✓         ✓          ✓           ✓      ✗      ✓
    A6          ✓         ✓          ✓           ✓      ✓      ✗
    =========  ========  =========  ==========  =====  =====  ==========
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hyperagent.telemetry.metrics import MetricsCollector, RunMetrics

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Ablation configuration
# ---------------------------------------------------------------------------

@dataclass
class AblationConfig:
    """Specification for one ablation condition.

    Each flag mirrors a toggleable subsystem in the pipeline:

    - *skip_stages*: stage IDs to skip entirely (simulate absence of that
      analysis component, e.g. ``["02-static-pass1", "04-static-pass2"]``).
    - *isolated_subagents*: when ``False``, inject the parent message history
      into the child agent loop (ablates RQ1 isolation, condition A3).
    - *cache_enabled*: when ``False``, omit ``cache_control`` from the
      Anthropic system prompt block (ablates RQ2 caching, condition A4).
    - *injection_guard*: when ``False``, omit the INJECTION_GUARD_PROMPT
      prefix from stages that read sample content (condition A5).
    - *checkpoint_enabled*: when ``False``, disable the context threshold
      check in ``ContextTracker`` (condition A6).
    """

    name: str
    """Short identifier used in telemetry (e.g. ``"A1_no_static"``)."""

    skip_stages: list[str] = field(default_factory=list)
    """Stage IDs to skip during the pipeline run."""

    isolated_subagents: bool = True
    """If False, share parent message history with child subagents (A3)."""

    cache_enabled: bool = True
    """If False, disable Anthropic prompt caching (A4)."""

    injection_guard: bool = True
    """If False, omit the prompt-injection guard prefix (A5)."""

    checkpoint_enabled: bool = True
    """If False, disable context-window checkpointing (A6)."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name":               self.name,
            "skip_stages":        self.skip_stages,
            "isolated_subagents": self.isolated_subagents,
            "cache_enabled":      self.cache_enabled,
            "injection_guard":    self.injection_guard,
            "checkpoint_enabled": self.checkpoint_enabled,
        }


# Pre-defined standard ablation conditions
ABLATION_CONFIGS: list[AblationConfig] = [
    AblationConfig("FULL"),
    AblationConfig(
        "A1_no_static",
        skip_stages=["02-static-pass1", "04-static-pass2"],
    ),
    AblationConfig(
        "A2_no_dynamic",
        skip_stages=["05-dynamic"],
    ),
    AblationConfig(
        "A3_no_isolation",
        isolated_subagents=False,
    ),
    AblationConfig(
        "A4_no_cache",
        cache_enabled=False,
    ),
    AblationConfig(
        "A5_no_guard",
        injection_guard=False,
    ),
    AblationConfig(
        "A6_no_checkpoint",
        checkpoint_enabled=False,
    ),
]

# Quick lookup by name
ABLATION_BY_NAME: dict[str, AblationConfig] = {c.name: c for c in ABLATION_CONFIGS}


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class AblationResult:
    """Results for one ablation condition on one sample."""

    ablation_config: str
    sample_sha256: str
    run_id: str
    run_metrics: RunMetrics | None = None
    error: str | None = None
    success: bool = True

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "ablation_config": self.ablation_config,
            "sample_sha256":   self.sample_sha256,
            "run_id":          self.run_id,
            "success":         self.success,
            "error":           self.error,
        }
        if self.run_metrics is not None:
            d["run_summary"] = self.run_metrics.to_dict()
        return d


@dataclass
class AblationReport:
    """Comparative report across all ablation conditions for one sample."""

    sample_sha256: str
    results: list[AblationResult] = field(default_factory=list)

    def summary_table(self) -> list[dict[str, Any]]:
        """Return a list of dicts suitable for tabular display or CSV export."""
        rows = []
        for r in self.results:
            rm = r.run_metrics
            row: dict[str, Any] = {"ablation": r.ablation_config, "success": r.success}
            if rm is not None:
                row.update({
                    "total_input_tokens":    rm.total_input_tokens,
                    "total_output_tokens":   rm.total_output_tokens,
                    "cache_read_tokens":     rm.total_cache_read_tokens,
                    "cache_savings_pct":     round(rm.overall_cache_savings_percent, 2),
                    "aggregate_precision":   round(rm.aggregate_precision, 4),
                    "aggregate_recall":      round(rm.aggregate_recall, 4),
                    "aggregate_f1":          round(rm.aggregate_f1, 4),
                    "total_cost_usd":        round(rm.total_effective_cost_usd, 6),
                    "total_wall_time_s":     round(rm.total_wall_time_seconds, 1),
                })
            else:
                row["error"] = r.error
            rows.append(row)
        return rows

    def to_markdown(self) -> str:
        """Render the summary table as a GitHub-flavoured markdown table."""
        rows = self.summary_table()
        if not rows:
            return "_No results._"

        headers = list(rows[0].keys())
        lines: list[str] = []
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
        for row in rows:
            cells = [str(row.get(h, "")) for h in headers]
            lines.append("| " + " | ".join(cells) + " |")
        return "\n".join(lines)

    def save_jsonl(self, output_path: Path) -> None:
        """Append one JSON line per ablation result to *output_path*."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("a", encoding="utf-8") as fh:
            for r in self.results:
                fh.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")
        logger.info("Ablation report written to %s", output_path)


# ---------------------------------------------------------------------------
# AblationRunner
# ---------------------------------------------------------------------------

class AblationRunner:
    """Runs all ablation conditions for a set of samples.

    This class does **not** import pipeline internals directly — it drives them
    through a callable ``run_fn`` so that the caller can inject the appropriate
    provider/config without coupling the experiments package to the main package.

    Usage::

        from experiments.ablation_runner import AblationRunner, ABLATION_CONFIGS
        from hyperagent.engine.launcher import run_pipeline_with_config

        runner = AblationRunner(run_fn=run_pipeline_with_config)
        report = await runner.run_sample(
            sample_path=Path("samples/malware.exe"),
            configs=ABLATION_CONFIGS,
            output_dir=Path("experiments/results"),
        )
        print(report.to_markdown())
    """

    def __init__(self, run_fn: Any) -> None:
        """
        Parameters
        ----------
        run_fn:
            An async callable with signature:
            ``async (sample_path, ablation_config, run_id) -> RunMetrics``

            The launcher is responsible for translating ``AblationConfig``
            fields into actual pipeline behaviour (skip stages, disable cache,
            etc.).
        """
        self._run_fn = run_fn

    async def run_sample(
        self,
        sample_path: Path,
        configs: list[AblationConfig] | None = None,
        output_dir: Path = Path("experiments/results"),
    ) -> AblationReport:
        """Run all *configs* for a single sample and return the comparison report.

        Parameters
        ----------
        sample_path:
            Path to the malware sample to analyse.
        configs:
            Ablation conditions to run.  Defaults to ``ABLATION_CONFIGS``.
        output_dir:
            Directory where per-condition JSONL outputs are saved.
        """
        import asyncio

        if configs is None:
            configs = ABLATION_CONFIGS

        sha256 = _sha256_of(sample_path)
        report = AblationReport(sample_sha256=sha256)

        for cfg in configs:
            run_id = uuid.uuid4().hex
            logger.info(
                "Ablation [%s] on %s (run_id=%s)", cfg.name, sample_path.name, run_id
            )
            try:
                run_metrics: RunMetrics = await self._run_fn(
                    sample_path, cfg, run_id
                )
                result = AblationResult(
                    ablation_config=cfg.name,
                    sample_sha256=sha256,
                    run_id=run_id,
                    run_metrics=run_metrics,
                    success=True,
                )
            except Exception as exc:
                logger.exception("Ablation [%s] failed: %s", cfg.name, exc)
                result = AblationResult(
                    ablation_config=cfg.name,
                    sample_sha256=sha256,
                    run_id=run_id,
                    success=False,
                    error=str(exc),
                )
            report.results.append(result)

        report.save_jsonl(output_dir / f"{sha256}_ablation.jsonl")
        return report

    async def run_corpus(
        self,
        sample_paths: list[Path],
        configs: list[AblationConfig] | None = None,
        output_dir: Path = Path("experiments/results"),
    ) -> list[AblationReport]:
        """Run ablation study across multiple samples sequentially."""
        reports = []
        for i, path in enumerate(sample_paths, 1):
            logger.info("Processing sample %d/%d: %s", i, len(sample_paths), path.name)
            report = await self.run_sample(path, configs=configs, output_dir=output_dir)
            reports.append(report)
        return reports


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256_of(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
