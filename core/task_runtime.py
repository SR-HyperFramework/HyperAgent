from __future__ import annotations

import asyncio
import contextlib
import contextvars
import os
import subprocess
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from core.pipeline_logger import PipelineLogger
from core.result_models import TaskSession


CLAUDE_EXECUTOR_STAGE_KEYS = frozenset(
    {
        "native_agent.claude",
        "script_agent.claude",
        "dotnet_agent.claude",
        "claude_runner",
    }
)

_PROCESS_SCOPE: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "hyperagent_process_scope",
    default=None,
)
_PROCESS_LOCK = threading.RLock()
_PROCESS_RECORDS: dict[str, dict[str, Any]] = {}
_RUN_PROCESS_INDEX: dict[str, list[str]] = {}
_ACTIVE_PROCESS_BY_PID: dict[int, str] = {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def executor_kind_for_stage(stage_key: str) -> str:
    if stage_key in CLAUDE_EXECUTOR_STAGE_KEYS:
        return "claude"
    return "local"


class TaskScopedPipelineLogger:
    def __init__(self, pipeline_logger: PipelineLogger | "TaskScopedPipelineLogger", task: TaskSession):
        self._pipeline_logger = getattr(pipeline_logger, "root_logger", pipeline_logger)
        self._task = task
        self.run_id = self._pipeline_logger.run_id

    @property
    def root_logger(self) -> PipelineLogger:
        return self._pipeline_logger

    @property
    def task(self) -> TaskSession:
        return self._task

    def task_snapshot(self) -> dict[str, Any]:
        snapshot: dict[str, Any] = {
            "task_id": self._task.task_id,
            "session_id": self._task.session_id,
            "executor_kind": self._task.executor_kind,
        }
        if self._task.parent_task_id is not None:
            snapshot["parent_task_id"] = self._task.parent_task_id
        return snapshot

    def log(self, stage: str, state: str, message: str, **data: Any) -> dict[str, Any]:
        return self._pipeline_logger.log(
            stage,
            state,
            message,
            **self.task_snapshot(),
            **data,
        )

    def record_output(self, payload: Any, *, output_kind: str | None = None, merge: bool = False) -> dict[str, Any]:
        return self._pipeline_logger.record_task_output(
            payload,
            task_id=self._task.task_id,
            output_kind=output_kind,
            merge=merge,
        )

    def seed_output(self, **fields: Any) -> None:
        snapshot = self.task_snapshot()
        snapshot.pop("task_id", None)
        self._pipeline_logger.seed_task_output(task_id=self._task.task_id, **snapshot, **fields)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._pipeline_logger, name)


@dataclass
class TrackedCompletedProcess:
    args: list[str]
    returncode: int
    stdout: bytes
    stderr: bytes


StreamCallback = Callable[[bytes], None]


def create_child_task_scope(
    pipeline_logger: PipelineLogger | TaskScopedPipelineLogger,
    *,
    stage_key: str,
    title: str,
    parent_task_id: str | None = None,
    executor_kind: str | None = None,
    artifact_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[TaskSession, TaskScopedPipelineLogger]:
    snapshot = pipeline_logger.task_snapshot() if hasattr(pipeline_logger, "task_snapshot") else {}
    default_parent_task_id = snapshot.get("task_id") if isinstance(snapshot.get("task_id"), str) else None
    task = TaskSession(
        run_id=pipeline_logger.run_id,
        stage_key=stage_key,
        title=title,
        parent_task_id=parent_task_id if parent_task_id is not None else default_parent_task_id,
        artifact_id=artifact_id,
        executor_kind=executor_kind or executor_kind_for_stage(stage_key),
        metadata=dict(metadata or {}),
    )
    return task, TaskScopedPipelineLogger(pipeline_logger, task)


def _scope_from_logger(pipeline_logger: PipelineLogger | TaskScopedPipelineLogger | None) -> dict[str, Any]:
    if pipeline_logger is None:
        return {}
    scope: dict[str, Any] = {}
    run_id = getattr(pipeline_logger, "run_id", None)
    if isinstance(run_id, str) and run_id:
        scope["run_id"] = run_id
    if hasattr(pipeline_logger, "task_snapshot"):
        snapshot = pipeline_logger.task_snapshot()
        for key in ("task_id", "session_id", "parent_task_id", "executor_kind"):
            value = snapshot.get(key)
            if isinstance(value, str) and value:
                scope[key] = value
    task = getattr(pipeline_logger, "task", None)
    stage_key = getattr(task, "stage_key", None)
    title = getattr(task, "title", None)
    if isinstance(stage_key, str) and stage_key:
        scope["stage_key"] = stage_key
    if isinstance(title, str) and title:
        scope["title"] = title
    return scope


def current_process_scope() -> dict[str, Any]:
    scope = _PROCESS_SCOPE.get()
    if not isinstance(scope, dict):
        return {}
    return dict(scope)


@contextmanager
def bind_process_scope(
    *,
    pipeline_logger: PipelineLogger | TaskScopedPipelineLogger | None = None,
    run_id: str | None = None,
    task_id: str | None = None,
    session_id: str | None = None,
    parent_task_id: str | None = None,
    executor_kind: str | None = None,
    stage_key: str | None = None,
    title: str | None = None,
):
    scope = current_process_scope()
    scope.update(_scope_from_logger(pipeline_logger))
    explicit = {
        "run_id": run_id,
        "task_id": task_id,
        "session_id": session_id,
        "parent_task_id": parent_task_id,
        "executor_kind": executor_kind,
        "stage_key": stage_key,
        "title": title,
    }
    for key, value in explicit.items():
        if isinstance(value, str) and value:
            scope[key] = value
    token = _PROCESS_SCOPE.set(scope)
    try:
        yield dict(scope)
    finally:
        _PROCESS_SCOPE.reset(token)


def reset_process_runtime() -> None:
    with _PROCESS_LOCK:
        _PROCESS_RECORDS.clear()
        _RUN_PROCESS_INDEX.clear()
        _ACTIVE_PROCESS_BY_PID.clear()


def _command_text(command: list[str]) -> str:
    return " ".join(str(part) for part in command)


def _register_process(
    command: list[str],
    *,
    pid: int,
    cwd: str | None = None,
    pipeline_logger: PipelineLogger | TaskScopedPipelineLogger | None = None,
) -> str:
    scope = current_process_scope()
    scope.update(_scope_from_logger(pipeline_logger))
    run_id = scope.get("run_id") if isinstance(scope.get("run_id"), str) else None
    process_id = TaskSession(run_id=run_id or "", stage_key="process", title="process").task_id
    executable = os.path.basename(command[0]) if command else "process"
    record = {
        "process_id": process_id,
        "run_id": run_id,
        "task_id": scope.get("task_id"),
        "session_id": scope.get("session_id"),
        "parent_task_id": scope.get("parent_task_id"),
        "executor_kind": scope.get("executor_kind"),
        "stage_key": scope.get("stage_key"),
        "title": scope.get("title") or executable,
        "pid": pid,
        "command": list(command),
        "command_text": _command_text(command),
        "command_name": executable,
        "cwd": cwd,
        "status": "running",
        "started_at": _utc_now(),
        "finished_at": None,
        "return_code": None,
        "error": None,
    }
    with _PROCESS_LOCK:
        _PROCESS_RECORDS[process_id] = record
        if run_id:
            process_ids = _RUN_PROCESS_INDEX.setdefault(run_id, [])
            if process_id not in process_ids:
                process_ids.append(process_id)
        _ACTIVE_PROCESS_BY_PID[pid] = process_id
    return process_id


def _finalize_process(
    process_id: str,
    *,
    returncode: int | None = None,
    status: str | None = None,
    error: str | None = None,
) -> dict[str, Any] | None:
    with _PROCESS_LOCK:
        record = _PROCESS_RECORDS.get(process_id)
        if not isinstance(record, dict):
            return None
        current_status = record.get("status")
        if current_status == "cancelled" and status != "cancelled":
            if record.get("return_code") is None and returncode is not None:
                record["return_code"] = returncode
            if error and not record.get("error"):
                record["error"] = error
            return dict(record)
        if record.get("finished_at") and status != "cancelled":
            return dict(record)
        if status is None:
            if returncode is None or returncode == 0:
                status = "completed"
            else:
                status = "failed"
        record["status"] = status
        record["finished_at"] = record.get("finished_at") or _utc_now()
        if returncode is not None:
            record["return_code"] = returncode
        if error:
            record["error"] = error
        pid = record.get("pid")
        if isinstance(pid, int) and _ACTIVE_PROCESS_BY_PID.get(pid) == process_id:
            _ACTIVE_PROCESS_BY_PID.pop(pid, None)
        return dict(record)


def list_run_processes(run_id: str) -> list[dict[str, Any]]:
    with _PROCESS_LOCK:
        process_ids = list(_RUN_PROCESS_INDEX.get(run_id, []))
        records = [dict(_PROCESS_RECORDS[process_id]) for process_id in process_ids if process_id in _PROCESS_RECORDS]
    status_rank = {"running": 0, "failed": 1, "cancelled": 2, "completed": 3}
    return sorted(
        records,
        key=lambda record: (
            status_rank.get(str(record.get("status")), 9),
            str(record.get("started_at") or ""),
            str(record.get("title") or ""),
        ),
    )


def _terminate_process_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        return
    with contextlib.suppress(ProcessLookupError):
        import signal

        os.kill(pid, signal.SIGTERM)


def kill_run_processes(run_id: str, *, reason: str | None = None) -> list[dict[str, Any]]:
    active_records = [record for record in list_run_processes(run_id) if record.get("status") == "running"]
    for record in active_records:
        pid = record.get("pid")
        if isinstance(pid, int):
            _terminate_process_tree(pid)
        _finalize_process(
            record["process_id"],
            status="cancelled",
            error=reason,
        )
    return list_run_processes(run_id)


async def _read_stream(
    stream: asyncio.StreamReader | None,
    callback: StreamCallback | None = None,
) -> bytes:
    if stream is None:
        return b""
    chunks: list[bytes] = []
    while True:
        chunk = await stream.read(4096)
        if not chunk:
            break
        chunks.append(chunk)
        if callback is not None:
            callback(chunk)
    return b"".join(chunks)


async def run_tracked_process(
    *command: str,
    cwd: str | None = None,
    pipeline_logger: PipelineLogger | TaskScopedPipelineLogger | None = None,
    stdout_callback: StreamCallback | None = None,
    stderr_callback: StreamCallback | None = None,
) -> tuple[int, bytes | str, bytes | str]:
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    process_id = _register_process(list(command), pid=process.pid, cwd=cwd, pipeline_logger=pipeline_logger)
    stdout_task = asyncio.create_task(_read_stream(process.stdout, stdout_callback))
    stderr_task = asyncio.create_task(_read_stream(process.stderr, stderr_callback))
    try:
        returncode, stdout, stderr = await asyncio.gather(process.wait(), stdout_task, stderr_task)
    except asyncio.CancelledError:
        _terminate_process_tree(process.pid)
        stdout_task.cancel()
        stderr_task.cancel()
        with contextlib.suppress(Exception):
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        _finalize_process(process_id, returncode=process.returncode, status="cancelled", error="Process cancelled")
        raise
    except Exception as exc:
        if process.returncode is None:
            _terminate_process_tree(process.pid)
        stdout_task.cancel()
        stderr_task.cancel()
        with contextlib.suppress(Exception):
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        _finalize_process(process_id, returncode=process.returncode, status="failed", error=str(exc))
        raise
    _finalize_process(process_id, returncode=returncode)
    return returncode, stdout, stderr


def run_tracked_subprocess(
    command: list[str],
    *,
    cwd: str | None = None,
    pipeline_logger: PipelineLogger | TaskScopedPipelineLogger | None = None,
    stdout_callback: StreamCallback | None = None,
    stderr_callback: StreamCallback | None = None,
) -> TrackedCompletedProcess:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    process_id = _register_process(list(command), pid=process.pid, cwd=cwd, pipeline_logger=pipeline_logger)
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []

    def _pump(stream, chunks: list[bytes], callback: StreamCallback | None) -> None:
        if stream is None:
            return
        while True:
            chunk = stream.read(4096)
            if not chunk:
                break
            chunks.append(chunk)
            if callback is not None:
                callback(chunk)

    stdout_thread = threading.Thread(target=_pump, args=(process.stdout, stdout_chunks, stdout_callback), daemon=True)
    stderr_thread = threading.Thread(target=_pump, args=(process.stderr, stderr_chunks, stderr_callback), daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    try:
        returncode = process.wait()
        stdout_thread.join()
        stderr_thread.join()
    except BaseException as exc:
        _terminate_process_tree(process.pid)
        with contextlib.suppress(Exception):
            process.wait()
        stdout_thread.join(timeout=0.1)
        stderr_thread.join(timeout=0.1)
        _finalize_process(process_id, returncode=process.returncode, status="failed", error=str(exc))
        raise
    stdout = b"".join(stdout_chunks)
    stderr = b"".join(stderr_chunks)
    _finalize_process(process_id, returncode=returncode)
    return TrackedCompletedProcess(
        args=list(command),
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )
