#!/usr/bin/env python3
"""Shared STATE.json helper for the HyperAgent v3 pipeline.

Owns the canonical stage-id table and is the only supported way to read or
mutate ``reports/<sha256>/STATE.json``. Skills and the launcher must call
this module instead of hand-editing the JSON, so status semantics stay
consistent pipeline-wide:

- ``pending``:   stage has not started yet.
- ``running``:   stage stopped because context usage reached >= 80% and a
                 progress file was written; it is NOT finished and must be
                 resumed from ``progress_path``.
- ``completed``: the stage's final artifact was written, validated, and
                 there is no follow-up problem left for that stage.

The top-level ``recommend_next_stage`` field is a normalized summary for
operator-facing helpers such as ``hyperagent-progress``. It does not override
stage status or ordinal stage order; it is a state-derived hint describing the
next safe action for this run.

Never depends on ``cwd`` — every path is taken from arguments or resolved
against the report directory.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCHEMA_VERSION = "1.0"

# Canonical stage-id table: stage_id -> (skill, default output filename or None for Markdown-only stages)
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
VALID_STATUSES = (STATUS_PENDING, STATUS_RUNNING, STATUS_COMPLETED)

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
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")



def _validate_stage_id(stage_id: str) -> None:
    if stage_id not in STAGE_TABLE:
        raise SystemExit(f"Unknown stage id: {stage_id!r}. Valid: {', '.join(STAGE_IDS)}")



def _validate_optional_stage_id(stage_id: str | None) -> None:
    if stage_id is not None:
        _validate_stage_id(stage_id)



def _next_stage_id(stage_id: str) -> str | None:
    _validate_stage_id(stage_id)
    index = STAGE_IDS.index(stage_id)
    return STAGE_IDS[index + 1] if index + 1 < len(STAGE_IDS) else None



def _default_recommend_reason(
    action: str,
    stage_id: str | None,
    source_stage_id: str | None,
) -> str:
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
) -> dict:
    if action not in VALID_RECOMMEND_ACTIONS:
        raise SystemExit(
            f"Unknown recommend_next_stage action: {action!r}. Valid: {', '.join(VALID_RECOMMEND_ACTIONS)}"
        )
    _validate_optional_stage_id(stage_id)
    _validate_optional_stage_id(source_stage_id)

    if action == RECOMMEND_ACTION_PIPELINE_COMPLETE:
        stage_id = None
        progress_path = None
    elif action == RECOMMEND_ACTION_RESUME_CURRENT:
        if stage_id is None:
            raise SystemExit("resume_current requires a stage_id")
        if not progress_path:
            raise SystemExit("resume_current requires a progress_path")
    else:
        if stage_id is None:
            raise SystemExit(f"{action} requires a stage_id")
        progress_path = None

    return {
        "action": action,
        "stage_id": stage_id,
        "skill": STAGE_TABLE[stage_id]["skill"] if stage_id else None,
        "source_stage_id": source_stage_id,
        "reason": (reason or _default_recommend_reason(action, stage_id, source_stage_id)).strip(),
        "progress_path": progress_path,
    }



def state_path_for(report_dir: Path) -> Path:
    return report_dir / "STATE.json"



def _infer_recommend_next_stage(report_dir: Path, state: dict) -> dict:
    stages = state.get("stages", {})

    for stage_id in STAGE_IDS:
        entry = stages.get(stage_id, {})
        if entry.get("status") != STATUS_RUNNING:
            continue
        progress_path = entry.get("progress_path")
        if not progress_path:
            progress_path = default_progress_path(report_dir, stage_id)
        return _make_recommend_next_stage(
            action=RECOMMEND_ACTION_RESUME_CURRENT,
            stage_id=stage_id,
            source_stage_id=stage_id,
            reason=None,
            progress_path=resolve_recorded_path(report_dir, progress_path),
        )

    for index, stage_id in enumerate(STAGE_IDS):
        entry = stages.get(stage_id, {})
        if entry.get("status") != STATUS_PENDING:
            continue
        source_stage_id = None
        for previous_stage_id in reversed(STAGE_IDS[:index]):
            previous_entry = stages.get(previous_stage_id, {})
            if previous_entry.get("status") == STATUS_COMPLETED:
                source_stage_id = previous_stage_id
                break
        return _make_recommend_next_stage(
            action=RECOMMEND_ACTION_RUN_NEXT,
            stage_id=stage_id,
            source_stage_id=source_stage_id,
            reason=None,
            progress_path=None,
        )

    last_completed_stage_id = None
    for stage_id in reversed(STAGE_IDS):
        entry = stages.get(stage_id, {})
        if entry.get("status") == STATUS_COMPLETED:
            last_completed_stage_id = stage_id
            break

    return _make_recommend_next_stage(
        action=RECOMMEND_ACTION_PIPELINE_COMPLETE,
        stage_id=None,
        source_stage_id=last_completed_stage_id,
        reason=None,
        progress_path=None,
    )



def _recommendation_matches_state(state: dict, action: str, stage_id: str | None) -> bool:
    stages = state.get("stages", {})

    if action == RECOMMEND_ACTION_PIPELINE_COMPLETE:
        return all(stages.get(candidate, {}).get("status") == STATUS_COMPLETED for candidate in STAGE_IDS)

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



def normalize_state(report_dir: Path, state: dict) -> dict:
    recommend = state.get("recommend_next_stage")
    if not isinstance(recommend, dict):
        state["recommend_next_stage"] = _infer_recommend_next_stage(report_dir, state)
        return state

    action = recommend.get("action")
    stage_id = recommend.get("stage_id")
    source_stage_id = recommend.get("source_stage_id")
    reason = recommend.get("reason")
    progress_path = recommend.get("progress_path")

    if action not in VALID_RECOMMEND_ACTIONS:
        state["recommend_next_stage"] = _infer_recommend_next_stage(report_dir, state)
        return state

    if stage_id is not None and stage_id not in STAGE_TABLE:
        state["recommend_next_stage"] = _infer_recommend_next_stage(report_dir, state)
        return state

    if source_stage_id is not None and source_stage_id not in STAGE_TABLE:
        state["recommend_next_stage"] = _infer_recommend_next_stage(report_dir, state)
        return state

    if not _recommendation_matches_state(state, action, stage_id):
        state["recommend_next_stage"] = _infer_recommend_next_stage(report_dir, state)
        return state

    if action == RECOMMEND_ACTION_RESUME_CURRENT:
        if progress_path:
            progress_path = resolve_recorded_path(report_dir, progress_path)
        else:
            entry_progress_path = state.get("stages", {}).get(stage_id, {}).get("progress_path")
            if not entry_progress_path:
                state["recommend_next_stage"] = _infer_recommend_next_stage(report_dir, state)
                return state
            progress_path = resolve_recorded_path(report_dir, entry_progress_path)
    else:
        progress_path = None

    state["recommend_next_stage"] = _make_recommend_next_stage(
        action=action,
        stage_id=stage_id,
        source_stage_id=source_stage_id,
        reason=reason,
        progress_path=progress_path,
    )
    return state



def recommendation_for_state(report_dir: Path, state: dict) -> dict:
    return normalize_state(report_dir, state)["recommend_next_stage"]



def new_state(sample_sha256: str, input_path: str, report_dir: Path) -> dict:
    now = _now_utc()
    stages = {}
    for stage_id, meta in STAGE_TABLE.items():
        stages[stage_id] = {
            "skill": meta["skill"],
            "status": STATUS_PENDING,
            "output_path": None,
            "progress_path": None,
            "updated_at": None,
        }
    state = {
        "schema_version": SCHEMA_VERSION,
        "timestamp_utc": now,
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
    return state



def load_state(report_dir: Path) -> dict | None:
    path = state_path_for(report_dir)
    if not path.exists():
        return None
    state = json.loads(path.read_text(encoding="utf-8"))
    return normalize_state(report_dir, state)



def save_state(report_dir: Path, state: dict) -> Path:
    path = state_path_for(report_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = normalize_state(report_dir, state)
    path.write_text(json.dumps(normalized, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path



def ensure_state(report_dir: Path, sample_sha256: str, input_path: str) -> dict:
    """Load STATE.json if present, otherwise create and persist a fresh one."""
    state = load_state(report_dir)
    if state is not None:
        return state
    state = new_state(sample_sha256, input_path, report_dir)
    save_state(report_dir, state)
    return state



def default_output_path(report_dir: Path, stage_id: str) -> str | None:
    _validate_stage_id(stage_id)
    filename = STAGE_TABLE[stage_id]["output"]
    return str(report_dir / filename) if filename else None



def default_progress_path(report_dir: Path, stage_id: str) -> str:
    _validate_stage_id(stage_id)
    return str(report_dir / "_state" / f"{stage_id}.progress.md")



def resolve_recorded_path(report_dir: Path, p: str) -> str:
    """Normalize a recorded STATE.json path to an absolute, cwd-independent one.

    Absolute paths pass through unchanged. Relative paths are resolved against
    the report directory, so a value stored in STATE.json never depends on the
    process's current working directory (validation and resume then work from
    any cwd). Skills should prefer building paths from ``$REPORT_DIR``.
    """
    path = Path(p).expanduser()
    if not path.is_absolute():
        path = report_dir / path
    return str(path)



def checkpoint(
    report_dir: Path,
    stage_id: str,
    progress_path: str,
    recommend_reason: str | None = None,
) -> dict:
    """Mark a stage 'running': it stopped at >= 80% context usage and wrote a progress file."""
    _validate_stage_id(stage_id)
    state = load_state(report_dir)
    if state is None:
        raise SystemExit(f"STATE.json not found in {report_dir}; call ensure/init first")
    if not progress_path:
        raise SystemExit("checkpoint requires a non-empty --progress-path")
    # Persist absolute paths only, so STATE.json stays cwd-independent.
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
    report_dir: Path,
    stage_id: str,
    output_path: str,
    recommend_reason: str | None = None,
) -> dict:
    """Mark a stage 'completed': final artifact written, validated, no follow-up problem left."""
    _validate_stage_id(stage_id)
    state = load_state(report_dir)
    if state is None:
        raise SystemExit(f"STATE.json not found in {report_dir}; call ensure/init first")
    if not output_path:
        raise SystemExit("complete requires a non-empty --output-path")
    # Persist absolute paths only, so STATE.json stays cwd-independent.
    output_path = resolve_recorded_path(report_dir, output_path)
    now = _now_utc()
    entry = state["stages"][stage_id]
    entry["status"] = STATUS_COMPLETED
    entry["output_path"] = output_path
    entry["updated_at"] = now
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



def fail(report_dir: Path, stage_id: str, message: str) -> dict:
    """Record an explicit failure. Does not change stage status; the launcher decides
    whether to retry or stop based on this and the stage's own last-known status."""
    _validate_stage_id(stage_id)
    state = load_state(report_dir)
    if state is None:
        raise SystemExit(f"STATE.json not found in {report_dir}; call ensure/init first")
    now = _now_utc()
    state["last_error"] = f"[{stage_id}] {message}"
    state["current_stage_id"] = stage_id
    state["timestamp_utc"] = now
    state["recommend_next_stage"] = _make_recommend_next_stage(
        action=RECOMMEND_ACTION_RETRY_STAGE,
        stage_id=stage_id,
        source_stage_id=stage_id,
        reason=f"Last attempt failed for {stage_id}: {message}",
        progress_path=None,
    )
    save_state(report_dir, state)
    return state



def main() -> int:
    parser = argparse.ArgumentParser(description="HyperAgent pipeline STATE.json helper")
    parser.add_argument("--report-dir", required=True, help="reports/<sha256> directory")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Create STATE.json if it does not already exist")
    p_init.add_argument("--sample-sha256", required=True)
    p_init.add_argument("--input-path", required=True)

    p_read = sub.add_parser("read", help="Print STATE.json, or a single stage entry with --stage-id")
    p_read.add_argument("--stage-id", default=None)

    p_ckpt = sub.add_parser("checkpoint", help="Mark a stage 'running' with a progress file")
    p_ckpt.add_argument("--stage-id", required=True)
    p_ckpt.add_argument("--progress-path", required=True)
    p_ckpt.add_argument(
        "--recommend-reason",
        default=None,
        help="Optional short explanation stored in top-level recommend_next_stage.reason",
    )

    p_complete = sub.add_parser("complete", help="Mark a stage 'completed' with its final artifact")
    p_complete.add_argument("--stage-id", required=True)
    p_complete.add_argument("--output-path", required=True)
    p_complete.add_argument(
        "--recommend-reason",
        default=None,
        help="Optional short explanation stored in top-level recommend_next_stage.reason",
    )

    p_fail = sub.add_parser("fail", help="Record a pipeline-level error against a stage")
    p_fail.add_argument("--stage-id", required=True)
    p_fail.add_argument("--message", required=True)

    args = parser.parse_args()
    report_dir = Path(args.report_dir).expanduser().resolve()

    if args.command == "init":
        state = ensure_state(report_dir, args.sample_sha256, args.input_path)
    elif args.command == "read":
        state = load_state(report_dir)
        if state is None:
            print(f"No STATE.json in {report_dir}", file=sys.stderr)
            return 1
        if args.stage_id:
            _validate_stage_id(args.stage_id)
            print(json.dumps(state["stages"][args.stage_id], indent=2, ensure_ascii=False))
            return 0
    elif args.command == "checkpoint":
        state = checkpoint(
            report_dir,
            args.stage_id,
            args.progress_path,
            recommend_reason=args.recommend_reason,
        )
    elif args.command == "complete":
        state = complete(
            report_dir,
            args.stage_id,
            args.output_path,
            recommend_reason=args.recommend_reason,
        )
    elif args.command == "fail":
        state = fail(report_dir, args.stage_id, args.message)
    else:  # pragma: no cover - argparse enforces choices
        parser.error("unknown command")
        return 2

    print(json.dumps(state, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
