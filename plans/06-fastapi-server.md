# Phase 6 — FastAPI Server

Read `00-index.md` first for shared constraints and reference paths.
**Depends on Phase 3d** (launcher) and **Phase 4 Part B** (rule verifier)
for their respective endpoints.

## Goal

Expose the pipeline and rule-verification over HTTP for the existing WebUI
(`webui/` dir already in this repo — check what it currently talks to
before designing request/response shapes, so this server is a drop-in
backend rather than requiring a WebUI rewrite).

## Files to create

### `hyperagent/api/models.py` [NEW]

Pydantic models (project already depends on `pydantic>=2.10.0`, see
`pyproject.toml`) for request/response bodies:
- `AnalyzeRequest` / `AnalyzeResponse` (single sample)
- `BatchAnalyzeRequest` / `BatchJobResponse` (Phase 5's batch evaluator)
- `RuleVerifyRequest` / `RuleVerifyResponse` (Phase 4's `RuleVerifier`)
- `JobStatusResponse` (poll endpoint for async job progress)

### `hyperagent/api/jobs.py` [NEW]

In-process async job tracker (dict of `job_id -> status/result`, or a
lightweight `asyncio.Queue`-backed worker) since there's no task queue
dependency (Celery/RQ) in `pyproject.toml` and adding one is out of scope
here — keep this simple: `submit_job()`, `get_job_status()`,
`list_jobs()`.

### `hyperagent/api/server.py` [NEW]

```python
app = FastAPI()

@app.post("/analyze")
async def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    """Submit a single sample for the full pipeline; returns a job_id."""

@app.get("/analyze/{job_id}")
async def get_analysis_status(job_id: str) -> JobStatusResponse: ...

@app.post("/analyze/batch")
async def analyze_batch(req: BatchAnalyzeRequest) -> BatchJobResponse:
    """Submit multiple samples at once — uses experiments.batch_eval.BatchEvaluator."""

@app.post("/verify-rule")
async def verify_rule(req: RuleVerifyRequest) -> RuleVerifyResponse:
    """WebUI-facing endpoint to verify a JQ rule before save — wraps
    hyperagent.tools.rule_verifier.RuleVerifier."""
```
Run actual pipeline execution (`run_pipeline_with_config`) in a background
task (`BackgroundTasks` or the `jobs.py` worker) — never block the request
thread on a full 9-stage run.

### `hyperagent/api/__init__.py` [MODIFY]

Currently empty — export `app` from `server.py` for
`uvicorn hyperagent.api.server:app`.

## Exit criteria

```bash
python -m uvicorn hyperagent.api.server:app --reload
curl -X POST http://localhost:8000/verify-rule -H "Content-Type: application/json" -d '{"jq_rule": ".|has(\"pe\")"}'
```
Add `hyperagent/tests/test_api_server.py` using FastAPI's `TestClient`
(bundled with `fastapi`, no new dependency) — mock `run_pipeline_with_config`
and `RuleVerifier` so tests don't need a live LLM/VM; assert each endpoint
returns the right status code and response shape for a success and a
failure case.
