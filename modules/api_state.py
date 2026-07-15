from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from core.pipeline_logger import PipelineLogger
from core.result_models import TaskSession, TaskStatus, TaskTerminalState

UPLOAD_DIR = Path("uploads")

RUNS: dict[str, dict[str, Any]] = {}
TASK_SESSIONS: dict[str, dict[str, Any]] = {}
RUN_TASK_INDEX: dict[str, list[str]] = {}
TASK_OUTPUTS: dict[str, dict[str, Any]] = {}
RUN_WORKERS: dict[str, Any] = {}

TASK_STAGE_TITLES = {
    "request": "Run request",
    "response": "Final response",
}

TERMINAL_STATE_BY_STATUS = {
    "completed": TaskTerminalState.SUCCESS,
    "failed": TaskTerminalState.FAILED,
    "skipped": TaskTerminalState.SKIPPED,
    "cancelled": TaskTerminalState.CANCELLED,
}

_UNSET = object()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _task_title(stage: str, message: str) -> str:
    title = TASK_STAGE_TITLES.get(stage)
    if title:
        return title
    if message:
        return message
    return stage.replace("_", " ").replace(".", " ").title()


def _serialize_task_session(task: TaskSession) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "run_id": task.run_id,
        "session_id": task.session_id,
        "parent_task_id": task.parent_task_id,
        "stage_key": task.stage_key,
        "title": task.title,
        "status": task.status.value,
        "terminal_state": task.terminal_state.value if task.terminal_state else None,
        "executor_kind": task.executor_kind,
        "artifact_id": task.artifact_id,
        "summary": task.summary,
        "created_at": task.created_at,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
        "metadata": dict(task.metadata),
    }


def _ensure_task_output_record(
    *,
    task_id: str,
    run_id: str,
    session_id: str | None = None,
    parent_task_id: str | None = None,
    stage_key: str | None = None,
    title: str | None = None,
    executor_kind: str | None = None,
) -> dict[str, Any]:
    record = TASK_OUTPUTS.get(task_id)
    if not isinstance(record, dict):
        record = {"task_id": task_id, "run_id": run_id, "events": []}
        TASK_OUTPUTS[task_id] = record
    if run_id:
        record["run_id"] = run_id
    if session_id is not None:
        record["session_id"] = session_id
    if parent_task_id is not None:
        record["parent_task_id"] = parent_task_id
    if stage_key is not None:
        record["stage_key"] = stage_key
    if title is not None:
        record["title"] = title
    if executor_kind is not None:
        record["executor_kind"] = executor_kind
    events = record.get("events")
    if not isinstance(events, list):
        record["events"] = []
    return record


def _store_task_session(task: TaskSession) -> dict[str, Any]:
    snapshot = _serialize_task_session(task)
    TASK_SESSIONS[task.task_id] = snapshot
    task_ids = RUN_TASK_INDEX.setdefault(task.run_id, [])
    if task.task_id not in task_ids:
        task_ids.append(task.task_id)
    _ensure_task_output_record(
        task_id=task.task_id,
        run_id=task.run_id,
        session_id=task.session_id,
        parent_task_id=task.parent_task_id,
        stage_key=task.stage_key,
        title=task.title,
        executor_kind=task.executor_kind,
    )
    return snapshot


def _merge_task_output(task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    task = TASK_SESSIONS.get(task_id)
    run_id = task.get("run_id") if isinstance(task, dict) else None
    record = _ensure_task_output_record(task_id=task_id, run_id=run_id or "")
    for key, value in payload.items():
        if key == "events" and isinstance(value, list):
            record["events"] = list(value)
        elif value is not None:
            record[key] = value
    return record


def _serialize_task_output(task_id: str) -> dict[str, Any] | None:
    record = TASK_OUTPUTS.get(task_id)
    if not isinstance(record, dict):
        return None
    return {
        "task_id": record.get("task_id"),
        "run_id": record.get("run_id"),
        "session_id": record.get("session_id"),
        "parent_task_id": record.get("parent_task_id"),
        "stage_key": record.get("stage_key"),
        "title": record.get("title"),
        "executor_kind": record.get("executor_kind"),
        "status": record.get("status"),
        "terminal_state": record.get("terminal_state"),
        "summary": record.get("summary"),
        "error": record.get("error"),
        "output_kind": record.get("output_kind"),
        "result": record.get("result"),
        "events": list(record.get("events") or []),
    }


def _run_task_output_snapshot(run_id: str, task_id: str) -> dict[str, Any]:
    record = RUNS.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    if task_id not in RUN_TASK_INDEX.get(run_id, []):
        raise HTTPException(status_code=404, detail=f"Task not found for run: {task_id}")
    task = TASK_SESSIONS.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    return {
        "run_id": run_id,
        "task": dict(task),
        "output": _serialize_task_output(task_id),
    }


def _task_action_label(task: dict[str, Any]) -> str:
    terminal_state = task.get("terminal_state")
    if isinstance(terminal_state, str) and terminal_state:
        return terminal_state
    status = task.get("status")
    return status if isinstance(status, str) and status else "idle"


def _task_detail_header(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": task.get("task_id"),
        "run_id": task.get("run_id"),
        "session_id": task.get("session_id"),
        "parent_task_id": task.get("parent_task_id"),
        "stage_key": task.get("stage_key"),
        "title": task.get("title"),
        "executor_kind": task.get("executor_kind"),
        "status": task.get("status"),
        "terminal_state": task.get("terminal_state"),
        "summary": task.get("summary"),
        "error": None,
        "output_kind": None,
        "result": None,
        "events": [],
    }


def _sync_task_output_from_event(task_id: str, event: dict[str, Any], task: dict[str, Any]) -> None:
    record = _ensure_task_output_record(
        task_id=task_id,
        run_id=task["run_id"],
        session_id=task.get("session_id"),
        parent_task_id=task.get("parent_task_id"),
        stage_key=task.get("stage_key"),
        title=task.get("title"),
        executor_kind=task.get("executor_kind"),
    )
    record["status"] = task.get("status")
    record["terminal_state"] = task.get("terminal_state")
    record["summary"] = task.get("summary")
    if isinstance(task.get("artifact_id"), str):
        record["artifact_id"] = task["artifact_id"]
    if event not in record["events"]:
        record["events"].append(dict(event))
    if task.get("terminal_state") == TaskTerminalState.FAILED.value:
        record["error"] = event.get("message")


def _apply_task_output_snapshot(run_id: str, task_id: str, payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        return
    task = TASK_SESSIONS.get(task_id)
    if task is None:
        return
    merged = _merge_task_output(task_id, payload)
    merged["run_id"] = run_id
    merged.setdefault("task_id", task_id)
    merged.setdefault("session_id", task.get("session_id"))
    merged.setdefault("parent_task_id", task.get("parent_task_id"))
    merged.setdefault("stage_key", task.get("stage_key"))
    merged.setdefault("title", task.get("title"))
    merged.setdefault("executor_kind", task.get("executor_kind"))
    merged.setdefault("status", task.get("status"))
    merged.setdefault("terminal_state", task.get("terminal_state"))
    merged.setdefault("summary", task.get("summary"))
    if task.get("artifact_id") is not None:
        merged.setdefault("artifact_id", task.get("artifact_id"))
    events = merged.get("events")
    if not isinstance(events, list):
        merged["events"] = []
    if task.get("terminal_state") == TaskTerminalState.FAILED.value and task.get("summary"):
        merged.setdefault("error", task.get("summary"))


def _harvest_logger_task_outputs(run_id: str, pipeline_logger: PipelineLogger) -> None:
    for task_id, payload in pipeline_logger.task_outputs_snapshot().items():
        _apply_task_output_snapshot(run_id, task_id, payload)


def _task_output_listener(run_id: str):
    def handle(task_id: str, payload: dict[str, Any]) -> None:
        _apply_task_output_snapshot(run_id, task_id, payload)

    return handle


def _root_task_output_payload(result: dict[str, Any], error: str | None = None) -> dict[str, Any]:
    payload = {
        "output_kind": "run_result",
        "result": result,
    }
    if error:
        payload["error"] = error
    return payload


def _create_task_session(
    *,
    run_id: str,
    stage_key: str,
    title: str,
    parent_task_id: str | None = None,
    artifact_id: str | None = None,
    executor_kind: str = "local",
    task_id: str | None = None,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task = TaskSession(
        run_id=run_id,
        stage_key=stage_key,
        title=title,
        task_id=task_id or uuid.uuid4().hex,
        parent_task_id=parent_task_id,
        artifact_id=artifact_id,
        executor_kind=executor_kind,
        session_id=session_id or uuid.uuid4().hex,
        created_at=_utc_now(),
        metadata=dict(metadata or {}),
    )
    return _store_task_session(task)


def _update_task_session(task_id: str, **changes: Any) -> dict[str, Any] | None:
    task = TASK_SESSIONS.get(task_id)
    if task is None:
        return None
    for key, value in changes.items():
        if value is not _UNSET:
            task[key] = value
    return task


def _list_run_tasks(run_id: str) -> list[dict[str, Any]]:
    task_ids = RUN_TASK_INDEX.get(run_id, [])
    return [dict(TASK_SESSIONS[task_id]) for task_id in task_ids if task_id in TASK_SESSIONS]


def _derive_run_status(record: dict[str, Any]) -> str:
    tasks = _list_run_tasks(record["run_id"])
    if record.get("status") == "cancelled" or any(task["terminal_state"] == TaskTerminalState.CANCELLED.value for task in tasks):
        return "cancelled"
    if any(task["terminal_state"] == TaskTerminalState.FAILED.value for task in tasks):
        return "failed"
    if any(task["status"] == TaskStatus.PROCESSING.value for task in tasks):
        return "running"
    if tasks and all(task["status"] == TaskStatus.COMPLETED.value for task in tasks):
        return "completed"
    if any(task["status"] != TaskStatus.PENDING.value for task in tasks):
        return "running"
    return record["status"]


def _create_run_record(*, run_id: str, source: str, file_name: str | None = None) -> dict[str, Any]:
    existing = RUNS.get(run_id)
    if existing is not None:
        if source:
            existing["source"] = source
        if file_name:
            existing["file_name"] = file_name
        return existing

    root_task = _create_task_session(
        run_id=run_id,
        stage_key="request",
        title="Run request",
        executor_kind="local",
        metadata={"source": source, "file_name": file_name},
    )
    record = {
        "run_id": run_id,
        "status": "queued",
        "source": source,
        "file_name": file_name,
        "started_at": root_task["created_at"],
        "finished_at": None,
        "pipeline_log": [],
        "result": None,
        "error": None,
        "root_task_id": root_task["task_id"],
        "root_session_id": root_task["session_id"],
    }
    RUNS[run_id] = record
    return record


def _sync_task_from_event(*, run_id: str, event: dict[str, Any]) -> None:
    record = RUNS.get(run_id)
    if record is None:
        return

    data = event.get("data") or {}
    task_id = data.get("task_id") if isinstance(data, dict) else None
    if not isinstance(task_id, str) or not task_id:
        task_id = record.get("root_task_id")
    if not isinstance(task_id, str) or not task_id:
        return

    session_id = data.get("session_id") if isinstance(data, dict) and isinstance(data.get("session_id"), str) else record.get("root_session_id")
    parent_task_id = data.get("parent_task_id") if isinstance(data, dict) and isinstance(data.get("parent_task_id"), str) else None
    executor_kind = data.get("executor_kind") if isinstance(data, dict) and isinstance(data.get("executor_kind"), str) else "local"
    artifact_id = data.get("artifact_id") if isinstance(data, dict) and isinstance(data.get("artifact_id"), str) else None
    metadata = dict(data) if isinstance(data, dict) else {}

    task = TASK_SESSIONS.get(task_id)
    if task is None:
        task = _create_task_session(
            run_id=run_id,
            stage_key=event.get("stage") or "task",
            title=_task_title(event.get("stage") or "task", event.get("message") or ""),
            parent_task_id=parent_task_id,
            artifact_id=artifact_id,
            executor_kind=executor_kind,
            task_id=task_id,
            session_id=session_id,
            metadata=metadata,
        )
    else:
        task["metadata"] = metadata
        if session_id:
            task["session_id"] = session_id
        if parent_task_id:
            task["parent_task_id"] = parent_task_id
        if artifact_id:
            task["artifact_id"] = artifact_id
        if executor_kind:
            task["executor_kind"] = executor_kind
        if event.get("stage"):
            task["stage_key"] = event["stage"]
        if event.get("message") and not task.get("summary"):
            task["title"] = _task_title(task["stage_key"], event["message"])
        _ensure_task_output_record(
            task_id=task_id,
            run_id=run_id,
            session_id=task.get("session_id"),
            parent_task_id=task.get("parent_task_id"),
            stage_key=task.get("stage_key"),
            title=task.get("title"),
            executor_kind=task.get("executor_kind"),
        )

    state = event.get("state")
    summary = event.get("message")
    changes: dict[str, Any] = {
        "summary": summary,
        "metadata": metadata,
    }
    if state == "started":
        changes["status"] = TaskStatus.PROCESSING.value
        changes["started_at"] = task.get("started_at") or event.get("timestamp") or _utc_now()
        changes["terminal_state"] = None
        changes["finished_at"] = None
    elif state in TERMINAL_STATE_BY_STATUS:
        changes["status"] = TaskStatus.COMPLETED.value
        changes["terminal_state"] = TERMINAL_STATE_BY_STATUS[state].value
        changes["started_at"] = task.get("started_at") or task.get("created_at")
        changes["finished_at"] = event.get("timestamp") or _utc_now()
    else:
        changes["terminal_state"] = _UNSET
        changes["finished_at"] = _UNSET
        changes["started_at"] = _UNSET
    updated_task = _update_task_session(task_id, **changes)
    if updated_task is not None:
        _sync_task_output_from_event(task_id, event, updated_task)


def _finalize_root_task(run_id: str, *, terminal_state: TaskTerminalState, summary: str | None = None) -> None:
    record = RUNS.get(run_id)
    if record is None:
        return
    _update_task_session(
        record["root_task_id"],
        status=TaskStatus.COMPLETED.value,
        terminal_state=terminal_state.value,
        started_at=TASK_SESSIONS.get(record["root_task_id"], {}).get("started_at") or record["started_at"],
        finished_at=record.get("finished_at") or _utc_now(),
        summary=summary or TASK_SESSIONS.get(record["root_task_id"], {}).get("summary") or "Run finished",
    )


def _task_listener(run_id: str):
    def handle(event: dict[str, Any]) -> None:
        _sync_task_from_event(run_id=run_id, event=event)

    return handle


def _pipeline_listener(run_id: str):
    def handle(event: dict[str, Any]) -> None:
        record = RUNS.get(run_id)
        if record is None:
            return
        record["pipeline_log"] = [*record["pipeline_log"], event]
        state = event.get("state")
        if state == "started":
            record["status"] = "running"
        elif state == "failed":
            record["status"] = "failed"
            record["error"] = event.get("message")
        elif state == "completed":
            record["status"] = "running"

    return handle


class _CompositeListener:
    def __init__(self, *listeners):
        self._listeners = listeners

    def __call__(self, event: dict[str, Any]) -> None:
        for listener in self._listeners:
            listener(event)


def _combined_listener(run_id: str):
    return _CompositeListener(_pipeline_listener(run_id), _task_listener(run_id))


def _run_snapshot(run_id: str) -> dict[str, Any]:
    record = RUNS.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return {
        "run_id": run_id,
        "status": _derive_run_status(record),
        "source": record["source"],
        "file_name": record["file_name"],
        "started_at": record["started_at"],
        "finished_at": record["finished_at"],
        "pipeline_log": record["pipeline_log"],
        "result": record["result"],
        "error": record["error"],
    }


def _run_tasks_snapshot(run_id: str) -> dict[str, Any]:
    record = RUNS.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return {
        "run_id": run_id,
        "status": _derive_run_status(record),
        "tasks": _list_run_tasks(run_id),
    }
