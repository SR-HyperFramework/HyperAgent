"""STATE.json read/write helper for the HyperAgent v4 pipeline.

Owns the canonical stage-id table and is the only supported way to read or
mutate ``<report_dir>/STATE.json``. The launcher (``engine/launcher.py``)
calls this module instead of hand-editing the JSON, so status semantics stay
consistent pipeline-wide:

- ``pending``:   stage has not started yet.
- ``running``:   stage stopped to checkpoint (context threshold reached) and
                 a progress file was written; it is NOT finished and must be
                 resumed from ``progress_path``.
- ``completed``: the stage's final artifact was written and validated.
- ``failed``:    the last attempt for this stage raised an error.

Adapted from the v3 reference implementation at
``skill/backup/hyperagent-malware-analyze/v3/_hyperagent-common/scripts/pipeline_state.py``.
v3 exposed a rich ``recommend_next_stage`` hint plus a standalone CLI; v4 only
needs the plain read/write API consumed by ``engine/launcher.py``, so that
mechanism and the CLI were dropped. Never depends on ``cwd`` — every path is
taken from arguments or resolved against ``report_dir``.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "1.0"

# Canonical stage-id table: stage_id -> default output filename (None for stages with no single artifact).
STAGE_TABLE: dict[str, str | None] = {
    "01-prepare-env": "01-prepare-env.json",
    "02-static-pass1": "02-static-pass1.json",
    "03-unpack": "03-unpack.json",
    "04-static-pass2": "04-static-pass2.json",
    "05-dynamic": "05-dynamic.json",
    "06-intel": "06-intel.json",
    "07-deepdive": "07-deepdive.json",
    "08-report": "08-report.md",
    "09-summary": "09-summary.json",
}

STAGE_IDS: tuple[str, ...] = tuple(STAGE_TABLE.keys())

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate_stage_id(stage_id: str) -> None:
    if stage_id not in STAGE_TABLE:
        raise ValueError(f"Unknown stage id: {stage_id!r}. Valid: {', '.join(STAGE_IDS)}")


def state_path_for(report_dir: Path) -> Path:
    return report_dir / "STATE.json"


def _new_state(sample_sha256: str, input_path: str) -> dict:
    now = _now_utc()
    stages = {
        stage_id: {
            "status": STATUS_PENDING,
            "output_path": None,
            "progress_path": None,
            "error": None,
            "updated_at": None,
        }
        for stage_id in STAGE_IDS
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "timestamp_utc": now,
        "sample_sha256": sample_sha256,
        "input_path": input_path,
        "stages": stages,
    }


def _save_state(report_dir: Path, state: dict) -> Path:
    """Write STATE.json atomically (tmp file + os.replace) to avoid torn writes."""
    path = state_path_for(report_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp_path, path)
    return path


def load_state(report_dir: Path) -> dict:
    """Load STATE.json. Raises FileNotFoundError if it does not exist yet."""
    path = state_path_for(report_dir)
    if not path.exists():
        raise FileNotFoundError(f"STATE.json not found in {report_dir}; call ensure_state first")
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_state(report_dir: Path, sample_sha256: str, input_path: str) -> None:
    """Create STATE.json if missing. Idempotent: an existing file is left untouched."""
    path = state_path_for(report_dir)
    if path.exists():
        return
    state = _new_state(sample_sha256, input_path)
    _save_state(report_dir, state)


def default_output_path(report_dir: Path, stage_id: str) -> str | None:
    _validate_stage_id(stage_id)
    filename = STAGE_TABLE[stage_id]
    return str(report_dir / filename) if filename else None


def resolve_recorded_path(report_dir: Path, output_path: str) -> str:
    """Normalize a recorded STATE.json path to an absolute, cwd-independent one.

    Absolute paths pass through unchanged. Relative paths are resolved against
    ``report_dir`` so a value stored in STATE.json never depends on the
    process's current working directory.
    """
    path = Path(output_path).expanduser()
    if not path.is_absolute():
        path = report_dir / path
    return str(path)


def checkpoint(report_dir: Path, stage_id: str, progress_path: str, recommend_reason: str = "") -> None:
    """Mark a stage 'running': it checkpointed and wrote a progress file."""
    _validate_stage_id(stage_id)
    state = load_state(report_dir)
    progress_path = resolve_recorded_path(report_dir, progress_path)
    entry = state["stages"][stage_id]
    entry["status"] = STATUS_RUNNING
    entry["progress_path"] = progress_path
    entry["updated_at"] = _now_utc()
    if recommend_reason:
        entry["recommend_reason"] = recommend_reason
    state["timestamp_utc"] = _now_utc()
    _save_state(report_dir, state)


def complete(report_dir: Path, stage_id: str, output_path: str, recommend_reason: str = "") -> None:
    """Mark a stage 'completed': final artifact written and validated."""
    _validate_stage_id(stage_id)
    state = load_state(report_dir)
    output_path = resolve_recorded_path(report_dir, output_path)
    entry = state["stages"][stage_id]
    entry["status"] = STATUS_COMPLETED
    entry["output_path"] = output_path
    entry["error"] = None
    entry["updated_at"] = _now_utc()
    if recommend_reason:
        entry["recommend_reason"] = recommend_reason
    state["timestamp_utc"] = _now_utc()
    _save_state(report_dir, state)


def fail(report_dir: Path, stage_id: str, reason: str) -> None:
    """Record a stage as 'failed' with an error reason."""
    _validate_stage_id(stage_id)
    state = load_state(report_dir)
    entry = state["stages"][stage_id]
    entry["status"] = STATUS_FAILED
    entry["error"] = reason
    entry["updated_at"] = _now_utc()
    state["timestamp_utc"] = _now_utc()
    _save_state(report_dir, state)
