"""STATE.json read/write helper for the HyperAgent pipeline.

This is the single implementation of the stage table and of every STATE.json
mutation. The launcher imports it directly; the skill-side CLI
(``skill/_hyperagent-common/scripts/pipeline_state.py``) and the skill helper
scripts that need the stage table import it too, so the launcher, the skills
and the validators cannot drift apart.

The persisted state matches ``skill/_hyperagent-common/schemas/state.schema.json``.
Stage statuses:

- ``pending``:   stage has not started yet.
- ``running``:   stage checkpointed near its context limit and wrote a progress
                 file; it is NOT finished and must resume from ``progress_path``.
- ``completed``: the stage's final artifact was written and validated.

The top-level ``recommend_next_stage`` is a state-derived hint for operators
and resume logic. A recorded recommendation that no longer matches the stage
statuses is replaced by one inferred from them.

Nothing here depends on the current working directory: every recorded path is
resolved against the report directory and stored absolute.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"

# Canonical stage table: stage_id -> skill, default output filename, and whether
# the stage reads sample-derived content (strings, disassembly, unpacked
# payloads, network capture...) and so needs the anti-injection guard.
# hyperagent-static runs twice (pass 1 and pass 2), so everything keys on
# stage_id, never on the skill name alone.
STAGE_TABLE: dict[str, dict[str, Any]] = {
    "01-prepare-env": {
        "skill": "hyperagent-prepare-env", "output": "01-prepare-env.json", "reads_sample": False,
    },
    "02-static-pass1": {
        "skill": "hyperagent-static", "output": "02-static-pass1.json", "reads_sample": True,
    },
    "03-unpack": {"skill": "hyperagent-unpack", "output": "03-unpack.json", "reads_sample": True},
    "04-static-pass2": {
        "skill": "hyperagent-static", "output": "04-static-pass2.json", "reads_sample": True,
    },
    "05-dynamic": {"skill": "hyperagent-dynamic", "output": "05-dynamic.json", "reads_sample": True},
    "06-intel": {"skill": "hyperagent-intel", "output": "06-intel.json", "reads_sample": True},
    "07-deepdive": {
        "skill": "hyperagent-deepdive", "output": "07-deepdive.json", "reads_sample": True,
    },
    "08-report": {"skill": "hyperagent-report", "output": "08-report.md", "reads_sample": False},
    "09-summary": {
        "skill": "hyperagent-summary", "output": "09-summary.json", "reads_sample": False,
    },
}

STAGE_IDS: tuple[str, ...] = tuple(STAGE_TABLE.keys())
STAGE_SKILLS: dict[str, str] = {stage_id: meta["skill"] for stage_id, meta in STAGE_TABLE.items()}


def stage_schema_rel(stage_id: str) -> str | None:
    """Schema path relative to the skills root, or None for Markdown-only stages."""
    _validate_stage_id(stage_id)
    meta = STAGE_TABLE[stage_id]
    if not str(meta["output"]).endswith(".json"):
        return None
    return f"{meta['skill']}/schema.json"


STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
VALID_STATUSES = (STATUS_PENDING, STATUS_RUNNING, STATUS_COMPLETED)
# Kept as a compatibility constant for callers/tests, but never persisted: the
# state schema represents retries via ``last_error`` and
# ``recommend_next_stage.action = retry_stage``.
STATUS_FAILED = "failed"

RECOMMEND_ACTION_RESUME_CURRENT = "resume_current"
RECOMMEND_ACTION_RUN_NEXT = "run_next"
RECOMMEND_ACTION_RETRY_STAGE = "retry_stage"
RECOMMEND_ACTION_PIPELINE_COMPLETE = "pipeline_complete"
VALID_RECOMMEND_ACTIONS = (
    RECOMMEND_ACTION_RESUME_CURRENT,
    RECOMMEND_ACTION_RUN_NEXT,
    RECOMMEND_ACTION_RETRY_STAGE,
    RECOMMEND_ACTION_PIPELINE_COMPLETE,
)


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate_stage_id(stage_id: str) -> None:
    if stage_id not in STAGE_TABLE:
        raise ValueError(f"Unknown stage id: {stage_id!r}. Valid: {', '.join(STAGE_IDS)}")


def _next_stage_id(stage_id: str) -> str | None:
    _validate_stage_id(stage_id)
    index = STAGE_IDS.index(stage_id)
    return STAGE_IDS[index + 1] if index + 1 < len(STAGE_IDS) else None


def state_path_for(report_dir: Path) -> Path:
    return report_dir / "STATE.json"


def default_output_path(report_dir: Path, stage_id: str) -> str | None:
    _validate_stage_id(stage_id)
    filename = STAGE_TABLE[stage_id]["output"]
    return str(report_dir / filename) if filename else None


def default_progress_path(report_dir: Path, stage_id: str) -> str:
    _validate_stage_id(stage_id)
    return str(report_dir / "_state" / f"{stage_id}.progress.md")


def _collapse_repeated_report_dir(report_dir: Path, path: Path) -> Path:
    """Undo ``report_dir / "reports/<sha256>/x"`` -> ``report_dir / "x"``.

    Skills describe artifacts with repo-relative paths such as
    ``reports/<sha256>/07-deepdive.json``. Joining one of those onto the report
    directory repeats the ``<sha256>`` segment and records a path that does
    not exist, which later reads as "completed artifact missing". When the
    report directory's own name reappears below it, keep only what follows
    its last occurrence.
    """
    try:
        rel_parts = path.relative_to(report_dir).parts
    except ValueError:
        return path
    name = report_dir.name
    dirs = rel_parts[:-1]
    if not name or name not in dirs:
        return path
    last = len(dirs) - 1 - dirs[::-1].index(name)
    return report_dir.joinpath(*rel_parts[last + 1:])


def resolve_recorded_path(report_dir: Path, recorded: str) -> str:
    """Normalize a recorded STATE.json path to an absolute, cwd-independent one.

    Absolute paths pass through; relative paths are resolved against the report
    directory. Either way a repeated ``<report_dir>/reports/<sha256>/`` prefix
    is collapsed (see ``_collapse_repeated_report_dir``).
    """
    path = Path(recorded).expanduser()
    if not path.is_absolute():
        path = report_dir / path
    return str(_collapse_repeated_report_dir(report_dir, path))


def _default_recommend_reason(action: str, stage_id: str | None, source_stage_id: str | None) -> str:
    if action == RECOMMEND_ACTION_RESUME_CURRENT and stage_id:
        return f"Resume {stage_id} from its recorded progress checkpoint."
    if action == RECOMMEND_ACTION_RUN_NEXT and stage_id and source_stage_id:
        return f"Stage {source_stage_id} completed; run {stage_id} next."
    if action == RECOMMEND_ACTION_RUN_NEXT and stage_id:
        return f"Run {stage_id} next."
    if action == RECOMMEND_ACTION_RETRY_STAGE and stage_id:
        return f"Retry {stage_id} after resolving the recorded error."
    return "Pipeline is complete; no additional stage needs to run."


def _make_recommend_next_stage(
    *,
    action: str,
    stage_id: str | None,
    source_stage_id: str | None,
    reason: str | None,
    progress_path: str | None,
) -> dict[str, Any]:
    if action not in VALID_RECOMMEND_ACTIONS:
        raise ValueError(
            f"Unknown recommend_next_stage action: {action!r}. "
            f"Valid: {', '.join(VALID_RECOMMEND_ACTIONS)}"
        )
    for candidate in (stage_id, source_stage_id):
        if candidate is not None:
            _validate_stage_id(candidate)

    if action == RECOMMEND_ACTION_PIPELINE_COMPLETE:
        stage_id = None
        progress_path = None
    elif stage_id is None:
        raise ValueError(f"{action} requires a stage_id")
    elif action == RECOMMEND_ACTION_RESUME_CURRENT:
        if not progress_path:
            raise ValueError("resume_current requires a progress_path")
    else:
        progress_path = None

    return {
        "action": action,
        "stage_id": stage_id,
        "skill": STAGE_SKILLS[stage_id] if stage_id else None,
        "source_stage_id": source_stage_id,
        "reason": (reason or _default_recommend_reason(action, stage_id, source_stage_id)).strip(),
        "progress_path": progress_path,
    }


def _infer_recommendation(report_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    stages = state.get("stages", {})
    for stage_id in STAGE_IDS:
        entry = stages.get(stage_id, {})
        if entry.get("status") == STATUS_RUNNING:
            progress_path = entry.get("progress_path") or default_progress_path(report_dir, stage_id)
            return _make_recommend_next_stage(
                action=RECOMMEND_ACTION_RESUME_CURRENT,
                stage_id=stage_id,
                source_stage_id=stage_id,
                reason=None,
                progress_path=resolve_recorded_path(report_dir, progress_path),
            )

    last_completed: str | None = None
    for stage_id in STAGE_IDS:
        status = stages.get(stage_id, {}).get("status")
        if status == STATUS_PENDING:
            return _make_recommend_next_stage(
                action=RECOMMEND_ACTION_RUN_NEXT,
                stage_id=stage_id,
                source_stage_id=last_completed,
                reason=None,
                progress_path=None,
            )
        if status == STATUS_COMPLETED:
            last_completed = stage_id

    return _make_recommend_next_stage(
        action=RECOMMEND_ACTION_PIPELINE_COMPLETE,
        stage_id=None,
        source_stage_id=last_completed,
        reason=None,
        progress_path=None,
    )


def _recommendation_matches_state(state: dict[str, Any], action: str, stage_id: str | None) -> bool:
    stages = state.get("stages", {})
    if action == RECOMMEND_ACTION_PIPELINE_COMPLETE:
        return all(stages.get(sid, {}).get("status") == STATUS_COMPLETED for sid in STAGE_IDS)
    if stage_id is None:
        return False
    status = stages.get(stage_id, {}).get("status")
    if action == RECOMMEND_ACTION_RESUME_CURRENT:
        return status == STATUS_RUNNING
    if action == RECOMMEND_ACTION_RUN_NEXT:
        return status == STATUS_PENDING
    if action == RECOMMEND_ACTION_RETRY_STAGE:
        return status != STATUS_COMPLETED
    return False


def _normalize_recommendation(report_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    recommend = state.get("recommend_next_stage")
    if not isinstance(recommend, dict):
        return _infer_recommendation(report_dir, state)

    action = recommend.get("action")
    stage_id = recommend.get("stage_id")
    source_stage_id = recommend.get("source_stage_id")
    if (
        action not in VALID_RECOMMEND_ACTIONS
        or (stage_id is not None and stage_id not in STAGE_TABLE)
        or not _recommendation_matches_state(state, action, stage_id)
    ):
        return _infer_recommendation(report_dir, state)
    if source_stage_id not in STAGE_TABLE:
        source_stage_id = None

    progress_path = None
    if action == RECOMMEND_ACTION_RESUME_CURRENT:
        recorded = recommend.get("progress_path") or state["stages"][stage_id].get("progress_path")
        if not recorded:
            return _infer_recommendation(report_dir, state)
        progress_path = resolve_recorded_path(report_dir, recorded)

    return _make_recommend_next_stage(
        action=action,
        stage_id=stage_id,
        source_stage_id=source_stage_id,
        reason=recommend.get("reason"),
        progress_path=progress_path,
    )


def _new_state(sample_sha256: str, input_path: str, report_dir: Path) -> dict[str, Any]:
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
    return {
        "schema_version": SCHEMA_VERSION,
        "timestamp_utc": _now_utc(),
        "sample_sha256": sample_sha256,
        "input_path": input_path,
        "report_dir": str(report_dir),
        "current_stage_id": STAGE_IDS[0],
        "last_error": None,
        "stages": stages,
        "recommend_next_stage": _make_recommend_next_stage(
            action=RECOMMEND_ACTION_RUN_NEXT,
            stage_id=STAGE_IDS[0],
            source_stage_id=None,
            reason=f"Pipeline initialized; run {STAGE_IDS[0]} next.",
            progress_path=None,
        ),
    }


def new_state(sample_sha256: str, input_path: str, report_dir: Path) -> dict[str, Any]:
    """A fresh, unsaved pipeline state."""
    return _new_state(sample_sha256, input_path, report_dir)


def normalize_state(report_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    """Return a schema-shaped state, accepting older v3/v4 files as input."""
    normalized: dict[str, Any] = {
        "schema_version": state.get("schema_version") or SCHEMA_VERSION,
        "timestamp_utc": state.get("timestamp_utc") or _now_utc(),
        "sample_sha256": state.get("sample_sha256", ""),
        "input_path": state.get("input_path", ""),
        "report_dir": state.get("report_dir") or str(report_dir),
        "current_stage_id": (
            state.get("current_stage_id")
            if state.get("current_stage_id") in STAGE_TABLE
            else STAGE_IDS[0]
        ),
        "last_error": state.get("last_error"),
        "stages": {},
    }

    old_stages = state.get("stages") if isinstance(state.get("stages"), dict) else {}
    for stage_id, meta in STAGE_TABLE.items():
        old_entry = old_stages.get(stage_id)
        old_entry = old_entry if isinstance(old_entry, dict) else {}
        status = old_entry.get("status", STATUS_PENDING)
        if status not in VALID_STATUSES:
            if status == STATUS_FAILED and old_entry.get("error") and not normalized["last_error"]:
                normalized["last_error"] = f"[{stage_id}] {old_entry['error']}"
            status = STATUS_PENDING
        output_path = old_entry.get("output_path")
        progress_path = old_entry.get("progress_path")
        normalized["stages"][stage_id] = {
            "skill": old_entry.get("skill") or meta["skill"],
            "status": status,
            "output_path": resolve_recorded_path(report_dir, output_path) if output_path else None,
            "progress_path": (
                resolve_recorded_path(report_dir, progress_path) if progress_path else None
            ),
            "updated_at": old_entry.get("updated_at"),
        }

    normalized["recommend_next_stage"] = _normalize_recommendation(report_dir, {
        **normalized,
        "recommend_next_stage": state.get("recommend_next_stage"),
    })

    recommend = normalized["recommend_next_stage"]
    current = recommend.get("stage_id") or recommend.get("source_stage_id")
    if current in STAGE_TABLE:
        normalized["current_stage_id"] = current
    return normalized


def save_state(report_dir: Path, state: dict[str, Any]) -> Path:
    """Write STATE.json atomically (tmp file + os.replace) to avoid torn writes."""
    path = state_path_for(report_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = normalize_state(report_dir, state)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(normalized, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp_path, path)
    return path


_save_state = save_state


def load_state(report_dir: Path) -> dict[str, Any]:
    """Load STATE.json. Raises FileNotFoundError if it does not exist yet."""
    path = state_path_for(report_dir)
    if not path.exists():
        raise FileNotFoundError(f"STATE.json not found in {report_dir}; call ensure_state first")
    return normalize_state(report_dir, json.loads(path.read_text(encoding="utf-8")))


def ensure_state(report_dir: Path, sample_sha256: str, input_path: str) -> dict[str, Any]:
    """Create STATE.json if missing. Idempotent; existing state is normalized."""
    if state_path_for(report_dir).exists():
        state = load_state(report_dir)
    else:
        state = _new_state(sample_sha256, input_path, report_dir)
    save_state(report_dir, state)
    return load_state(report_dir)


def checkpoint(
    report_dir: Path, stage_id: str, progress_path: str, recommend_reason: str | None = ""
) -> dict[str, Any]:
    """Mark a stage 'running': it checkpointed and wrote a progress file."""
    _validate_stage_id(stage_id)
    if not progress_path:
        raise ValueError("checkpoint requires a non-empty progress_path")
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
        reason=recommend_reason,
        progress_path=progress_path,
    )
    save_state(report_dir, state)
    return state


def complete(
    report_dir: Path, stage_id: str, output_path: str, recommend_reason: str | None = ""
) -> dict[str, Any]:
    """Mark a stage 'completed': final artifact written and validated.

    If the given path does not exist but the stage's canonical artifact does
    (same filename), the canonical path is recorded instead, so a wrongly
    rooted path cannot leave STATE.json pointing at a missing file.
    """
    _validate_stage_id(stage_id)
    if not output_path:
        raise ValueError("complete requires a non-empty output_path")
    state = load_state(report_dir)
    output_path = resolve_recorded_path(report_dir, output_path)
    default = default_output_path(report_dir, stage_id)
    if (
        default
        and not Path(output_path).exists()
        and Path(default).exists()
        and Path(output_path).name == Path(default).name
    ):
        output_path = default
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
            reason=recommend_reason,
            progress_path=None,
        )
    else:
        state["recommend_next_stage"] = _make_recommend_next_stage(
            action=RECOMMEND_ACTION_RUN_NEXT,
            stage_id=next_stage_id,
            source_stage_id=stage_id,
            reason=recommend_reason,
            progress_path=None,
        )
    save_state(report_dir, state)
    return state


def fail(report_dir: Path, stage_id: str, reason: str) -> dict[str, Any]:
    """Record a retryable stage failure without writing a schema-invalid status.

    A stage that was marked completed is demoted to pending: the failure means
    its artifact cannot be trusted, and a retry recommendation for a completed
    stage would contradict the status (and be discarded on the next load).
    """
    _validate_stage_id(stage_id)
    state = load_state(report_dir)
    now = _now_utc()
    state["current_stage_id"] = stage_id
    state["last_error"] = f"[{stage_id}] {reason}"
    state["timestamp_utc"] = now
    entry = state["stages"][stage_id]
    if entry["status"] == STATUS_COMPLETED:
        entry["status"] = STATUS_PENDING
    entry["updated_at"] = now
    state["recommend_next_stage"] = _make_recommend_next_stage(
        action=RECOMMEND_ACTION_RETRY_STAGE,
        stage_id=stage_id,
        source_stage_id=stage_id,
        reason=f"Last attempt failed for {stage_id}: {reason}",
        progress_path=None,
    )
    save_state(report_dir, state)
    return state
