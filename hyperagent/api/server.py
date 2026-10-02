"""FastAPI server exposing the HyperAgent pipeline and rule verification.

Backs the existing ``webui/`` frontend's async workflows (submit-and-poll
analysis, batch evaluation) plus a synchronous rule-check endpoint. The
read-only report browsing UI itself still talks to ``webui.app`` directly;
this server is for *driving* the pipeline, not browsing finished reports.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException

from ..config import HyperAgentConfig, load_config
from ..engine.launcher import run_pipeline_with_config
from ..tools.rule_verifier import RuleVerifier
from .jobs import job_manager
from .models import (
    AnalyzeRequest,
    AnalyzeResponse,
    BatchAnalyzeRequest,
    BatchJobResponse,
    JobStatusResponse,
    RuleVerifyRequest,
    RuleVerifyResponse,
)

app = FastAPI(title="HyperAgent API")

_config: HyperAgentConfig | None = None


def get_config() -> HyperAgentConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def _resolve_ablation_config(name: str | None):
    if not name:
        return None
    from experiments.ablation_runner import ABLATION_CONFIGS

    for candidate in ABLATION_CONFIGS:
        if candidate.name == name:
            return candidate
    raise HTTPException(status_code=400, detail=f"Unknown ablation_config: {name!r}")


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    """Submit a single sample for the full pipeline; returns a job_id."""
    sample_path = Path(req.sample_path)
    if not sample_path.exists():
        raise HTTPException(status_code=404, detail=f"Sample not found: {sample_path}")

    ablation_config = _resolve_ablation_config(req.ablation_config)
    config = get_config()

    job_id = job_manager.submit_job(
        "analyze",
        lambda: run_pipeline_with_config(
            sample_path, config, ablation_config, stage_id=req.stage_id
        ),
    )
    return AnalyzeResponse(job_id=job_id, status="pending")


@app.get("/analyze/{job_id}", response_model=JobStatusResponse)
async def get_analysis_status(job_id: str) -> JobStatusResponse:
    record = job_manager.get_job_status(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No such job: {job_id}")
    result = record.result.to_dict() if record.result is not None else None
    return JobStatusResponse(
        job_id=record.job_id,
        kind=record.kind,
        status=record.status,
        created_at=record.created_at,
        result=result,
        error=record.error,
    )


@app.post("/analyze/batch", response_model=BatchJobResponse)
async def analyze_batch(req: BatchAnalyzeRequest) -> BatchJobResponse:
    """Submit multiple samples at once — uses experiments.batch_eval.BatchEvaluator."""
    from experiments.batch_eval import BatchEvaluator

    malware_dir = Path(req.malware_dir)
    benign_dir = Path(req.benign_dir)
    if not malware_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"malware_dir not found: {malware_dir}")
    if not benign_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"benign_dir not found: {benign_dir}")

    split_date = date.fromisoformat(req.split_date) if req.split_date else None
    evaluator = BatchEvaluator(get_config())

    job_id = job_manager.submit_job(
        "analyze_batch",
        lambda: evaluator.evaluate_corpus(
            malware_dir=malware_dir,
            benign_dir=benign_dir,
            output_dir=Path(req.output_dir),
            quick_test=req.quick_test,
            split_date=split_date,
        ),
    )
    return BatchJobResponse(job_id=job_id, status="pending")


@app.post("/verify-rule", response_model=RuleVerifyResponse)
async def verify_rule(req: RuleVerifyRequest) -> RuleVerifyResponse:
    """WebUI-facing endpoint to verify a JQ rule before save."""
    verifier = RuleVerifier(Path(req.benign_reports_dir))
    try:
        result = verifier.verify_jq_rule(req.jq_rule)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    repair_prompt = (
        None if result.passed else verifier.generate_repair_prompt(req.jq_rule, result.fps)
    )
    return RuleVerifyResponse(
        passed=result.passed, false_positive_files=result.fps, repair_prompt=repair_prompt
    )
