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
from ..console import RunConsole
from ..providers import create_provider
from ..skills import SkillDoc, load_stage_skill
from ..telemetry.metrics import MetricsCollector, RunMetrics
from ..tools import vmware_tools
from ..tools.path_scope import compute_run_scope
from ..tools.registry import (
    STAGE_TOOLS,
    ToolRegistry,
    build_full_registry,
    common_scripts_dir,
    missing_x64dbg_required_tools,
    refresh_x64dbg_tools,
)
from .agent_loop import AgentLoop, ModelRefusal
from .checkpoint import CheckpointReached, compact_messages, write_checkpoint
from .mcp_servers import ensure_idalib_mcp, stop_idalib_mcp

logger = logging.getLogger(__name__)

#: Cap on host-side VM/x64dbg auto-recovery attempts per guarded stage run.
#: Kept low and separate from ``max_stage_attempts``: once the guest session
#: is genuinely re-established, further wrappers-missing failures are a real
#: problem (bad debugger path, crashing x64dbg, etc.), not a stale VM, and
#: should fall through to the normal checkpoint-and-retry path rather than
#: repeatedly reverting a VM that keeps coming back broken.
_MAX_VM_AUTO_RECOVERY_ATTEMPTS = 1

#: Extra bounded rounds tried once a stage exhausts its whole
#: ``max_stage_attempts`` budget, before giving up on it entirely. Each round
#: writes its own checkpoint on failure, so a round that still overflows
#: context hands the next one an even more compacted summary to work from.
_MAX_FINALIZE_ATTEMPTS = 2

#: Turn budget for a finalize round. Its only job is to transcribe an
#: already-checkpointed summary into a schema-valid artifact, not to keep
#: investigating, so it needs far fewer turns than a real attempt.
_FINALIZE_MAX_TURNS = 8

_FINALIZE_DIRECTIVE = (
    "\n\n[FINAL ATTEMPT -- WRITE NOW]\n"
    "The attempt budget for this stage is exhausted. Do not call any more "
    "exploratory, debugging, or environment tools, and do not keep "
    "investigating. Your only remaining job is to write the stage's output "
    "artifact right now, using everything already discovered in the "
    "checkpoint summary above.\n"
    "- Populate every field the schema requires; an incomplete artifact is "
    "not acceptable a second time.\n"
    "- For anything that was not confirmed, use the schema's own uncertainty "
    "vocabulary (e.g. status values like partial/blocked/unknown, low "
    "confidence scores, and entries in limitations) instead of asserting a "
    "conclusion you have no evidence for.\n"
    "- Call validate_json_output before finishing, exactly as the skill "
    "instructs, and stop as soon as it returns VALID."
)

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


def _artifact_validation_error(stage: Stage, output_path: Path | None, skill_doc: SkillDoc) -> str | None:
    if output_path is None:
        return "no canonical output path is defined for this stage"
    if not output_path.exists():
        return f"artifact missing at {output_path}"

    if stage.stage_id == "08-report":
        return None if output_path.read_text(encoding="utf-8").strip() else f"artifact at {output_path} is empty"

    if skill_doc.schema_path is None or not skill_doc.schema_path.exists():
        return None if output_path.stat().st_size > 0 else f"artifact at {output_path} is empty"

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return f"artifact at {output_path} is not valid JSON: {exc.msg}"

    try:
        schema = json.loads(skill_doc.schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        return f"artifact at {output_path} does not match schema: {exc.message}"
    except Exception as exc:
        return f"artifact at {output_path} could not be validated: {exc}"
    return None


def _artifact_is_valid(stage: Stage, output_path: Path | None, skill_doc: SkillDoc) -> bool:
    return _artifact_validation_error(stage, output_path, skill_doc) is None


def _fallback_complete_if_valid(report_dir: Path, stage: Stage, skill_doc: SkillDoc) -> Path | None:
    output_path = _default_output_path(report_dir, stage.stage_id)
    if _artifact_validation_error(stage, output_path, skill_doc) is not None:
        return None

    pipeline_state.complete(
        report_dir,
        stage.stage_id,
        str(output_path),
        "launcher fallback: valid artifact found after agent exited without updating STATE.json",
    )
    return output_path


def _ablated_upstream_note(stage: Stage, ablation_config: Any) -> list[str]:
    """Tell a stage which upstream artifacts were withheld on purpose.

    Without this the ablation measures the wrong thing. Skipping a stage
    deletes its artifact, and the downstream skills list several of those as
    required inputs with no "when present" qualifier — so the agent meets a
    missing file it was told to expect. Deepdive's claim policy then does
    exactly what it should and refuses to assert behaviour it has no evidence
    for, the verdict falls to ``inconclusive``, and ``verdict_is_malicious``
    reads that as benign.

    The A1/A2 columns would then show a large recall drop that says nothing
    about how much static or dynamic analysis contributes. It only restates
    that the claim policy blocks conclusions without evidence, which is true by
    construction. An ablation has to degrade the pipeline's *information*, not
    break its plumbing, so the run profile is announced and the stage is asked
    to reason from a smaller evidence set and record the limitation.
    """
    skipped = list(getattr(ablation_config, "skip_stages", []) or [])
    if not skipped:
        return []

    order = {s.stage_id: i for i, s in enumerate(STAGES)}
    upstream = [
        stage_id
        for stage_id in skipped
        if order.get(stage_id, len(STAGES)) < order.get(stage.stage_id, 0)
    ]
    if not upstream:
        return []

    name = getattr(ablation_config, "name", "ablation")
    lines = [
        f"Run profile: {name}. The following upstream stages were disabled for "
        "this run, so their artifacts do not exist:",
    ]
    lines.extend(f"- {stage_id}" for stage_id in upstream)
    lines.extend([
        "Treat those inputs as not collected in this run profile, not as an "
        "error and not as a blocker.",
        "Proceed with the evidence that is present, state the missing coverage "
        "in the limitations of your artifact, and scope your claims to what the "
        "remaining evidence supports.",
        "Do not invent replacement findings, and do not stop to look for the "
        "missing files.",
    ])
    return lines


def _build_stage_prompt(
    sample_path: Path,
    report_dir: Path,
    stage: Stage,
    state_path: Path,
    skill_doc: SkillDoc,
    skills_root: Path,
    ablation_config: Any = None,
) -> str:
    lines = [
        f"Analyze sample: {sample_path}",
        f"Report directory: {report_dir}",
        f"STATE.json path: {state_path}",
        f"Current stage_id: {stage.stage_id}",
    ]
    if skill_doc.schema_path is not None:
        lines.append(f"Stage schema path: {skill_doc.schema_path}")
    lines.append(f"Common scripts directory: {common_scripts_dir(skills_root)}")
    default_output = _default_output_path(report_dir, stage.stage_id)
    if default_output is not None:
        lines.append(f"Default stage output path: {default_output}")
    lines.extend([
        "Operational contract:",
        "- Do not manually discover SKILL.md, schema.json, or validator-script paths; use the resolved paths provided in this prompt.",
        "- Do not write STATE.json directly; write and validate the default stage artifact, then the launcher records completion.",
        "- If a filesystem path is denied by scope policy, treat it as out of bounds instead of searching other roots.",
    ])
    if ablation_config is not None:
        lines.extend(_ablated_upstream_note(stage, ablation_config))
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


def _checkpoint_summary(loop: AgentLoop, reason: str = "Resume from the latest completed reasoning state.") -> str:
    parts = [
        "# Checkpoint",
        "",
        reason,
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


def _checkpoint_summary_or_compact(
    loop: AgentLoop,
    provider: Any,
    stage_id: str,
    config: HyperAgentConfig,
    reason: str = "Resume from the latest completed reasoning state.",
) -> str:
    """Between-attempt checkpoint text: a real semantic summary when possible.

    ``_checkpoint_summary`` alone only keeps the last 4 messages (500 chars
    each), so a fresh attempt starts having "forgotten" whatever the previous
    attempt discovered (OEP location, working breakpoints, dead ends already
    tried) -- forcing costly rediscovery every retry. ``compact_messages``
    already does this well for mid-attempt context-limit compaction; reuse it
    here so it also survives a full attempt boundary. Falls back to the crude
    last-4-messages summary if compaction itself fails (e.g. too little
    history to compact), mirroring agent_loop.py's own fallback behavior.
    """
    last_messages = getattr(loop, "last_messages", [])
    try:
        target_tokens = int(
            provider.max_context_tokens() * getattr(config, "compact_target_ratio", 0.45)
        )
        compacted = compact_messages(
            provider,
            last_messages,
            stage_id=stage_id,
            target_tokens=target_tokens,
            max_summary_tokens=getattr(config, "max_compaction_tokens", 2048),
        )
    except Exception as exc:
        logger.warning(
            "Checkpoint compaction failed for %s; falling back to raw message preview: %s",
            stage_id,
            exc,
        )
        return _checkpoint_summary(loop, reason)

    return "\n".join(["# Checkpoint", "", reason, "", "## Prior progress (compacted)", compacted.summary])


def _force_finalize_stage(
    *,
    report_dir: Path,
    stage: Stage,
    skill_doc: SkillDoc,
    sample_path: Path,
    state_path: Path,
    config: HyperAgentConfig,
    registry: ToolRegistry,
    tool_names: list[str],
    include_injection_guard: bool,
    cache_enabled: bool,
    checkpoint_threshold: float,
    model_name: str,
    run_console: RunConsole | None,
    metrics: MetricsCollector,
    ablation_config: Any,
    index: int,
    total: int,
) -> Path | None:
    """Turn whatever a stage already discovered into a real artifact instead
    of discarding it once the attempt budget is gone.

    Every prior attempt in this run now ends via ``CheckpointReached`` (see
    agent_loop.py), so by the time ``max_stage_attempts`` is exhausted there
    is almost always a checkpointed progress summary on disk -- the work just
    never made it into a validated artifact (context overflow, a flaky tool
    call, an environment hiccup mid-turn). Failing the whole sample here
    throws that work away. Instead, run a couple of small, tightly bounded
    rounds whose only job is to transcribe the checkpoint into a schema-valid
    artifact, using the schema's own partial/blocked/unknown vocabulary for
    whatever was never confirmed rather than fabricating a finished analysis.
    """
    base_prompt = _build_stage_prompt(
        sample_path, report_dir, stage, state_path, skill_doc, config.skills_root, ablation_config,
    )

    for finalize_attempt in range(1, _MAX_FINALIZE_ATTEMPTS + 1):
        resume_prompt = _resume_prompt_if_any(report_dir, stage.stage_id)
        prompt = base_prompt
        if resume_prompt:
            prompt = f"{prompt}\n\n{resume_prompt}"
        prompt = f"{prompt}{_FINALIZE_DIRECTIVE}"

        provider = create_provider(
            config.provider, model=model_name, cache_enabled=cache_enabled, run_console=run_console,
        )
        loop = AgentLoop(
            provider,
            registry,
            checkpoint_threshold=checkpoint_threshold,
            max_turns=_FINALIZE_MAX_TURNS,
            metrics=metrics,
            console_mode=config.provider.console_mode,
            run_console=run_console,
            compact_enabled=getattr(config, "compact_enabled", True),
            compact_threshold=getattr(config, "compact_threshold", None),
            compact_target_ratio=getattr(config, "compact_target_ratio", 0.45),
            max_compactions=getattr(config, "max_compactions", 3),
            max_compaction_tokens=getattr(config, "max_compaction_tokens", 2048),
        )
        logger.warning(
            "[%d/%d] %s exhausted its attempt budget; forcing a finalize pass (%d/%d) from checkpointed progress",
            index, total, stage.stage_id, finalize_attempt, _MAX_FINALIZE_ATTEMPTS,
        )
        try:
            loop.run(
                skill_instructions=skill_doc.instructions,
                initial_prompt=prompt,
                stage_tools=tool_names,
                reads_sample_content=stage.reads_sample_content,
                stage_id=stage.stage_id,
                include_injection_guard=include_injection_guard,
            )
        except CheckpointReached:
            write_checkpoint(
                report_dir,
                stage.stage_id,
                _checkpoint_summary_or_compact(loop, provider, stage.stage_id, config),
                "context threshold during forced finalize",
            )
            continue
        except ModelRefusal:
            return None

        fallback_output = _fallback_complete_if_valid(report_dir, stage, skill_doc)
        if fallback_output is not None:
            return fallback_output

    return None


def _runtime_value(config: HyperAgentConfig, name: str, default: Any) -> Any:
    runtime = getattr(config, "runtime", None)
    return getattr(runtime, name, default)


def _profile_stage_ids(profile: str) -> tuple[str, ...]:
    normalized = (profile or "full").lower().replace("_", "-")
    if normalized == "full":
        return tuple(stage.stage_id for stage in STAGES)
    if normalized in {"fast", "static-only"}:
        return (
            "01-prepare-env",
            "02-static-pass1",
            "03-unpack",
            "04-static-pass2",
            "07-deepdive",
            "08-report",
            "09-summary",
        )
    raise ValueError("Unknown pipeline profile: " f"{profile!r}. Valid: full, fast, static-only")


def _selected_stages(
    stage_id: str | None,
    *,
    profile: str = "full",
    skip_dynamic: bool = False,
    skip_intel: bool = False,
) -> tuple[Stage, ...]:
    if stage_id is None:
        selected_ids = list(_profile_stage_ids(profile))
    else:
        if stage_id not in {stage.stage_id for stage in STAGES}:
            raise ValueError(f"Unknown stage: {stage_id!r}. Valid: {[stage.stage_id for stage in STAGES]}")
        selected_ids = [stage_id]

    if skip_dynamic:
        selected_ids = [sid for sid in selected_ids if sid != "05-dynamic"]
    if skip_intel:
        selected_ids = [sid for sid in selected_ids if sid != "06-intel"]

    by_id = {stage.stage_id: stage for stage in STAGES}
    return tuple(by_id[stage_id] for stage_id in selected_ids)


def _stage_patterns_need_ida(stage_ids: tuple[str, ...]) -> bool:
    for stage_id in stage_ids:
        patterns = STAGE_TOOLS.get(stage_id, [])
        if "source:ida" in patterns or "ida_health_check" in patterns:
            return True
    return False


def _should_start_idalib_mcp(config: HyperAgentConfig, selected_stages: tuple[Stage, ...]) -> bool:
    strategy = str(_runtime_value(config, "start_ida_mcp", "auto")).lower()
    if strategy == "always":
        return True
    if strategy == "never":
        return False
    if strategy != "auto":
        raise ValueError("Unknown runtime.start_ida_mcp: " f"{strategy!r}. Valid: auto, always, never")
    return _stage_patterns_need_ida(tuple(stage.stage_id for stage in selected_stages))


async def run_pipeline_with_config(
    sample_path: Path,
    config: HyperAgentConfig,
    ablation_config: AblationConfig | None = None,
    run_id: str | None = None,
    *,
    stage_id: str | None = None,
    run_console: RunConsole | None = None,
) -> RunMetrics:
    """Run the HyperAgent pipeline for one sample and return aggregate metrics."""
    sample_path = Path(sample_path).expanduser().resolve()
    if not sample_path.exists():
        raise FileNotFoundError(f"Sample does not exist: {sample_path}")

    selected_stages = _selected_stages(
        stage_id,
        profile=_runtime_value(config, "pipeline_profile", "full"),
        skip_dynamic=bool(_runtime_value(config, "skip_dynamic", False)),
        skip_intel=bool(_runtime_value(config, "skip_intel", False)),
    )
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

    idalib_proc = None
    clients = []
    try:
        if run_console is not None:
            run_console.start()

        idalib_proc = ensure_idalib_mcp(config) if _should_start_idalib_mcp(config, selected_stages) else None
        registry, clients = build_full_registry(config, scope)
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
                reuse_completed_stages = bool(_runtime_value(config, "reuse_completed_stages", True))

                if reuse_completed_stages and entry["status"] == pipeline_state.STATUS_COMPLETED:
                    validation_error = _artifact_validation_error(stage, stage_output, skill_doc)
                    if validation_error is None:
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
                    failure_reason = f"State drift: {stage.stage_id} marked completed but {validation_error}"
                    logger.error("[%d/%d] %s", index, len(selected_stages), failure_reason)
                    return metrics.finalize_run()

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
                vm_recovery_attempts = 0
                stage_metrics_started = False
                max_stage_attempts = getattr(config, "stage_max_attempts", {}).get(
                    stage.stage_id, config.max_stage_attempts
                )
                profile = str(_runtime_value(config, "pipeline_profile", "full")).lower().replace("_", "-")
                if profile in {"fast", "static-only"}:
                    max_stage_attempts = min(
                        max_stage_attempts,
                        int(_runtime_value(config, "fast_max_stage_attempts", max_stage_attempts)),
                    )
                while True:
                    attempts += 1
                    if attempts > max_stage_attempts:
                        if not stage_metrics_started:
                            metrics.start_stage(stage.stage_id)
                            stage_metrics_started = True
                        finalize_output = _force_finalize_stage(
                            report_dir=report_dir,
                            stage=stage,
                            skill_doc=skill_doc,
                            sample_path=sample_path,
                            state_path=state_path,
                            config=config,
                            registry=registry,
                            tool_names=tool_names,
                            include_injection_guard=include_injection_guard,
                            cache_enabled=cache_enabled,
                            checkpoint_threshold=checkpoint_threshold,
                            model_name=model_name,
                            run_console=run_console,
                            metrics=metrics,
                            ablation_config=ablation_config,
                            index=index,
                            total=len(selected_stages),
                        )
                        if finalize_output is not None:
                            logger.warning(
                                "[%d/%d] %s force-finalized from checkpointed progress after "
                                "exhausting %d attempts",
                                index,
                                len(selected_stages),
                                stage.stage_id,
                                max_stage_attempts,
                            )
                            metrics.finalize_stage(stage.stage_id, status="completed")
                            break

                        pipeline_state.fail(
                            report_dir,
                            stage.stage_id,
                            f"did not reach completed after {max_stage_attempts} attempts "
                            "(forced finalize also failed)",
                        )
                        metrics.finalize_stage(stage.stage_id, status="failed")
                        failure_reason = (
                            f"{stage.stage_id} did not reach 'completed' after {max_stage_attempts} "
                            "attempts (forced finalize also failed)"
                        )
                        logger.error("[%d/%d] %s", index, len(selected_stages), failure_reason)
                        return metrics.finalize_run()

                    x64dbg_client = refresh_x64dbg_tools(
                        registry,
                        clients,
                        config.x64dbg_mcp,
                        stage.stage_id,
                        current_client=clients[0] if clients else None,
                    )
                    if x64dbg_client is not None and clients:
                        clients[0] = x64dbg_client
                    stage_tools = registry.get_tools_for_stage(stage.stage_id)
                    tool_names = [tool.name for tool in stage_tools]
                    missing_x64dbg = []
                    if "source:x64dbg" in STAGE_TOOLS.get(stage.stage_id, []):
                        missing_x64dbg = missing_x64dbg_required_tools(registry)
                        if missing_x64dbg:
                            logger.warning(
                                "Resolved %s without required x64dbg wrappers; missing: %s",
                                stage.stage_id,
                                ", ".join(missing_x64dbg),
                            )
                            tool_names = [
                                name for name in tool_names
                                if name != "x64dbg_health_check"
                            ]
                    logger.debug(
                        "Resolved tools for %s attempt %d: %s",
                        stage.stage_id,
                        attempts,
                        ", ".join(tool_names),
                    )

                    provider = create_provider(
                        config.provider,
                        model=model_name,
                        cache_enabled=cache_enabled,
                        run_console=run_console,
                    )
                    loop = AgentLoop(
                        provider,
                        registry,
                        checkpoint_threshold=checkpoint_threshold,
                        metrics=metrics,
                        console_mode=config.provider.console_mode,
                        run_console=run_console,
                        compact_enabled=(
                            getattr(config, "compact_enabled", True)
                            and (not ablation_config or ablation_config.checkpoint_enabled)
                        ),
                        compact_threshold=getattr(config, "compact_threshold", None),
                        compact_target_ratio=getattr(config, "compact_target_ratio", 0.45),
                        max_compactions=getattr(config, "max_compactions", 3),
                        max_compaction_tokens=getattr(config, "max_compaction_tokens", 2048),
                    )
                    if not stage_metrics_started:
                        metrics.start_stage(stage.stage_id, provider=getattr(provider, "_model", ""))
                        stage_metrics_started = True

                    if run_console is not None:
                        run_console.stage_transition(
                            index=index,
                            total=len(selected_stages),
                            stage_id=stage.stage_id,
                            stage_name=stage.skill,
                            attempt=attempts,
                            guarded=stage.reads_sample_content,
                        )
                    if missing_x64dbg:
                        if vm_recovery_attempts < _MAX_VM_AUTO_RECOVERY_ATTEMPTS:
                            vm_recovery_attempts += 1
                            logger.warning(
                                "[%d/%d] %s missing x64dbg debugger wrappers; attempting automatic "
                                "VM/debugger recovery (%d/%d) before retrying.",
                                index,
                                len(selected_stages),
                                stage.stage_id,
                                vm_recovery_attempts,
                                _MAX_VM_AUTO_RECOVERY_ATTEMPTS,
                            )
                            recovery_result = vmware_tools.vm_auto_recover_dynamic_env(
                                config.vmware, sample_path, scope
                            )
                            logger.warning(
                                "[%d/%d] %s automatic VM recovery %s: %s",
                                index,
                                len(selected_stages),
                                stage.stage_id,
                                "failed" if recovery_result.is_error else "succeeded",
                                recovery_result.content,
                            )
                            continue

                        progress_path = write_checkpoint(
                            report_dir,
                            stage.stage_id,
                            (
                                "x64dbg MCP is reachable only partially or not yet fully initialized. "
                                f"Required debugger wrappers are missing: {', '.join(missing_x64dbg)}. "
                                "Resume this stage after the guest x64dbg MCP exposes the full debugger tool set."
                            ),
                            "required x64dbg debugger wrappers missing",
                        )
                        logger.warning(
                            "[%d/%d] %s missing x64dbg debugger wrappers; checkpointed at %s and retrying.",
                            index,
                            len(selected_stages),
                            stage.stage_id,
                            progress_path,
                        )
                        continue
                    logger.info(
                        "[%d/%d] Running %s (stage_id=%s, attempt=%d, guarded=%s)",
                        index,
                        len(selected_stages),
                        stage.skill,
                        stage.stage_id,
                        attempts,
                        stage.reads_sample_content,
                        extra={"run_console_skip": run_console is not None},
                    )

                    stage_prompt = _build_stage_prompt(
                        sample_path,
                        report_dir,
                        stage,
                        state_path,
                        skill_doc,
                        config.skills_root,
                        ablation_config,
                    )
                    resume_prompt = _resume_prompt_if_any(report_dir, stage.stage_id)
                    if resume_prompt:
                        stage_prompt = f"{stage_prompt}\n\n{resume_prompt}"

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
                            _checkpoint_summary_or_compact(loop, provider, stage.stage_id, config),
                            "context threshold",
                        )
                    except ModelRefusal as exc:
                        # Deterministic for a given sample+prompt, so the retry
                        # loop would only refuse again at full token cost. Fail
                        # the run here, and record the cause distinctly so a
                        # corpus sweep can report a refusal rate instead of
                        # burying these in the generic failure count.
                        pipeline_state.fail(report_dir, stage.stage_id, str(exc))
                        metrics.finalize_stage(stage.stage_id, status="refused")
                        failure_reason = f"{stage.stage_id} refused: {exc}"
                        logger.error("[%d/%d] %s", index, len(selected_stages), failure_reason)
                        return metrics.finalize_run()

                    state = pipeline_state.load_state(report_dir)
                    entry = state["stages"][stage.stage_id]
                    stage_output = _resolve_stage_output(report_dir, stage, entry)
                    status = entry.get("status") or pipeline_state.STATUS_PENDING

                    if status == pipeline_state.STATUS_COMPLETED:
                        validation_error = _artifact_validation_error(stage, stage_output, skill_doc)
                        if validation_error is None:
                            metrics.finalize_stage(stage.stage_id, status="completed")
                            break
                        pipeline_state.fail(
                            report_dir,
                            stage.stage_id,
                            f"marked completed but {validation_error}",
                        )
                        metrics.finalize_stage(stage.stage_id, status="failed")
                        failure_reason = f"{stage.stage_id} exited 0 and claimed completed but {validation_error}"
                        logger.error("[%d/%d] %s", index, len(selected_stages), failure_reason)
                        return metrics.finalize_run()

                    if status == pipeline_state.STATUS_RUNNING:
                        fallback_output = _fallback_complete_if_valid(report_dir, stage, skill_doc)
                        if fallback_output is not None:
                            logger.warning(
                                "[%d/%d] launcher auto-completed %s from valid artifact at %s after a resumed attempt exited without updating STATE.json",
                                index,
                                len(selected_stages),
                                stage.stage_id,
                                fallback_output,
                            )
                            metrics.finalize_stage(stage.stage_id, status="completed")
                            break
                        logger.info(
                            "[%d/%d] %s checkpointed at %s; resuming.",
                            index,
                            len(selected_stages),
                            stage.stage_id,
                            entry.get("progress_path"),
                        )
                        continue

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

                    if attempts < max_stage_attempts:
                        progress_path = write_checkpoint(
                            report_dir,
                            stage.stage_id,
                            _checkpoint_summary_or_compact(
                                loop,
                                provider,
                                stage.stage_id,
                                config,
                                "The previous attempt ended normally but did not write a valid final "
                                "artifact or update STATE.json. Resume from the prior progress below, "
                                "finish the required artifact, validate it, and mark this stage completed.",
                            ),
                            "resume after agent ended without writing a valid artifact or updating STATE.json",
                        )
                        logger.warning(
                            "[%d/%d] %s ended without artifact/state update; checkpointed at %s and retrying.",
                            index,
                            len(selected_stages),
                            stage.stage_id,
                            progress_path,
                        )
                        continue

                    if attempts >= max_stage_attempts:
                        finalize_output = _force_finalize_stage(
                            report_dir=report_dir,
                            stage=stage,
                            skill_doc=skill_doc,
                            sample_path=sample_path,
                            state_path=state_path,
                            config=config,
                            registry=registry,
                            tool_names=tool_names,
                            include_injection_guard=include_injection_guard,
                            cache_enabled=cache_enabled,
                            checkpoint_threshold=checkpoint_threshold,
                            model_name=model_name,
                            run_console=run_console,
                            metrics=metrics,
                            ablation_config=ablation_config,
                            index=index,
                            total=len(selected_stages),
                        )
                        if finalize_output is not None:
                            logger.warning(
                                "[%d/%d] %s force-finalized after exiting without checkpointing or "
                                "completing on its last attempt",
                                index,
                                len(selected_stages),
                                stage.stage_id,
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
        if run_console is not None:
            run_console.finish()

    return metrics.finalize_run()
