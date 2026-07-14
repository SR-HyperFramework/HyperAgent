from __future__ import annotations

import os
import uuid

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

from modules.api_dashboard import _dashboard_html
from modules.api_execution import _execute_run, _queue_run_task, _run_processes_snapshot, _stop_run
from modules.api_schema import AnalyzePathRequest
from modules.api_state import (
    RUNS,
    RUN_TASK_INDEX,
    RUN_WORKERS,
    TASK_OUTPUTS,
    TASK_SESSIONS,
    UPLOAD_DIR,
    _create_run_record,
    _merge_task_output,
    _run_snapshot,
    _run_task_output_snapshot,
    _run_tasks_snapshot,
    _sync_task_from_event,
)
from modules.api_uploads import _finalize_upload, _queue_upload_run, _run_upload_now
from core.task_runtime import reset_process_runtime
from main import HyperAgentOrchestrator

app = FastAPI(title="HyperAgent API", version="0.1.0")
orchestrator = HyperAgentOrchestrator()

__all__ = [
    "app",
    "orchestrator",
    "AnalyzePathRequest",
    "UPLOAD_DIR",
    "RUNS",
    "TASK_SESSIONS",
    "RUN_TASK_INDEX",
    "TASK_OUTPUTS",
    "RUN_WORKERS",
    "reset_process_runtime",
    "_create_run_record",
    "_merge_task_output",
    "_sync_task_from_event",
]


@app.post("/analyze/path")
async def analyze_path(body: AnalyzePathRequest):
    file_path = body.file_path
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    run_id = uuid.uuid4().hex
    try:
        result = await _execute_run(
            orchestrator,
            analysis_target=file_path,
            run_id=run_id,
            source="path",
            file_name=os.path.basename(file_path),
        )
        result["run_id"] = run_id
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/analyze/upload")
async def analyze_upload(
    file: UploadFile = File(...),
    keep_file: bool = False,
):
    if not file:
        raise HTTPException(status_code=400, detail="No file uploaded")

    try:
        result, upload_id, saved_path = await _run_upload_now(orchestrator, file, keep_file)
        result["upload_id"] = upload_id
        result["run_id"] = upload_id
        result["saved_path"] = str(saved_path) if saved_path else None
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    finally:
        await _finalize_upload(file)


@app.post("/runs/path")
async def start_run_path(body: AnalyzePathRequest):
    file_path = body.file_path
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    run_id = uuid.uuid4().hex
    _create_run_record(run_id=run_id, source="path", file_name=os.path.basename(file_path))
    _queue_run_task(
        orchestrator,
        analysis_target=file_path,
        run_id=run_id,
        source="path",
        file_name=os.path.basename(file_path),
    )
    return {"run_id": run_id, "status": "queued"}


@app.post("/runs/upload")
async def start_run_upload(
    file: UploadFile = File(...),
    keep_file: bool = False,
):
    if not file:
        raise HTTPException(status_code=400, detail="No file uploaded")

    try:
        upload_id, saved_path = await _queue_upload_run(orchestrator, file, keep_file)
        return {
            "run_id": upload_id,
            "upload_id": upload_id,
            "status": "queued",
            "saved_path": str(saved_path) if saved_path else None,
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    finally:
        await _finalize_upload(file)


@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    return _run_snapshot(run_id)


@app.get("/runs/{run_id}/tasks")
async def get_run_tasks(run_id: str):
    return _run_tasks_snapshot(run_id)


@app.get("/runs/{run_id}/processes")
async def get_run_processes(run_id: str):
    return _run_processes_snapshot(run_id)


@app.post("/runs/{run_id}/stop")
async def stop_run(run_id: str):
    return await _stop_run(run_id)


@app.get("/runs/{run_id}/tasks/{task_id}")
async def get_run_task_output(run_id: str, task_id: str):
    return _run_task_output_snapshot(run_id, task_id)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_index():
    return HTMLResponse(_dashboard_html())


@app.get("/dashboard/{run_id}", response_class=HTMLResponse)
async def dashboard_run(run_id: str):
    return HTMLResponse(_dashboard_html(run_id))
