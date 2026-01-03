from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel

from main import HyperAgentOrchestrator

app = FastAPI(title="HyperAgent API", version="0.1.0")

orchestrator = HyperAgentOrchestrator()


UPLOAD_DIR = Path(os.getenv("HYPERAGENT_UPLOAD_DIR", "uploads"))


class AnalyzePathRequest(BaseModel):
    file_path: str


# @app.get("/health")
# async def health():
#     return {"status": "ok"}

@app.post("/analyze/path")
async def analyze_path(body: AnalyzePathRequest):
    file_path = body.file_path
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    try:
        return await orchestrator.analyze(file_path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/analyze/upload")
async def analyze_upload(
    file: UploadFile = File(...),
    # original_name: Optional[str] = None,
    keep_file: bool = False,
):
    if not file:
        raise HTTPException(status_code=400, detail="No file uploaded")

    safe_name = os.path.basename(file.filename) if file.filename else "upload.bin"
    upload_id = uuid.uuid4().hex

    saved_path: Optional[Path] = None
    tmp_path: Optional[str] = None
    try:
        # Persist to a stable on-disk path so downstream tools (DIE/IDA/etc.) can open it.
        if keep_file:
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            saved_path = UPLOAD_DIR / f"{upload_id}_{safe_name}"

            with open(saved_path, "wb") as out_f:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    out_f.write(chunk)
            analysis_target = str(saved_path)
        else:
            suffix = ""
            if safe_name and "." in safe_name:
                suffix = os.path.splitext(safe_name)[1]

            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp_path = tmp.name
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    tmp.write(chunk)
            analysis_target = tmp_path

        result = await orchestrator.analyze(analysis_target)
        result["upload_id"] = upload_id
        # result["original_name"] = original_name or (file.filename if file.filename else None)
        result["saved_path"] = str(saved_path) if saved_path else None
        return result

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # If we used a temp file, clean it up after analysis.
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
