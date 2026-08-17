"""Tests for hyperagent.api.server.

The pipeline, batch evaluator, and rule verifier are all mocked: this suite
must never need a real sample, VM, or LLM call.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from hyperagent.api import server as server_module
from hyperagent.api.jobs import JobManager
from hyperagent.tools.rule_verifier import VerificationResult


class _FakeRunMetrics:
    def to_dict(self) -> dict:
        return {"run_id": "abc", "total_input_tokens": 10}


@pytest.fixture(autouse=True)
def _fresh_job_manager(monkeypatch):
    """Each test gets its own JobManager so jobs don't leak across tests."""
    manager = JobManager()
    monkeypatch.setattr(server_module, "job_manager", manager)
    monkeypatch.setattr("hyperagent.api.jobs.job_manager", manager)
    return manager


@pytest.fixture(autouse=True)
def _fixed_config(monkeypatch, tmp_path):
    config = SimpleNamespace(reports_root=tmp_path / "reports")
    monkeypatch.setattr(server_module, "get_config", lambda: config)
    return config


@pytest.fixture()
def client() -> TestClient:
    return TestClient(server_module.app)


def _drain_pending_tasks() -> None:
    """Let the event loop run any scheduled asyncio.create_task jobs to completion."""
    async def _drain() -> None:
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if pending:
            await asyncio.wait(pending, timeout=2)

    asyncio.run(_drain())


def test_analyze_missing_sample_returns_404(client: TestClient):
    resp = client.post("/analyze", json={"sample_path": "does/not/exist.exe"})
    assert resp.status_code == 404


def test_analyze_submits_job_and_status_completes(client: TestClient, tmp_path, monkeypatch):
    sample = tmp_path / "sample.exe"
    sample.write_bytes(b"MZ")

    async def fake_run(sample_path, config, ablation_config, *, stage_id=None):
        return _FakeRunMetrics()

    monkeypatch.setattr(server_module, "run_pipeline_with_config", fake_run)

    resp = client.post("/analyze", json={"sample_path": str(sample)})
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]
    assert resp.json()["status"] == "pending"

    _drain_pending_tasks()

    status_resp = client.get(f"/analyze/{job_id}")
    assert status_resp.status_code == 200
    body = status_resp.json()
    assert body["status"] == "completed"
    assert body["result"]["run_id"] == "abc"


def test_analyze_status_unknown_job_404(client: TestClient):
    resp = client.get("/analyze/does-not-exist")
    assert resp.status_code == 404


def test_analyze_unknown_ablation_config_400(client: TestClient, tmp_path):
    sample = tmp_path / "sample.exe"
    sample.write_bytes(b"MZ")
    resp = client.post(
        "/analyze", json={"sample_path": str(sample), "ablation_config": "NOT_REAL"}
    )
    assert resp.status_code == 400


def test_analyze_batch_missing_dir_404(client: TestClient, tmp_path):
    resp = client.post(
        "/analyze/batch",
        json={"malware_dir": str(tmp_path / "nope"), "benign_dir": str(tmp_path)},
    )
    assert resp.status_code == 404


def test_analyze_batch_submits_job(client: TestClient, tmp_path, monkeypatch):
    malware_dir = tmp_path / "malware"
    benign_dir = tmp_path / "benign"
    malware_dir.mkdir()
    benign_dir.mkdir()

    class _FakeEvaluator:
        def __init__(self, config) -> None:
            pass

        async def evaluate_corpus(self, **kwargs):
            return SimpleNamespace(to_dict=lambda: {"aggregate": {}})

    monkeypatch.setattr("experiments.batch_eval.BatchEvaluator", _FakeEvaluator)

    resp = client.post(
        "/analyze/batch",
        json={"malware_dir": str(malware_dir), "benign_dir": str(benign_dir)},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"

    _drain_pending_tasks()


def test_verify_rule_passes(client: TestClient, monkeypatch, tmp_path):
    benign_dir = tmp_path / "benign_reports"
    benign_dir.mkdir()

    def fake_verify_jq_rule(self, jq_rule):
        return VerificationResult(passed=True, fps=[])

    monkeypatch.setattr(
        "hyperagent.tools.rule_verifier.RuleVerifier.verify_jq_rule", fake_verify_jq_rule
    )

    resp = client.post(
        "/verify-rule",
        json={"jq_rule": '.|has("pe")', "benign_reports_dir": str(benign_dir)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["passed"] is True
    assert body["false_positive_files"] == []
    assert body["repair_prompt"] is None


def test_verify_rule_fails_returns_repair_prompt(client: TestClient, monkeypatch, tmp_path):
    benign_dir = tmp_path / "benign_reports"
    benign_dir.mkdir()

    def fake_verify_jq_rule(self, jq_rule):
        return VerificationResult(passed=False, fps=["report_a.json"])

    monkeypatch.setattr(
        "hyperagent.tools.rule_verifier.RuleVerifier.verify_jq_rule", fake_verify_jq_rule
    )

    resp = client.post(
        "/verify-rule",
        json={"jq_rule": ".pe.imphash", "benign_reports_dir": str(benign_dir)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["passed"] is False
    assert body["false_positive_files"] == ["report_a.json"]
    assert body["repair_prompt"] is not None


def test_verify_rule_missing_dir_404(client: TestClient, tmp_path):
    resp = client.post(
        "/verify-rule",
        json={"jq_rule": ".|has(\"pe\")", "benign_reports_dir": str(tmp_path / "nope")},
    )
    assert resp.status_code == 404
