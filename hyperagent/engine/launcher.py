"""Pipeline launcher for HyperAgent v4.

Ports the v3 CLI-based stage driver into an in-process SDK launcher that runs
one ``AgentLoop`` per stage, with the stage's resolved SKILL.md instructions
and allowed tool subset.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema

from .. import pipeline_state
from ..config import HyperAgentConfig
from ..providers import create_provider
from ..skills import SkillDoc, load_stage_skill
from ..telemetry.metrics import MetricsCollector, RunMetrics
from ..tools import vmware_tools
from ..tools.path_scope import compute_run_scope
from ..tools.registry import STAGE_TOOLS, ToolRegistry, build_full_registry
from .agent_loop import AgentLoop
from .checkpoint import CheckpointReached, write_checkpoint
from .mcp_servers import ensure_idalib_mcp, stop_idalib_mcp

logger = logging.getLogger(__name__)

try:
    from experiments.ablation_runner import AblationConfig
except Exception:  # pragma: no cover - experiments package may be absent/broken
    AblationConfig = Any  # type: ignore[misc,assignment]


@dataclass(frozen=True)
class Stage:
    """One pipeline stage definition."""

    stage_id: str
    skill: str
    reads_sample_content: bool


STAGES: tuple[Stage, ...] = (
    Stage("01-prepare-env", "hyperagent-prepare-env", reads_sample_content=False),
    Stage("02-static-pass1", "hyperagent-static", reads_sample_content=True),
    Stage("03-unpack", "hyperagent-unpack", reads_sample_content=True),
    Stage("04-static-pass2", "hyperagent-static", reads_sample_content=True),
    Stage("05-dynamic", "hyperagent-dynamic", reads_sample_content=True),
    Stage("06-intel", "hyperagent-intel", reads_sample_content=True),
    Stage("07-deepdive", "hyperagent-deepdive", reads_sample_content=True),
    Stage("08-report", "hyperagent-report", reads_sample_content=False),
    Stage("09-summary", "hyperagent-summary", reads_sample_content=False),
)


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _report_dir_for(sample_path: Path, config: HyperAgentConfig) -> Path:
    root = config.reports_root or (sample_path.parent / "reports")
    return Path(root) / _sha256_of(sample_path)


def _default_output_path(report_dir: Path, stage_id: str) -> Path | None:
    output = pipeline_state.default_output_path(report_dir, stage_id)
    return Path(output) if output else None


def _resolve_stage_output(report_dir: Path, stage: Stage, entry: dict[str, Any]) -> Path | None:
    if entry.get("output_path"):
        return Path(pipeline_state.resolve_recorded_path(report_dir, entry["output_path"]))
    return _default_output_path(report_dir, stage.stage_id)


def _artifact_is_valid(stage: Stage, output_path: Path | None, skill_doc: SkillDoc) -> bool:
    if output_path is None or not output_path.exists():
        return False

    if stage.stage_id == "08-report":
        return bool(output_path.read_text(encoding="utf-8").strip())

    if skill_doc.schema_path is None or not skill_doc.schema_path.exists():
        return output_path.stat().st_size > 0

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        schema = json.loads(skill_doc.schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(payload, schema)
    except Exception:
        return False
    return True


def _fallback_complete_if_valid(report_dir: Path, stage: Stage, skill_doc: SkillDoc) -> Path | None:
    output_path = _default_output_path(report_dir, stage.stage_id)
    if not _artifact_is_valid(stage, output_path, skill_doc):
        return None

    pipeline_state.complete(
        report_dir,
        stage.stage_id,
        str(output_path),
        "launcher fallback: valid artifact found after agent exited without updating STATE.json",
    )
    return output_path


def _build_stage_prompt(sample_path: Path, report_dir: Path, stage: Stage, state_path: Path) -> str:
    lines = [
        f"Analyze sample: {sample_path}",
        f"Report directory: {report_dir}",
        f"STATE.json path: {state_path}",
        f"Current stage_id: {stage.stage_id}",
    ]
    default_output = _default_output_path(report_dir, stage.stage_id)
    if default_output is not None:
        lines.append(f"Default stage output path: {default_output}")
    lines.append("Honor the stage output/state contract for this stage.")
    return "\n".join(lines)


def _resume_prompt_if_any(report_dir: Path, stage_id: str) -> str | None:
    state = pipeline_state.load_state(report_dir)
    entry = state["stages"][stage_id]
    progress_path = entry.get("progress_path")
    if entry.get("status") != pipeline_state.STATUS_RUNNING or not progress_path:
        return None

    resolved = Path(pipeline_state.resolve_recorded_path(report_dir, progress_path))
    if not resolved.exists():
        return None

    progress_text = resolved.read_text(encoding="utf-8").strip()
    if not progress_text:
        return None

    return (
        "Resume this stage from the previously checkpointed progress summary below. "
        "Reuse prior work instead of restarting from scratch.\n\n"
        f"{progress_text}"
    )


def _checkpoint_summary(loop: AgentLoop) -> str:
    parts = [
        "# Checkpoint",
        "",
        "Resume from the latest completed reasoning state.",
    ]
    last_messages = getattr(loop, "last_messages", [])
    preview_parts: list[str] = []
    for message in last_messages[-4:]:
        text = message.content if isinstance(message.content, str) else str(message.content)
        text = text.strip()
        if text:
            preview_parts.append(f"- {message.role}: {text[:500]}")
    if preview_parts:
        parts.extend(["", "## Recent conversation", *preview_parts])
    return "\n".join(parts)


def _selected_stages(stage_id: str | None) -> tuple[Stage, ...]:
    if stage_id is None:
        return STAGES
    selected = tuple(stage for stage in STAGES if stage.stage_id == stage_id)
    if not selected:
        raise ValueError(f"Unknown stage: {stage_id!r}. Valid: {[stage.stage_id for stage in STAGES]}")
    return selected


async def run_pipeline_with_config(
    sample_path: Path,
    config: HyperAgentConfig,
    ablation_config: AblationConfig | None = None,
    run_id: str | None = None,
    *,
    stage_id: str | None = None,
) -> RunMetrics:
    """Run the HyperAgent pipeline for one sample and return aggregate metrics."""
    sample_path = Path(sample_path).expanduser().resolve()
    if not sample_path.exists():
        raise FileNotFoundError(f"Sample does not exist: {sample_path}")

    selected_stages = _selected_stages(stage_id)
    sample_sha256 = _sha256_of(sample_path)
    report_dir = _report_dir_for(sample_path, config)
    scope = compute_run_scope(sample_path, report_dir, config.skills_root)
    pipeline_state.ensure_state(report_dir, sample_sha256, str(sample_path))
    state_path = pipeline_state.state_path_for(report_dir)

    metrics = MetricsCollector(
        run_id=run_id or uuid.uuid4().hex,
        sample_sha256=sample_sha256,
        output_path=report_dir / "telemetry.jsonl",
        ablation_config=(getattr(ablation_config, "name", "FULL") if ablation_config else "FULL"),
    )

    idalib_proc = ensure_idalib_mcp(config)
    registry, clients = build_full_registry(config, scope)
    try:
        for index, stage in enumerate(selected_stages, start=1):
            failure_reason: str | None = None
            try:
                if stage.stage_id not in STAGE_TOOLS:
                    raise KeyError(f"Missing STAGE_TOOLS entry for {stage.stage_id}")

                skill_doc = load_stage_skill(config.skills_root, stage.skill)

                if ablation_config and stage.stage_id in getattr(ablation_config, "skip_stages", []):
                    logger.info(
                        "[%d/%d] Skipping %s due to ablation config",
                        index,
                        len(selected_stages),
                        stage.stage_id,
                    )
                    metrics.start_stage(stage.stage_id)
                    metrics.finalize_stage(stage.stage_id, status="completed")
                    continue

                state = pipeline_state.load_state(report_dir)
                entry = state["stages"][stage.stage_id]
                stage_output = _resolve_stage_output(report_dir, stage, entry)

                if entry["status"] == pipeline_state.STATUS_COMPLETED:
                    if _artifact_is_valid(stage, stage_output, skill_doc):
                        logger.info(
                            "[%d/%d] Skipping %s (%s): already completed.",
                            index,
                            len(selected_stages),
                            stage.stage_id,
                            stage.skill,
                        )
                        continue
                    metrics.start_stage(stage.stage_id)
                    metrics.finalize_stage(stage.stage_id, status="failed")
                    failure_reason = (
                        f"State drift: {stage.stage_id} marked completed but artifact missing/invalid at {stage_output}"
                    )
                    logger.error("[%d/%d] %s", index, len(selected_stages), failure_reason)
                    return metrics.finalize_run()

                stage_tools = registry.get_tools_for_stage(stage.stage_id)
                tool_names = [tool.name for tool in stage_tools]
                model_name = config.provider.stage_models.get(stage.stage_id, config.provider.model)
                checkpoint_threshold = (
                    config.checkpoint_threshold
                    if not ablation_config or ablation_config.checkpoint_enabled
                    else 1.0
                )
                include_injection_guard = (
                    True if not ablation_config else ablation_config.injection_guard
                )
                cache_enabled = True if not ablation_config else ablation_config.cache_enabled

                attempts = 0
                stage_metrics_started = False
                while True:
                    attempts += 1
                    if attempts > config.max_stage_attempts:
                        pipeline_state.fail(
                            report_dir,
                            stage.stage_id,
                            f"did not reach completed after {config.max_stage_attempts} attempts",
                        )
                        if not stage_metrics_started:
                            metrics.start_stage(stage.stage_id)
                            stage_metrics_started = True
                        metrics.finalize_stage(stage.stage_id, status="failed")
                        failure_reason = (
                            f"{stage.stage_id} did not reach 'completed' after {config.max_stage_attempts} attempts"
                        )
                        logger.error("[%d/%d] %s", index, len(selected_stages), failure_reason)
                        return metrics.finalize_run()

                    provider = create_provider(
                        config.provider,
                        model=model_name,
                        cache_enabled=cache_enabled,
                    )
                    loop = AgentLoop(
                        provider,
                        registry,
                        checkpoint_threshold=checkpoint_threshold,
                        metrics=metrics,
                        console_mode=config.provider.console_mode,
                    )
                    if not stage_metrics_started:
                        metrics.start_stage(stage.stage_id, provider=getattr(provider, "_model", ""))
                        stage_metrics_started = True

                    stage_prompt = _build_stage_prompt(sample_path, report_dir, stage, state_path)
                    resume_prompt = _resume_prompt_if_any(report_dir, stage.stage_id)
                    if resume_prompt:
                        stage_prompt = f"{stage_prompt}\n\n{resume_prompt}"

                    logger.info(
                        "[%d/%d] Running %s (stage_id=%s, attempt=%d, guarded=%s)",
                        index,
                        len(selected_stages),
                        stage.skill,
                        stage.stage_id,
                        attempts,
                        stage.reads_sample_content,
                    )

                    try:
                        loop.run(
                            skill_instructions=skill_doc.instructions,
                            initial_prompt=stage_prompt,
                            stage_tools=tool_names,
                            reads_sample_content=stage.reads_sample_content,
                            stage_id=stage.stage_id,
                            include_injection_guard=include_injection_guard,
                        )
                    except CheckpointReached:
                        write_checkpoint(
                            report_dir,
                            stage.stage_id,
                            _checkpoint_summary(loop),
                            "context threshold",
                        )

                    state = pipeline_state.load_state(report_dir)
                    entry = state["stages"][stage.stage_id]
                    stage_output = _resolve_stage_output(report_dir, stage, entry)
                    status = entry.get("status") or pipeline_state.STATUS_PENDING

                    if status == pipeline_state.STATUS_RUNNING:
                        logger.info(
                            "[%d/%d] %s checkpointed at %s; resuming.",
                            index,
                            len(selected_stages),
                            stage.stage_id,
                            entry.get("progress_path"),
                        )
                        continue

                    if status == pipeline_state.STATUS_COMPLETED:
                        if _artifact_is_valid(stage, stage_output, skill_doc):
                            metrics.finalize_stage(stage.stage_id, status="completed")
                            break
                        pipeline_state.fail(
                            report_dir,
                            stage.stage_id,
                            f"marked completed but artifact missing/invalid at {stage_output}",
                        )
                        metrics.finalize_stage(stage.stage_id, status="failed")
                        failure_reason = (
                            f"{stage.stage_id} exited 0 and claimed completed but artifact at {stage_output} is missing or invalid"
                        )
                        logger.error("[%d/%d] %s", index, len(selected_stages), failure_reason)
                        return metrics.finalize_run()

                    fallback_output = _fallback_complete_if_valid(report_dir, stage, skill_doc)
                    if fallback_output is not None:
                        logger.warning(
                            "[%d/%d] launcher auto-completed %s from valid artifact at %s after agent exited without updating STATE.json",
                            index,
                            len(selected_stages),
                            stage.stage_id,
                            fallback_output,
                        )
                        metrics.finalize_stage(stage.stage_id, status="completed")
                        break

                    pipeline_state.fail(
                        report_dir,
                        stage.stage_id,
                        "exited 0 without checkpointing or completing",
                    )
                    metrics.finalize_stage(stage.stage_id, status="failed")
                    failure_reason = (
                        f"{stage.stage_id} exited 0 without marking itself running or completed in STATE.json"
                    )
                    logger.error("[%d/%d] %s", index, len(selected_stages), failure_reason)
                    return metrics.finalize_run()
            finally:
                if stage.stage_id == "05-dynamic" and hasattr(vmware_tools, "vm_auto_revert_after_dynamic"):
                    vmware_tools.vm_auto_revert_after_dynamic(config.vmware)
    finally:
        for client in clients:
            try:
                client.close()
            except Exception:
                logger.warning("Failed to close MCP client cleanly", exc_info=True)
        stop_idalib_mcp(idalib_proc)

    return metrics.finalize_run()
