"""STATE.json read/write helper for the HyperAgent v4 pipeline.

Owns the canonical stage-id table and is the only supported way to read or
mutate ``<report_dir>/STATE.json``. The persisted state intentionally matches
``skill/_hyperagent-common/schemas/state.schema.json`` so launcher-created state,
skill validation, and report validation share one contract.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"

# Canonical stage-id table: stage_id -> skill + default output filename.
STAGE_TABLE: dict[str, dict[str, str | None]] = {
    "01-prepare-env": {"skill": "hyperagent-prepare-env", "output": "01-prepare-env.json"},
    "02-static-pass1": {"skill": "hyperagent-static", "output": "02-static-pass1.json"},
    "03-unpack": {"skill": "hyperagent-unpack", "output": "03-unpack.json"},
    "04-static-pass2": {"skill": "hyperagent-static", "output": "04-static-pass2.json"},
    "05-dynamic": {"skill": "hyperagent-dynamic", "output": "05-dynamic.json"},
    "06-intel": {"skill": "hyperagent-intel", "output": "06-intel.json"},
    "07-deepdive": {"skill": "hyperagent-deepdive", "output": "07-deepdive.json"},
    "08-report": {"skill": "hyperagent-report", "output": "08-report.md"},
    "09-summary": {"skill": "hyperagent-summary", "output": "09-summary.json"},
}

STAGE_IDS: tuple[str, ...] = tuple(STAGE_TABLE.keys())

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
# Kept as a compatibility constant for callers/tests, but not persisted because
# the common state schema represents retries via ``last_error`` and
# ``recommend_next_stage.action = retry_stage``.
STATUS_FAILED = "failed"

RECOMMEND_ACTION_RESUME_CURRENT = "resume_current"
RECOMMEND_ACTION_RUN_NEXT = "run_next"
RECOMMEND_ACTION_RETRY_STAGE = "retry_stage"
RECOMMEND_ACTION_PIPELINE_COMPLETE = "pipeline_complete"


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate_stage_id(stage_id: str) -> None:
    if stage_id not in STAGE_TABLE:
        raise ValueError(f"Unknown stage id: {stage_id!r}. Valid: {', '.join(STAGE_IDS)}")


def _next_stage_id(stage_id: str) -> str | None:
    _validate_stage_id(stage_id)
    index = STAGE_IDS.index(stage_id)
    return STAGE_IDS[index + 1] if index + 1 < len(STAGE_IDS) else None


def _stage_skill(stage_id: str | None) -> str | None:
    return STAGE_TABLE[stage_id]["skill"] if stage_id else None


def state_path_for(report_dir: Path) -> Path:
    return report_dir / "STATE.json"


def _make_recommend_next_stage(
    *,
    action: str,
    stage_id: str | None,
    source_stage_id: str | None,
    reason: str,
    progress_path: str | None,
) -> dict[str, Any]:
    return {
        "action": action,
        "stage_id": stage_id,
        "skill": _stage_skill(stage_id),
        "source_stage_id": source_stage_id,
        "reason": reason.strip(),
        "progress_path": progress_path,
    }


def _default_recommendation(report_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    stages = state.get("stages", {})
    for stage_id in STAGE_IDS:
        entry = stages.get(stage_id, {})
        if entry.get("status") == STATUS_RUNNING:
            progress_path = entry.get("progress_path")
            return _make_recommend_next_stage(
                action=RECOMMEND_ACTION_RESUME_CURRENT,
                stage_id=stage_id,
                source_stage_id=stage_id,
                reason=f"Resume {stage_id} from its recorded progress checkpoint.",
                progress_path=resolve_recorded_path(report_dir, progress_path) if progress_path else None,
            )

    last_completed: str | None = None
    for stage_id in STAGE_IDS:
        entry = stages.get(stage_id, {})
        if entry.get("status") == STATUS_PENDING:
            return _make_recommend_next_stage(
                action=RECOMMEND_ACTION_RUN_NEXT,
                stage_id=stage_id,
                source_stage_id=last_completed,
                reason=(
                    f"Stage {last_completed} completed; run {stage_id} next."
                    if last_completed else f"Run {stage_id} next."
                ),
                progress_path=None,
            )
        if entry.get("status") == STATUS_COMPLETED:
            last_completed = stage_id

    return _make_recommend_next_stage(
        action=RECOMMEND_ACTION_PIPELINE_COMPLETE,
        stage_id=None,
        source_stage_id=last_completed,
        reason="Pipeline is complete; no additional stage needs to run.",
        progress_path=None,
    )


def _new_state(sample_sha256: str, input_path: str, report_dir: Path) -> dict[str, Any]:
    now = _now_utc()
    stages = {
        stage_id: {
            "skill": meta["skill"],
            "status": STATUS_PENDING,
            "output_path": None,
            "progress_path": None,
            "updated_at": None,
        }
        for stage_id, meta in STAGE_TABLE.items()
    }
    state: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "timestamp_utc": now,
        "sample_sha256": sample_sha256,
        "input_path": input_path,
        "report_dir": str(report_dir),
        "current_stage_id": STAGE_IDS[0],
        "last_error": None,
        "stages": stages,
    }
    state["recommend_next_stage"] = _make_recommend_next_stage(
        action=RECOMMEND_ACTION_RUN_NEXT,
        stage_id=STAGE_IDS[0],
        source_stage_id=None,
        reason=f"Pipeline initialized; run {STAGE_IDS[0]} next.",
        progress_path=None,
    )
    return state


def normalize_state(report_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    """Return a schema-shaped state, accepting older v4 files as input."""
    now = state.get("timestamp_utc") or _now_utc()
    normalized: dict[str, Any] = {
        "schema_version": state.get("schema_version") or SCHEMA_VERSION,
        "timestamp_utc": now,
        "sample_sha256": state.get("sample_sha256", ""),
        "input_path": state.get("input_path", ""),
        "report_dir": state.get("report_dir") or str(report_dir),
        "current_stage_id": state.get("current_stage_id") if state.get("current_stage_id") in STAGE_TABLE else STAGE_IDS[0],
        "last_error": state.get("last_error"),
        "stages": {},
    }

    old_stages = state.get("stages", {}) if isinstance(state.get("stages"), dict) else {}
    for stage_id, meta in STAGE_TABLE.items():
        old_entry = old_stages.get(stage_id, {}) if isinstance(old_stages.get(stage_id, {}), dict) else {}
        status = old_entry.get("status", STATUS_PENDING)
        if status not in {STATUS_PENDING, STATUS_RUNNING, STATUS_COMPLETED}:
            if status == STATUS_FAILED and old_entry.get("error") and not normalized["last_error"]:
                normalized["last_error"] = f"[{stage_id}] {old_entry['error']}"
            status = STATUS_PENDING
        normalized["stages"][stage_id] = {
            "skill": old_entry.get("skill") or meta["skill"],
            "status": status,
            "output_path": old_entry.get("output_path"),
            "progress_path": old_entry.get("progress_path"),
            "updated_at": old_entry.get("updated_at"),
        }

    recommend = state.get("recommend_next_stage")
    if isinstance(recommend, dict):
        action = recommend.get("action")
        stage_id = recommend.get("stage_id")
        source_stage_id = recommend.get("source_stage_id")
        progress_path = recommend.get("progress_path")
        if stage_id not in STAGE_TABLE:
            stage_id = None
        if source_stage_id not in STAGE_TABLE:
            source_stage_id = None
        if action in {
            RECOMMEND_ACTION_RESUME_CURRENT,
            RECOMMEND_ACTION_RUN_NEXT,
            RECOMMEND_ACTION_RETRY_STAGE,
            RECOMMEND_ACTION_PIPELINE_COMPLETE,
        }:
            normalized["recommend_next_stage"] = _make_recommend_next_stage(
                action=action,
                stage_id=stage_id,
                source_stage_id=source_stage_id,
                reason=recommend.get("reason") or _default_recommendation(report_dir, normalized)["reason"],
                progress_path=resolve_recorded_path(report_dir, progress_path) if progress_path else None,
            )
        else:
            normalized["recommend_next_stage"] = _default_recommendation(report_dir, normalized)
    else:
        normalized["recommend_next_stage"] = _default_recommendation(report_dir, normalized)

    current = normalized["recommend_next_stage"].get("stage_id") or normalized["recommend_next_stage"].get("source_stage_id")
    if current in STAGE_TABLE:
        normalized["current_stage_id"] = current
    return normalized


def _save_state(report_dir: Path, state: dict[str, Any]) -> Path:
    """Write STATE.json atomically (tmp file + os.replace) to avoid torn writes."""
    path = state_path_for(report_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = normalize_state(report_dir, state)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(normalized, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp_path, path)
    return path


def load_state(report_dir: Path) -> dict[str, Any]:
    """Load STATE.json. Raises FileNotFoundError if it does not exist yet."""
    path = state_path_for(report_dir)
    if not path.exists():
        raise FileNotFoundError(f"STATE.json not found in {report_dir}; call ensure_state first")
    return normalize_state(report_dir, json.loads(path.read_text(encoding="utf-8")))


def ensure_state(report_dir: Path, sample_sha256: str, input_path: str) -> None:
    """Create STATE.json if missing. Idempotent; existing state is normalized."""
    path = state_path_for(report_dir)
    if path.exists():
        _save_state(report_dir, load_state(report_dir))
        return
    _save_state(report_dir, _new_state(sample_sha256, input_path, report_dir))


def default_output_path(report_dir: Path, stage_id: str) -> str | None:
    _validate_stage_id(stage_id)
    filename = STAGE_TABLE[stage_id]["output"]
    return str(report_dir / filename) if filename else None


def resolve_recorded_path(report_dir: Path, output_path: str) -> str:
    """Normalize a recorded STATE.json path to an absolute, cwd-independent one."""
    path = Path(output_path).expanduser()
    if not path.is_absolute():
        path = report_dir / path
    return str(path)


def checkpoint(report_dir: Path, stage_id: str, progress_path: str, recommend_reason: str = "") -> None:
    """Mark a stage 'running': it checkpointed and wrote a progress file."""
    _validate_stage_id(stage_id)
    state = load_state(report_dir)
    progress_path = resolve_recorded_path(report_dir, progress_path)
    now = _now_utc()
    entry = state["stages"][stage_id]
    entry["status"] = STATUS_RUNNING
    entry["progress_path"] = progress_path
    entry["updated_at"] = now
    state["current_stage_id"] = stage_id
    state["timestamp_utc"] = now
    state["recommend_next_stage"] = _make_recommend_next_stage(
        action=RECOMMEND_ACTION_RESUME_CURRENT,
        stage_id=stage_id,
        source_stage_id=stage_id,
        reason=recommend_reason or f"Resume {stage_id} from its recorded progress checkpoint.",
        progress_path=progress_path,
    )
    _save_state(report_dir, state)


def complete(report_dir: Path, stage_id: str, output_path: str, recommend_reason: str = "") -> None:
    """Mark a stage 'completed': final artifact written and validated."""
    _validate_stage_id(stage_id)
    state = load_state(report_dir)
    output_path = resolve_recorded_path(report_dir, output_path)
    now = _now_utc()
    entry = state["stages"][stage_id]
    entry["status"] = STATUS_COMPLETED
    entry["output_path"] = output_path
    entry["updated_at"] = now
    state["current_stage_id"] = stage_id
    state["last_error"] = None
    state["timestamp_utc"] = now

    next_stage_id = _next_stage_id(stage_id)
    if next_stage_id is None:
        state["recommend_next_stage"] = _make_recommend_next_stage(
            action=RECOMMEND_ACTION_PIPELINE_COMPLETE,
            stage_id=None,
            source_stage_id=stage_id,
            reason=recommend_reason or "Pipeline is complete; no additional stage needs to run.",
            progress_path=None,
        )
    else:
        state["recommend_next_stage"] = _make_recommend_next_stage(
            action=RECOMMEND_ACTION_RUN_NEXT,
            stage_id=next_stage_id,
            source_stage_id=stage_id,
            reason=recommend_reason or f"Stage {stage_id} completed; run {next_stage_id} next.",
            progress_path=None,
        )
    _save_state(report_dir, state)


def fail(report_dir: Path, stage_id: str, reason: str) -> None:
    """Record a retryable stage failure without writing schema-invalid statuses."""
    _validate_stage_id(stage_id)
    state = load_state(report_dir)
    now = _now_utc()
    state["current_stage_id"] = stage_id
    state["last_error"] = f"[{stage_id}] {reason}"
    state["timestamp_utc"] = now
    state["stages"][stage_id]["updated_at"] = now
    state["recommend_next_stage"] = _make_recommend_next_stage(
        action=RECOMMEND_ACTION_RETRY_STAGE,
        stage_id=stage_id,
        source_stage_id=stage_id,
        reason=f"Last attempt failed for {stage_id}: {reason}",
        progress_path=None,
    )
    _save_state(report_dir, state)
