"""NCKH study runner: baseline TP/FP/TN/FN, stage-skip ablation, LLM comparison.

Drives the pipeline described in ``README.md`` section 1 against the sample
list in ``experiments/results/sample_selection.json`` (built from the
DikeDataset corpus at ``H:\\Dataset\\files\\{m,b}``, cross-referenced against
the official ``labels/malware.csv`` / ``labels/benign.csv`` malice scores).

Four modes, each independently runnable:

- ``static-bulk``: all 30 samples, ``02-static-pass1`` only. This is the one
  pipeline stage with no VM/x64dbg dependency at all (``STAGE_TOOLS`` lists
  only ``source:ida`` + filesystem tools for it) -- it is IDA/idalib against
  the host copy of the sample. Safe to run in bulk ahead of everything else,
  including *while* another HyperAgent process holds the VM for a different
  sample, since it never calls a ``vm_*`` or ``source:x64dbg`` tool.
  ``01-prepare-env`` and ``04-static-pass2`` do NOT qualify for the same
  treatment: prepare-env's own skill also verifies dynamic-analysis readiness
  (which can revert/boot the VM and launch the sample under x64dbg in-guest),
  and static-pass2 re-analyzes ``03-unpack``'s output, so it can't run before
  unpack has produced something.
- ``baseline``: all 30 samples, one model (whatever ``~/.hyperagent/config.yaml``
  / env vars resolve to), full profile, default ``reports_root`` (next to each
  sample) -- this transparently reuses whatever stage progress already exists
  there, including runs made by other HyperAgent invocations (e.g. the
  ``02-static-pass1`` artifacts ``static-bulk`` already produced).
- ``ablation``: the 10-sample subset, same model, one isolated ``reports_root``
  per stage-skip condition in ``STAGE_SKIP_CONFIGS`` -- answers "does skipping
  stage N (or stages 1..N) change the final verdict's accuracy".
- ``llm-compare``: the 10-sample subset, one isolated ``reports_root`` per
  model in ``LLM_CONDITIONS``. The DeepSeek arm is never re-run: it is read
  straight from the default-location reports, since those samples were
  already analyzed with DeepSeek before this script existed. Stage 06-intel
  is always skipped (see ``no_intel`` in ``STAGE_SKIP_CONFIGS``, applied
  unconditionally in ``run_llm_compare``): VirusTotal's claim_checks state
  the ground-truth verdict outright, which would leak into every model's
  07-09 synthesis otherwise.

Every mode accepts ``--dry-run``, which prints the exact (sample, config)
matrix without calling the pipeline -- safe to run while another HyperAgent
process is holding the VM.

Every mode is resumable: each completed (sample, condition) pair is appended
to ``<out_dir>/progress.jsonl`` immediately, and ``results.json`` is rewritten
after every sample. Re-running the same command after a crash or a manual
stop skips whatever is already recorded instead of redoing it.
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import logging
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable

from hyperagent import pipeline_state
from hyperagent.config import HyperAgentConfig, load_config
from hyperagent.engine.launcher import _report_dir_for, run_pipeline_with_config

from .ablation_runner import AblationConfig
from .batch_eval import (
    LABEL_BENIGN,
    LABEL_MALWARE,
    compute_aggregate,
    read_verdict,
    verdict_is_malicious,
)

logger = logging.getLogger(__name__)

MANIFEST_PATH = Path("experiments/results/sample_selection.json")
# Absolute: llm-compare/ablation feed "<out_dir>/reports" into reports_root,
# which lands verbatim in each stage's prompt as "Report directory: ...".
# A relative reports_root makes that value ambiguous with PathScope's own
# relative-path fallback (resolved against the report dir itself), producing
# a doubled, nonsensical path when a tool call echoes it back unmodified.
# baseline never hit this because its default reports_root (next to each
# sample) is already absolute.
RESULTS_ROOT = Path("experiments/results").resolve()

# ---------------------------------------------------------------------------
# Stage-skip ablation matrix: single-axis removals plus a cumulative
# "skip stage 1..N" progression, holding the model and every other pipeline
# knob constant so any accuracy delta is attributable to the missing stage(s).
# ---------------------------------------------------------------------------

STAGE_SKIP_CONFIGS: list[AblationConfig] = [
    # Keep only the static-analysis stages: unpack and dynamic both need the
    # VM/x64dbg, so dropping them simulates a static-only pipeline.
    AblationConfig("only_static", skip_stages=["03-unpack", "05-dynamic"]),
    # Keep only the dynamic-analysis path: no static disassembly passes.
    AblationConfig("only_dynamic", skip_stages=["02-static-pass1", "04-static-pass2"]),
    # Drop VirusTotal/public-intel enrichment: answers whether accuracy holds
    # on local static+dynamic+LLM evidence alone, without VT's own detection
    # ratio available to the model as a shortcut. Requires
    # ``experiments/seed_no_intel_ablation.py`` to have pre-seeded
    # ``ablation/no_intel/reports/<hash>`` from completed baseline_30 reports
    # (stages 01-05 reused, 06-intel's artifacts physically removed) --
    # otherwise this condition redoes all 9 stages from scratch like any
    # other fresh isolated reports_root.
    AblationConfig("no_intel", skip_stages=["06-intel"]),
]


@dataclasses.dataclass
class LlmCondition:
    slug: str
    model: str
    extended_thinking: bool = False
    thinking_budget_tokens: int = 4096
    reused_from_default_location: bool = False


LLM_CONDITIONS: list[LlmCondition] = [
    LlmCondition("deepseek_v4_flash", model="", reused_from_default_location=True),
    LlmCondition("gpt_5_6_luna", model="cheapluna"),
    LlmCondition("minimax_m2_7", model="vql/vql/minimax-m2.7"),
    LlmCondition("glm_5_3_flash", model="openrouter/z-ai/glm-5.3-flash"),
    LlmCondition("minimax_m3", model="cheapmini"),
    LlmCondition("gpt_5_6_terra", model="exp-terra"),
    LlmCondition("gpt_5_6_sol", model="exp-sol"),
    LlmCondition("claude_haiku_4_5", model="cheaphaiku"),
]


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def all_samples(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for label, key in ((LABEL_MALWARE, "malware"), (LABEL_BENIGN, "benign")):
        for entry in manifest[key]:
            out.append({**entry, "label": label})
    return out


def subset_samples(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in all_samples(manifest) if s.get("in_llm_ablation_subset")]


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _with_reports_root(config: HyperAgentConfig, root: Path) -> HyperAgentConfig:
    return dataclasses.replace(config, reports_root=root)


def _with_model(
    config: HyperAgentConfig,
    model: str,
    extended_thinking: bool,
    thinking_budget_tokens: int,
) -> HyperAgentConfig:
    provider = dataclasses.replace(
        config.provider,
        model=model or config.provider.model,
        extended_thinking=extended_thinking,
        thinking_budget_tokens=thinking_budget_tokens,
    )
    return dataclasses.replace(config, provider=provider)


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

#: (sample, config, ablation, run_id, out_dir). ``run_id`` is deterministic
#: (mode + condition/model + sample hash prefix) so it survives across
#: process restarts and can be matched against a prior ``progress.jsonl``.
Plan = tuple[dict[str, Any], HyperAgentConfig, "AblationConfig | None", str, Path]


def _load_progress(out_dir: Path) -> dict[str, dict[str, Any]]:
    """Rows already recorded in ``<out_dir>/progress.jsonl``, keyed by run_id.

    Reading this back is what makes a restart after a crash / power loss skip
    work that already completed instead of re-walking the whole plan.
    """
    path = out_dir / "progress.jsonl"
    done: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return done
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        run_id = row.get("run_id")
        if run_id:
            done[run_id] = row
    return done


def _append_progress(out_dir: Path, row: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "progress.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()


def _cache_hit_rate(cache_creation_tokens: int, cache_read_tokens: int) -> float:
    """Fraction of cacheable input tokens served from cache (0-1); 0 if nothing cacheable ran."""
    total = cache_creation_tokens + cache_read_tokens
    return cache_read_tokens / total if total > 0 else 0.0


def _compute_stage_aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate for single-stage runs: no verdict exists yet, only stage status."""
    status_counts: dict[str, int] = {}
    error_count = 0
    for row in rows:
        if row.get("error"):
            error_count += 1
            continue
        status = row.get("stage_status") or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
    total_cache_creation = sum(int(r.get("cache_creation_input_tokens") or 0) for r in rows)
    total_cache_read = sum(int(r.get("cache_read_input_tokens") or 0) for r in rows)
    return {
        "sample_count": len(rows),
        "error_count": error_count,
        "status_counts": status_counts,
        "total_input_tokens": sum(int(r.get("input_tokens") or 0) for r in rows),
        "total_output_tokens": sum(int(r.get("output_tokens") or 0) for r in rows),
        "total_cache_creation_input_tokens": total_cache_creation,
        "total_cache_read_input_tokens": total_cache_read,
        "cache_hit_rate": _cache_hit_rate(total_cache_creation, total_cache_read),
        "total_token_cost_usd": sum(float(r.get("token_cost_usd") or 0.0) for r in rows),
    }


def _write_aggregate(
    out_dir: Path,
    rows: list[dict[str, Any]],
    aggregate_fn: Callable[[list[dict[str, Any]]], dict[str, Any]] = compute_aggregate,
) -> dict[str, Any]:
    aggregate = aggregate_fn(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(
        json.dumps({"per_sample": rows, "aggregate": aggregate}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return aggregate


async def _run_one(sample: dict[str, Any], config: HyperAgentConfig, ablation: AblationConfig | None, run_id: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "run_id": run_id,
        "sample_sha256": sample["hash"],
        "label": sample["label"],
        "sample_path": sample["path"],
        "verdict": "",
        "predicted_malicious": None,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_hit_rate": 0.0,
        "token_cost_usd": 0.0,
        "wall_time_seconds": 0.0,
        "stage_count": 0,
        "refused": False,
        "error": "",
    }
    try:
        metrics = await run_pipeline_with_config(
            Path(sample["path"]), config, ablation, run_id=run_id
        )
    except Exception as exc:  # one bad sample must not abort the whole matrix
        logger.exception("run failed for %s", sample["hash"])
        row["error"] = f"{type(exc).__name__}: {exc}"
        return row

    row.update(
        input_tokens=metrics.total_input_tokens,
        output_tokens=metrics.total_output_tokens,
        cache_creation_input_tokens=metrics.total_cache_creation_tokens,
        cache_read_input_tokens=metrics.total_cache_read_tokens,
        cache_hit_rate=_cache_hit_rate(metrics.total_cache_creation_tokens, metrics.total_cache_read_tokens),
        token_cost_usd=metrics.total_effective_cost_usd,
        wall_time_seconds=metrics.total_wall_time_seconds,
        stage_count=len(metrics.stages),
    )
    refused_stages = getattr(metrics, "refused_stages", [])
    if refused_stages:
        row["refused"] = True
        row["error"] = f"model refused at: {', '.join(refused_stages)}"

    report_dir = _report_dir_for(Path(sample["path"]), config)
    verdict = read_verdict(report_dir)
    row["verdict"] = verdict or ""
    row["predicted_malicious"] = verdict_is_malicious(verdict)
    if verdict is None:
        row["error"] = row["error"] or "no verdict artifact"
    return row


async def _run_single_stage(
    sample: dict[str, Any], config: HyperAgentConfig, stage_id: str, run_id: str
) -> dict[str, Any]:
    """Run exactly one stage (no verdict to read yet -- report that stage's own status)."""
    row: dict[str, Any] = {
        "run_id": run_id,
        "sample_sha256": sample["hash"],
        "label": sample["label"],
        "sample_path": sample["path"],
        "stage_id": stage_id,
        "stage_status": "",
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_hit_rate": 0.0,
        "token_cost_usd": 0.0,
        "error": "",
    }
    try:
        metrics = await run_pipeline_with_config(
            Path(sample["path"]), config, None, run_id=run_id, stage_id=stage_id
        )
    except Exception as exc:
        logger.exception("stage %s failed for %s", stage_id, sample["hash"])
        row["error"] = f"{type(exc).__name__}: {exc}"
        return row

    row.update(
        input_tokens=metrics.total_input_tokens,
        output_tokens=metrics.total_output_tokens,
        cache_creation_input_tokens=metrics.total_cache_creation_tokens,
        cache_read_input_tokens=metrics.total_cache_read_tokens,
        cache_hit_rate=_cache_hit_rate(metrics.total_cache_creation_tokens, metrics.total_cache_read_tokens),
        token_cost_usd=metrics.total_effective_cost_usd,
    )

    report_dir = _report_dir_for(Path(sample["path"]), config)
    output_path = pipeline_state.default_output_path(report_dir, stage_id)
    if not output_path or not Path(output_path).exists():
        row["error"] = "no stage artifact"
        return row
    try:
        payload = json.loads(Path(output_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        row["error"] = f"could not parse stage artifact: {exc}"
        return row
    row["stage_status"] = str(payload.get("status", "")) or "unknown"
    return row


def _stage_only_runner(stage_id: str) -> Callable[..., Awaitable[dict[str, Any]]]:
    async def _runner(sample: dict[str, Any], config: HyperAgentConfig, ablation: AblationConfig | None, run_id: str) -> dict[str, Any]:
        del ablation  # single-stage runs never carry an ablation condition
        return await _run_single_stage(sample, config, stage_id, run_id)

    return _runner


async def _execute_and_report(
    plan: list[Plan],
    dry_run: bool,
    run_fn: Callable[[dict[str, Any], HyperAgentConfig, "AblationConfig | None", str], Awaitable[dict[str, Any]]] = _run_one,
    aggregate_fn: Callable[[list[dict[str, Any]]], dict[str, Any]] = compute_aggregate,
) -> None:
    if dry_run:
        print(f"[dry-run] {len(plan)} pipeline invocation(s) planned:")
        for sample, config, ablation, run_id, out_dir in plan:
            print(
                f"  run_id={run_id} sample={sample['hash'][:12]} label={sample['label']} "
                f"model={config.provider.model or '(config default)'} "
                f"ablation={ablation.name if ablation else '-'} out_dir={out_dir}"
            )
        return

    by_out_dir: dict[Path, list[Plan]] = {}
    for item in plan:
        by_out_dir.setdefault(item[4], []).append(item)

    for out_dir, items in by_out_dir.items():
        done = _load_progress(out_dir)
        rows = list(done.values())
        skipped = 0
        for sample, config, ablation, run_id, _ in items:
            if run_id in done:
                skipped += 1
                continue
            row = await run_fn(sample, config, ablation, run_id)
            _append_progress(out_dir, row)
            rows.append(row)
            _write_aggregate(out_dir, rows, aggregate_fn)  # rewritten after every sample
        if skipped:
            print(f"[{out_dir}] resumed: skipped {skipped} already-recorded run(s) from a prior attempt")
        aggregate = _write_aggregate(out_dir, rows, aggregate_fn)
        print(f"[{out_dir}] aggregate: {json.dumps(aggregate, indent=2)}")


async def run_static_bulk(manifest: dict[str, Any], dry_run: bool) -> None:
    """Bulk-run 02-static-pass1 across all 30 samples -- no VM/x64dbg involved.

    Safe to run before, or concurrently alongside, any VM-bound stage (01's
    dynamic-readiness check, 03-unpack, 05-dynamic) for a different sample.
    """
    samples = all_samples(manifest)
    config = load_config()
    out_dir = RESULTS_ROOT / "static_bulk_02"
    plan: list[Plan] = [
        (s, config, None, f"static02-{s['hash'][:12]}", out_dir) for s in samples
    ]
    await _execute_and_report(
        plan, dry_run, run_fn=_stage_only_runner("02-static-pass1"), aggregate_fn=_compute_stage_aggregate
    )


async def run_baseline(manifest: dict[str, Any], dry_run: bool) -> None:
    samples = all_samples(manifest)
    config = load_config()
    out_dir = RESULTS_ROOT / "baseline_30"
    plan: list[Plan] = [
        (s, config, None, f"baseline-{s['hash'][:12]}", out_dir) for s in samples
    ]
    await _execute_and_report(plan, dry_run)


async def run_ablation(manifest: dict[str, Any], dry_run: bool, conditions: list[str] | None = None) -> None:
    samples = subset_samples(manifest)
    base_config = load_config()
    plan: list[Plan] = []
    configs = STAGE_SKIP_CONFIGS
    if conditions:
        wanted = set(conditions)
        configs = [c for c in STAGE_SKIP_CONFIGS if c.name in wanted]
        unknown = wanted - {c.name for c in configs}
        if unknown:
            raise ValueError(f"Unknown ablation condition(s): {', '.join(sorted(unknown))}")
    for cond in configs:
        out_dir = RESULTS_ROOT / "ablation" / cond.name
        cond_config = _with_reports_root(base_config, out_dir / "reports")
        for s in samples:
            plan.append((s, cond_config, cond, f"ablation-{cond.name}-{s['hash'][:12]}", out_dir))
    await _execute_and_report(plan, dry_run)


async def run_llm_compare(manifest: dict[str, Any], dry_run: bool, conditions: list[str] | None = None) -> None:
    samples = subset_samples(manifest)
    base_config = load_config()
    active_conditions = LLM_CONDITIONS
    if conditions:
        # Preserve the requested --condition order (not LLM_CONDITIONS's
        # declaration order): _execute_and_report processes out_dirs in
        # plan-insertion order, so this is what actually controls which
        # condition runs first.
        by_slug = {c.slug: c for c in LLM_CONDITIONS}
        unknown = [slug for slug in conditions if slug not in by_slug]
        if unknown:
            raise ValueError(f"Unknown llm-compare condition(s): {', '.join(unknown)}")
        active_conditions = [by_slug[slug] for slug in conditions]
    # Stage 06-intel is always skipped for llm-compare: its VirusTotal-derived
    # claim_checks state the ground-truth verdict outright (e.g. "widely
    # flagged by multiple AV engines as malicious" / "CLEAN/harmless"),
    # confirmed 2026-08-27 in gpt_5_6_terra/gpt_5_6_sol's seeded 06-intel.json.
    # Reusing the no_intel ablation's own skip config keeps this identical to
    # that condition's mechanism rather than inventing a second one.
    no_intel = next(c for c in STAGE_SKIP_CONFIGS if c.name == "no_intel")
    plan: list[Plan] = []
    for cond in active_conditions:
        if cond.reused_from_default_location:
            continue
        out_dir = RESULTS_ROOT / "llm_compare" / cond.slug
        cond_config = _with_model(
            base_config, cond.model, cond.extended_thinking, cond.thinking_budget_tokens
        )
        cond_config = _with_reports_root(cond_config, out_dir / "reports")
        for s in samples:
            plan.append((s, cond_config, no_intel, f"llm-{cond.slug}-{s['hash'][:12]}", out_dir))
    await _execute_and_report(plan, dry_run)

    if dry_run:
        print(
            "[dry-run] deepseek_v4_flash: read-only from default reports_root, "
            f"{len(samples)} sample(s), no new pipeline calls."
        )
        return

    deepseek_rows = []
    for s in samples:
        report_dir = _report_dir_for(Path(s["path"]), base_config)
        verdict = read_verdict(report_dir)
        deepseek_rows.append(
            {
                "run_id": f"llm-deepseek_v4_flash-{s['hash'][:12]}",
                "sample_sha256": s["hash"],
                "label": s["label"],
                "sample_path": s["path"],
                "verdict": verdict or "",
                "predicted_malicious": verdict_is_malicious(verdict),
                "error": "" if verdict else "no verdict artifact yet (still running or not started)",
            }
        )
    out_dir = RESULTS_ROOT / "llm_compare" / "deepseek_v4_flash"
    aggregate = _write_aggregate(out_dir, deepseek_rows)
    print(f"[{out_dir}] (reused, no new run) aggregate: {json.dumps(aggregate, indent=2)}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HyperAgent NCKH study runner")
    parser.add_argument("mode", choices=["static-bulk", "baseline", "ablation", "llm-compare"])
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the run plan without executing anything"
    )
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--condition",
        action="append",
        help="ablation/llm-compare modes only: restrict to this condition/slug name (repeatable)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    manifest = load_manifest(args.manifest)
    if args.mode == "ablation":
        asyncio.run(run_ablation(manifest, args.dry_run, conditions=args.condition))
        return 0
    if args.mode == "llm-compare":
        asyncio.run(run_llm_compare(manifest, args.dry_run, conditions=args.condition))
        return 0

    mode_fn = {
        "static-bulk": run_static_bulk,
        "baseline": run_baseline,
    }[args.mode]
    asyncio.run(mode_fn(manifest, args.dry_run))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
