from __future__ import annotations

import asyncio
import contextlib
import os
from typing import Any

from fastapi import HTTPException

from modules.api_state import (
    RUNS,
    RUN_WORKERS,
    TASK_SESSIONS,
    _combined_listener,
    _create_run_record,
    _derive_run_status,
    _ensure_task_output_record,
    _finalize_root_task,
    _harvest_logger_task_outputs,
    _merge_task_output,
    _root_task_output_payload,
    _update_task_session,
    _utc_now,
)
from core.pipeline_logger import PipelineLogger
from core.result_models import TaskStatus, TaskTerminalState
from core.task_runtime import kill_run_processes, list_run_processes


def _run_processes_snapshot(run_id: str) -> dict[str, Any]:
    record = RUNS.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return {
        "run_id": run_id,
        "status": _derive_run_status(record),
        "processes": list_run_processes(run_id),
    }


async def _stop_run(run_id: str) -> dict[str, Any]:
    record = RUNS.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    status = _derive_run_status(record)
    if status in {"completed", "failed", "cancelled"}:
        return {
            "run_id": run_id,
            "status": status,
            "processes": list_run_processes(run_id),
        }

    worker = RUN_WORKERS.get(run_id)
    if worker and not worker.done():
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker
    RUN_WORKERS.pop(run_id, None)

    processes = kill_run_processes(run_id, reason="Run cancelled by user")
    record["status"] = "cancelled"
    record["error"] = "Run cancelled by user"
    record["finished_at"] = record.get("finished_at") or _utc_now()
    _finalize_root_task(
        run_id,
        terminal_state=TaskTerminalState.CANCELLED,
        summary="Run cancelled by user",
    )
    finalized_root = TASK_SESSIONS.get(record["root_task_id"])
    if finalized_root is not None:
        _merge_task_output(
            record["root_task_id"],
            {
                "status": finalized_root.get("status"),
                "terminal_state": finalized_root.get("terminal_state"),
                "summary": finalized_root.get("summary"),
                "error": record.get("error"),
            },
        )
    return {
        "run_id": run_id,
        "status": "cancelled",
        "processes": processes,
    }


async def _execute_run(
    orchestrator,
    *,
    analysis_target: str,
    run_id: str,
    source: str,
    file_name: str | None = None,
    cleanup_path: str | None = None,
) -> dict[str, Any]:
    record = _create_run_record(run_id=run_id, source=source, file_name=file_name)
    pipeline_logger = PipelineLogger(
        run_id,
        task_id=record["root_task_id"],
        session_id=record["root_session_id"],
        executor_kind="local",
    )
    pipeline_logger.subscribe(_combined_listener(run_id))
    _ensure_task_output_record(
        task_id=record["root_task_id"],
        run_id=run_id,
        session_id=record["root_session_id"],
        stage_key="request",
        title="Run request",
        executor_kind="local",
    )
    root_task = _update_task_session(
        record["root_task_id"],
        status=TaskStatus.PROCESSING.value,
        started_at=TASK_SESSIONS.get(record["root_task_id"], {}).get("started_at") or _utc_now(),
        summary="Analysis queued",
    )
    if root_task is not None:
        _merge_task_output(
            record["root_task_id"],
            {
                "status": root_task.get("status"),
                "terminal_state": root_task.get("terminal_state"),
                "summary": root_task.get("summary"),
            },
        )

    try:
        result = await orchestrator.analyze(analysis_target, run_id=run_id, pipeline_logger=pipeline_logger)
        record["result"] = result
        record["pipeline_log"] = result.get("pipeline_log", record["pipeline_log"])
        record["status"] = "completed"
        _harvest_logger_task_outputs(run_id, pipeline_logger)
        _merge_task_output(record["root_task_id"], _root_task_output_payload(result))
        return result
    except asyncio.CancelledError:
        record["status"] = "cancelled"
        record["error"] = "Run cancelled by user"
        _harvest_logger_task_outputs(run_id, pipeline_logger)
        _merge_task_output(record["root_task_id"], _root_task_output_payload({}, "Run cancelled by user"))
        raise
    except Exception as exc:
        record["status"] = "failed"
        record["error"] = str(exc)
        _harvest_logger_task_outputs(run_id, pipeline_logger)
        _merge_task_output(record["root_task_id"], _root_task_output_payload({}, str(exc)))
        raise
    finally:
        record["finished_at"] = _utc_now()
        terminal_state = TaskTerminalState.SUCCESS
        if record["status"] == "failed":
            terminal_state = TaskTerminalState.FAILED
        elif record["status"] == "cancelled":
            terminal_state = TaskTerminalState.CANCELLED
        _finalize_root_task(
            run_id,
            terminal_state=terminal_state,
            summary=record["error"] or ("Run cancelled by user" if record["status"] == "cancelled" else "Analysis completed"),
        )
        finalized_root = TASK_SESSIONS.get(record["root_task_id"])
        if finalized_root is not None:
            _merge_task_output(
                record["root_task_id"],
                {
                    "status": finalized_root.get("status"),
                    "terminal_state": finalized_root.get("terminal_state"),
                    "summary": finalized_root.get("summary"),
                    "error": record.get("error"),
                },
            )
        RUN_WORKERS.pop(run_id, None)
        if cleanup_path and os.path.exists(cleanup_path):
            try:
                os.remove(cleanup_path)
            except OSError:
                pass


def _queue_run_task(
    orchestrator,
    *,
    analysis_target: str,
    run_id: str,
    source: str,
    file_name: str | None = None,
    cleanup_path: str | None = None,
) -> None:
    worker = asyncio.create_task(
        _execute_run(
            orchestrator,
            analysis_target=analysis_target,
            run_id=run_id,
            source=source,
            file_name=file_name,
            cleanup_path=cleanup_path,
        )
    )
    RUN_WORKERS[run_id] = worker
