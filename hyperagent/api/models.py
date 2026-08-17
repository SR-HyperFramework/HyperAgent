"""Pydantic request/response models for the HyperAgent API."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    sample_path: str
    stage_id: str | None = None
    ablation_config: str | None = Field(
        default=None, description="Name of an ABLATION_CONFIGS entry, e.g. 'FULL'."
    )


class AnalyzeResponse(BaseModel):
    job_id: str
    status: str


class JobStatusResponse(BaseModel):
    job_id: str
    kind: str
    status: str
    created_at: str
    result: Any = None
    error: str | None = None


class BatchAnalyzeRequest(BaseModel):
    malware_dir: str
    benign_dir: str
    output_dir: str = "experiments/results"
    quick_test: bool = False
    split_date: str | None = None


class BatchJobResponse(BaseModel):
    job_id: str
    status: str


class RuleVerifyRequest(BaseModel):
    jq_rule: str
    benign_reports_dir: str


class RuleVerifyResponse(BaseModel):
    passed: bool
    false_positive_files: list[str]
    repair_prompt: str | None = None
