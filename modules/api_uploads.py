from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from modules.api_execution import _execute_run, _queue_run_task
from modules.api_state import UPLOAD_DIR, _create_run_record


async def _persist_upload(
    file: UploadFile,
    upload_id: str,
    keep_file: bool,
) -> tuple[str, Path | None, str | None]:
    safe_name = os.path.basename(file.filename) if file.filename else "upload.bin"

    saved_path: Path | None = None
    tmp_path: str | None = None
    if keep_file:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        saved_path = UPLOAD_DIR / f"{upload_id}_{safe_name}"
        with open(saved_path, "wb") as out_f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                out_f.write(chunk)
        return str(saved_path), saved_path, None

    suffix = os.path.splitext(safe_name)[1] if safe_name and "." in safe_name else ""
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = tmp.name
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            tmp.write(chunk)
    return tmp_path, None, tmp_path


async def _close_upload(file: UploadFile) -> None:
    try:
        await file.close()
    except Exception:
        pass


def _upload_name(file: UploadFile) -> str:
    return os.path.basename(file.filename) if file.filename else "upload.bin"


async def _run_upload_now(orchestrator, file: UploadFile, keep_file: bool) -> tuple[dict[str, Any], str, Path | None]:
    upload_id = uuid.uuid4().hex
    safe_name = _upload_name(file)
    analysis_target, saved_path, cleanup_path = await _persist_upload(file, upload_id, keep_file)
    result = await _execute_run(
        orchestrator,
        analysis_target=analysis_target,
        run_id=upload_id,
        source="upload",
        file_name=safe_name,
        cleanup_path=cleanup_path,
    )
    return result, upload_id, saved_path


async def _queue_upload_run(orchestrator, file: UploadFile, keep_file: bool) -> tuple[str, Path | None]:
    upload_id = uuid.uuid4().hex
    safe_name = _upload_name(file)
    analysis_target, saved_path, cleanup_path = await _persist_upload(file, upload_id, keep_file)
    _create_run_record(run_id=upload_id, source="upload", file_name=safe_name)
    _queue_run_task(
        orchestrator,
        analysis_target=analysis_target,
        run_id=upload_id,
        source="upload",
        file_name=safe_name,
        cleanup_path=cleanup_path,
    )
    return upload_id, saved_path


async def _finalize_upload(file: UploadFile) -> None:
    await _close_upload(file)
