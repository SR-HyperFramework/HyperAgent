from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from core.pipeline_logger import PipelineLogger
from main import HyperAgentOrchestrator

app = FastAPI(title="HyperAgent API", version="0.1.0")

orchestrator = HyperAgentOrchestrator()

UPLOAD_DIR = Path(os.getenv("HYPERAGENT_UPLOAD_DIR", "uploads"))
RUNS: dict[str, dict[str, Any]] = {}


class AnalyzePathRequest(BaseModel):
    file_path: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _create_run_record(*, run_id: str, source: str, file_name: str | None = None) -> dict[str, Any]:
    existing = RUNS.get(run_id)
    if existing is not None:
        if source:
            existing["source"] = source
        if file_name:
            existing["file_name"] = file_name
        return existing

    record = {
        "run_id": run_id,
        "status": "queued",
        "source": source,
        "file_name": file_name,
        "started_at": _utc_now(),
        "finished_at": None,
        "pipeline_log": [],
        "result": None,
        "error": None,
    }
    RUNS[run_id] = record
    return record


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

    return handle


async def _execute_run(
    *,
    analysis_target: str,
    run_id: str,
    source: str,
    file_name: str | None = None,
    cleanup_path: str | None = None,
) -> dict[str, Any]:
    record = _create_run_record(run_id=run_id, source=source, file_name=file_name)
    pipeline_logger = PipelineLogger(run_id)
    pipeline_logger.subscribe(_pipeline_listener(run_id))
    try:
        result = await orchestrator.analyze(analysis_target, run_id=run_id, pipeline_logger=pipeline_logger)
        record["result"] = result
        record["pipeline_log"] = result.get("pipeline_log", record["pipeline_log"])
        record["status"] = "completed"
        return result
    except Exception as exc:
        record["status"] = "failed"
        record["error"] = str(exc)
        raise
    finally:
        record["finished_at"] = _utc_now()
        if cleanup_path and os.path.exists(cleanup_path):
            try:
                os.remove(cleanup_path)
            except OSError:
                pass


async def _persist_upload(
    file: UploadFile,
    upload_id: str,
    keep_file: bool,
) -> tuple[str, Optional[Path], Optional[str]]:
    safe_name = os.path.basename(file.filename) if file.filename else "upload.bin"

    saved_path: Optional[Path] = None
    tmp_path: Optional[str] = None
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
    return tmp_path, None, tmp_path


async def _close_upload(file: UploadFile) -> None:
    try:
        await file.close()
    except Exception:
        pass


def _upload_name(file: UploadFile) -> str:
    return os.path.basename(file.filename) if file.filename else "upload.bin"


def _queue_run_task(*, analysis_target: str, run_id: str, source: str, file_name: str | None = None, cleanup_path: str | None = None) -> None:
    asyncio.create_task(
        _execute_run(
            analysis_target=analysis_target,
            run_id=run_id,
            source=source,
            file_name=file_name,
            cleanup_path=cleanup_path,
        )
    )


async def _run_upload_now(file: UploadFile, keep_file: bool) -> tuple[dict[str, Any], str, Optional[Path]]:
    upload_id = uuid.uuid4().hex
    safe_name = _upload_name(file)
    analysis_target, saved_path, cleanup_path = await _persist_upload(file, upload_id, keep_file)
    result = await _execute_run(
        analysis_target=analysis_target,
        run_id=upload_id,
        source="upload",
        file_name=safe_name,
        cleanup_path=cleanup_path,
    )
    return result, upload_id, saved_path


async def _queue_upload_run(file: UploadFile, keep_file: bool) -> tuple[str, Optional[Path]]:
    upload_id = uuid.uuid4().hex
    safe_name = _upload_name(file)
    analysis_target, saved_path, cleanup_path = await _persist_upload(file, upload_id, keep_file)
    _create_run_record(run_id=upload_id, source="upload", file_name=safe_name)
    _queue_run_task(
        analysis_target=analysis_target,
        run_id=upload_id,
        source="upload",
        file_name=safe_name,
        cleanup_path=cleanup_path,
    )
    return upload_id, saved_path


async def _finalize_upload(file: UploadFile) -> None:
    await _close_upload(file)


def _run_snapshot(run_id: str) -> dict[str, Any]:
    record = RUNS.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return {
        "run_id": run_id,
        "status": record["status"],
        "source": record["source"],
        "file_name": record["file_name"],
        "started_at": record["started_at"],
        "finished_at": record["finished_at"],
        "pipeline_log": record["pipeline_log"],
        "result": record["result"],
        "error": record["error"],
    }


def _dashboard_html(run_id: str | None = None) -> str:
    initial_run_id = run_id or ""
    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>HyperAgent Workflow Dashboard</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #09090b;
      --panel: #111115;
      --panel-2: #18181d;
      --border: #27272f;
      --text: #f4f4f5;
      --muted: #a1a1aa;
      --accent: #22c55e;
      --warn: #f59e0b;
      --danger: #ef4444;
      --radius: 16px;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Inter, Arial, sans-serif; background: var(--bg); color: var(--text); }}
    .shell {{ max-width: 1440px; margin: 0 auto; padding: 24px; }}
    .header {{ display: grid; gap: 16px; margin-bottom: 24px; }}
    .title {{ display: flex; justify-content: space-between; gap: 16px; align-items: end; flex-wrap: wrap; }}
    h1 {{ margin: 0; font-size: 32px; line-height: 1; letter-spacing: -0.03em; }}
    .sub {{ color: var(--muted); max-width: 72ch; }}
    .controls {{ display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 12px; }}
    .upload-controls {{ display: grid; grid-template-columns: auto minmax(0,1fr) auto auto; gap: 12px; align-items: center; }}
    input, button, .button-like {{ border-radius: 999px; border: 1px solid var(--border); background: var(--panel); color: var(--text); padding: 12px 16px; font: inherit; }}
    button {{ background: var(--accent); color: #052e16; border: 0; font-weight: 700; cursor: pointer; }}
    button[disabled] {{ opacity: 0.6; cursor: progress; }}
    .button-like {{ display: inline-flex; align-items: center; justify-content: center; cursor: pointer; user-select: none; text-decoration: none; }}
    .secondary-button {{ background: var(--panel); color: var(--text); border: 1px solid var(--border); font-weight: 700; }}
    .file-picker {{ position: relative; display: inline-flex; align-items: center; justify-content: center; overflow: hidden; }}
    .file-picker input[type="file"] {{ position: absolute; inset: 0; width: 100%; height: 100%; opacity: 0; cursor: pointer; padding: 0; margin: 0; }}
    .file-name {{ color: var(--muted); font-size: 13px; min-height: 20px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .toggle {{ display: inline-flex; align-items: center; gap: 8px; padding: 0 12px; border: 1px solid var(--border); border-radius: 999px; background: var(--panel); color: var(--muted); min-height: 46px; }}
    .toggle input {{ width: 16px; height: 16px; margin: 0; padding: 0; accent-color: var(--accent); }}
    .status-text {{ color: var(--muted); font-size: 13px; min-height: 20px; }}
    @media (max-width: 980px) {{ .upload-controls {{ grid-template-columns: 1fr; }} }}
    .grid {{ display: grid; grid-template-columns: 340px minmax(0,1fr); gap: 20px; }}
    .card {{ background: linear-gradient(180deg, var(--panel), var(--panel-2)); border: 1px solid var(--border); border-radius: var(--radius); padding: 18px; }}
    .card h2 {{ margin: 0 0 12px; font-size: 14px; text-transform: uppercase; letter-spacing: 0.12em; color: var(--muted); }}
    .meta {{ display: grid; gap: 12px; }}
    .meta-row {{ display: grid; gap: 4px; }}
    .label {{ font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.12em; }}
    .value {{ font-size: 14px; word-break: break-word; }}
    .badge {{ display: inline-flex; align-items: center; gap: 8px; border-radius: 999px; padding: 8px 12px; width: fit-content; font-size: 12px; font-weight: 700; background: #1c1917; color: #fde68a; }}
    .badge.running {{ background: #172554; color: #bfdbfe; }}
    .badge.completed {{ background: #052e16; color: #bbf7d0; }}
    .badge.failed {{ background: #450a0a; color: #fecaca; }}
    .stack {{ display: grid; gap: 16px; }}
    .timeline {{ display: grid; gap: 10px; }}
    .event {{ border: 1px solid var(--border); border-radius: 14px; padding: 14px; background: rgba(255,255,255,0.02); }}
    .event-head {{ display: flex; justify-content: space-between; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }}
    .event-title {{ font-weight: 700; }}
    .event-stage {{ color: var(--muted); font-size: 12px; }}
    .event-msg {{ color: var(--text); font-size: 14px; }}
    .event-meta {{ margin-top: 10px; display: flex; flex-wrap: wrap; gap: 8px; }}
    .chip {{ border-radius: 999px; padding: 6px 10px; border: 1px solid var(--border); color: var(--muted); font-size: 12px; }}
    .tree {{ display: grid; gap: 8px; }}
    .tree-item {{ padding-left: 14px; border-left: 1px solid var(--border); }}
    pre {{ white-space: pre-wrap; word-break: break-word; margin: 0; font: 12px/1.6 ui-monospace, SFMono-Regular, Menlo, monospace; color: #d4d4d8; }}
    @media (max-width: 980px) {{ .grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <div class=\"shell\">
    <div class=\"header\">
      <div class=\"title\">
        <div>
          <h1>HyperAgent Workflow Dashboard</h1>
          <div class=\"sub\">Live view of agent workflow transitions, next-stage handoffs, and final analysis output.</div>
        </div>
        <div id=\"statusBadge\" class=\"badge\">Idle</div>
      </div>
      <div class=\"controls\">
        <input id=\"runIdInput\" placeholder=\"Enter run_id to inspect\" value=\"{initial_run_id}\" />
        <button id=\"openRunButton\" type=\"button\">Open run</button>
      </div>
      <div class=\"upload-controls\">
        <label id=\"chooseFileButton\" class=\"button-like secondary-button file-picker\">
          <span>Choose file</span>
          <input id=\"uploadFileInput\" type=\"file\" />
        </label>
        <div id=\"selectedFileName\" class=\"file-name\">No file selected.</div>
        <label class=\"toggle\"><input id=\"keepFileInput\" type=\"checkbox\" /> Keep file</label>
        <button id=\"uploadRunButton\" type=\"button\">Upload run</button>
      </div>
      <div id=\"uploadStatus\" class=\"status-text\"></div>
    </div>
    <div class=\"grid\">
      <div class=\"stack\">
        <section class=\"card\">
          <h2>Run</h2>
          <div class=\"meta\" id=\"runMeta\"></div>
        </section>
        <section class=\"card\">
          <h2>Artifacts</h2>
          <div id=\"artifactTree\" class=\"tree\"></div>
        </section>
      </div>
      <div class=\"stack\">
        <section class=\"card\">
          <h2>Timeline</h2>
          <div id=\"timeline\" class=\"timeline\"></div>
        </section>
        <section class=\"card\">
          <h2>Summary</h2>
          <pre id=\"summary\">Open a run to inspect findings, IOCs, verdict, and report output.</pre>
        </section>
      </div>
    </div>
  </div>
  <script>
    const runIdInput = document.getElementById('runIdInput');
    const openRunButton = document.getElementById('openRunButton');
    const uploadFileInput = document.getElementById('uploadFileInput');
    const selectedFileName = document.getElementById('selectedFileName');
    const keepFileInput = document.getElementById('keepFileInput');
    const uploadRunButton = document.getElementById('uploadRunButton');
    const uploadStatus = document.getElementById('uploadStatus');
    const runMeta = document.getElementById('runMeta');
    const timeline = document.getElementById('timeline');
    const artifactTree = document.getElementById('artifactTree');
    const summary = document.getElementById('summary');
    const statusBadge = document.getElementById('statusBadge');
    let currentRunId = runIdInput.value.trim();
    let pollHandle = null;

    function setBadge(status) {{
      statusBadge.textContent = status || 'idle';
      statusBadge.className = 'badge ' + (status || '');
    }}

    function metaRow(label, value) {{
      return `<div class=\"meta-row\"><div class=\"label\">${{label}}</div><div class=\"value\">${{value || '-'}}<\/div><\/div>`;
    }}

    function renderMeta(snapshot) {{
      const result = snapshot.result || {{}};
      runMeta.innerHTML = [
        metaRow('Run ID', snapshot.run_id),
        metaRow('Status', snapshot.status),
        metaRow('Detected type', result.detected_type),
        metaRow('File path', result.file_path),
        metaRow('Started at', snapshot.started_at),
        metaRow('Finished at', snapshot.finished_at),
        snapshot.error ? metaRow('Error', snapshot.error) : ''
      ].join('');
    }}

    function renderTimeline(events) {{
      if (!events || !events.length) {{
        timeline.innerHTML = '<div class=\"event\"><div class=\"event-msg\">Waiting for pipeline events.<\/div><\/div>';
        return;
      }}
      timeline.innerHTML = events.map((event) => {{
        const data = event.data || {{}};
        const chips = [];
        if (event.display_stage) chips.push(`<span class=\"chip\">${{event.display_stage}}<\/span>`);
        if (data.transition_label) chips.push(`<span class=\"chip\">${{data.transition_label}}<\/span>`);
        if (data.agent) chips.push(`<span class=\"chip\">${{data.agent}}<\/span>`);
        if (data.file_path) chips.push(`<span class=\"chip\">${{data.file_path}}<\/span>`);
        return `
          <div class=\"event\">
            <div class=\"event-head\">
              <div>
                <div class=\"event-title\">#${{event.sequence}} ${{event.status_label}}<\/div>
                <div class=\"event-stage\">${{event.stage}} · ${{event.timestamp}}<\/div>
              <\/div>
            <\/div>
            <div class=\"event-msg\">${{event.message}}<\/div>
            <div class=\"event-meta\">${{chips.join('')}}<\/div>
          <\/div>`;
      }}).join('');
    }}

    function flattenTree(node, depth = 0, rows = []) {{
      if (!node) return rows;
      rows.push({{ depth, label: `${{node.detected_type || 'UNKNOWN'}} · ${{node.file_path || '-'}}` }});
      const children = node.next_stage_results || [];
      children.forEach((child) => flattenTree(child, depth + 1, rows));
      return rows;
    }}

    function renderArtifacts(result) {{
      const rows = flattenTree(result);
      artifactTree.innerHTML = rows.length
        ? rows.map((row) => `<div class=\"tree-item\" style=\"margin-left:${{row.depth * 12}}px\">${{row.label}}<\/div>`).join('')
        : '<div class=\"tree-item\">No artifact tree yet.<\/div>';
    }}

    function renderSummary(snapshot) {{
      if (!snapshot.result) {{
        summary.textContent = snapshot.error || 'Run has not produced a result yet.';
        return;
      }}
      const result = snapshot.result;
      summary.textContent = JSON.stringify({{
        verdict: result.verdict,
        findings: result.findings,
        iocs: result.iocs,
        final_report_markdown: result.final_report_markdown
      }}, null, 2);
    }}

    async function loadRun(runId) {{
      const response = await fetch(`/runs/${{encodeURIComponent(runId)}}`);
      if (!response.ok) throw new Error(`Run lookup failed: ${{response.status}}`);
      return response.json();
    }}

    async function refresh() {{
      if (!currentRunId) return;
      try {{
        const snapshot = await loadRun(currentRunId);
        setBadge(snapshot.status);
        renderMeta(snapshot);
        renderTimeline(snapshot.pipeline_log || []);
        renderArtifacts(snapshot.result);
        renderSummary(snapshot);
        if (snapshot.status === 'completed' || snapshot.status === 'failed') {{
          uploadRunButton.disabled = false;
          uploadStatus.textContent = snapshot.status === 'completed' ? 'Upload run completed.' : 'Upload run failed.';
          if (pollHandle) clearInterval(pollHandle);
          pollHandle = null;
        }}
      }} catch (error) {{
        setBadge('failed');
        runMeta.innerHTML = metaRow('Error', error.message);
        uploadRunButton.disabled = false;
        uploadStatus.textContent = error.message;
      }}
    }}

    function openRun() {{
      currentRunId = runIdInput.value.trim();
      if (!currentRunId) return;
      window.history.replaceState(null, '', `/dashboard/${{encodeURIComponent(currentRunId)}}`);
      uploadStatus.textContent = '';
      if (pollHandle) clearInterval(pollHandle);
      refresh();
      pollHandle = setInterval(refresh, 1500);
    }}

    async function startUploadRun() {{
      const file = uploadFileInput.files && uploadFileInput.files[0];
      if (!file) {{
        uploadStatus.textContent = 'Choose a file first.';
        return;
      }}

      uploadRunButton.disabled = true;
      uploadStatus.textContent = 'Uploading sample and creating run...';
      const formData = new FormData();
      formData.append('file', file);
      formData.append('keep_file', keepFileInput.checked ? 'true' : 'false');

      try {{
        const response = await fetch('/runs/upload', {{ method: 'POST', body: formData }});
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || `Upload failed: ${{response.status}}`);
        runIdInput.value = payload.run_id;
        currentRunId = payload.run_id;
        uploadStatus.textContent = `Queued upload run ${{payload.run_id}}.`;
        window.history.replaceState(null, '', `/dashboard/${{encodeURIComponent(currentRunId)}}`);
        if (pollHandle) clearInterval(pollHandle);
        refresh();
        pollHandle = setInterval(refresh, 1500);
      }} catch (error) {{
        uploadRunButton.disabled = false;
        uploadStatus.textContent = error.message;
      }}
    }}

    uploadFileInput.addEventListener('change', () => {{
      const file = uploadFileInput.files && uploadFileInput.files[0];
      selectedFileName.textContent = file ? file.name : 'No file selected.';
      if (file) uploadStatus.textContent = '';
    }});
    openRunButton.addEventListener('click', openRun);
    uploadRunButton.addEventListener('click', startUploadRun);
    if (currentRunId) openRun();
  </script>
</body>
</html>"""


@app.post("/analyze/path")
async def analyze_path(body: AnalyzePathRequest):
    file_path = body.file_path
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    run_id = uuid.uuid4().hex
    try:
        result = await _execute_run(analysis_target=file_path, run_id=run_id, source="path", file_name=os.path.basename(file_path))
        result["run_id"] = run_id
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/analyze/upload")
async def analyze_upload(
    file: UploadFile = File(...),
    keep_file: bool = False,
):
    if not file:
        raise HTTPException(status_code=400, detail="No file uploaded")

    try:
        result, upload_id, saved_path = await _run_upload_now(file, keep_file)
        result["upload_id"] = upload_id
        result["run_id"] = upload_id
        result["saved_path"] = str(saved_path) if saved_path else None
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
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
        upload_id, saved_path = await _queue_upload_run(file, keep_file)
        return {
            "run_id": upload_id,
            "upload_id": upload_id,
            "status": "queued",
            "saved_path": str(saved_path) if saved_path else None,
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await _finalize_upload(file)


@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    return _run_snapshot(run_id)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_index():
    return HTMLResponse(_dashboard_html())


@app.get("/dashboard/{run_id}", response_class=HTMLResponse)
async def dashboard_run(run_id: str):
    return HTMLResponse(_dashboard_html(run_id))

