"""In-process async job tracker.

No task queue (Celery/RQ) is a dependency of this project, so jobs are just
``asyncio.Task``s tracked in a dict — good enough for a single-process
FastAPI server fronting a pipeline that already serializes stage-by-stage.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


@dataclass
class JobRecord:
    job_id: str
    kind: str
    status: str = STATUS_PENDING
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    result: Any = None
    error: str | None = None
    _task: asyncio.Task | None = field(default=None, repr=False, compare=False)


class JobManager:
    """Tracks background jobs backed by ``asyncio.Task``."""

    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}

    def submit_job(self, kind: str, coro_factory: Callable[[], Awaitable[Any]]) -> str:
        """Schedule *coro_factory* as a background task and return its job id."""
        job_id = uuid.uuid4().hex
        record = JobRecord(job_id=job_id, kind=kind)
        self._jobs[job_id] = record

        async def _run() -> None:
            record.status = STATUS_RUNNING
            try:
                record.result = await coro_factory()
                record.status = STATUS_COMPLETED
            except Exception as exc:  # a failed job must not crash the server
                record.status = STATUS_FAILED
                record.error = f"{type(exc).__name__}: {exc}"

        record._task = asyncio.create_task(_run())
        return job_id

    def get_job_status(self, job_id: str) -> JobRecord | None:
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[JobRecord]:
        return list(self._jobs.values())


job_manager = JobManager()
