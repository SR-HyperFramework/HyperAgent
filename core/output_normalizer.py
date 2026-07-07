from __future__ import annotations

import re
from typing import Any

from core.result_models import AgentResult, ArtifactNode, Finding


_URL_PATTERN = re.compile(r"https?://[^\s'\"<>]+", re.IGNORECASE)
_IP_PATTERN = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b")
_FILE_PATH_PATTERN = re.compile(r"\b[a-zA-Z]:\\(?:[^\\/:*?\"<>|\r\n ]+\\)*[^\\/:*?\"<>|\r\n ]+")
_DOMAIN_PATTERN = re.compile(r"\b(?:[a-zA-Z0-9-]+\.)+(?:com|net|org|ru|cn|xyz|biz|info|io)\b", re.IGNORECASE)


def serialize_agent_result(result: AgentResult) -> dict[str, Any]:
    return dict(result.legacy_payload)


def normalize_agent_result(result: Any) -> Any:
    if isinstance(result, AgentResult):
        return serialize_agent_result(result)
    if isinstance(result, dict):
        return dict(result)
    return result


def serialize_artifact(artifact: ArtifactNode) -> dict[str, Any]:
    return {
        "id": artifact.id,
        "path": artifact.path,
        "kind": artifact.kind,
        "parent_id": artifact.parent_id,
        "depth": artifact.depth,
        "sha256": artifact.sha256,
    }


def serialize_finding(finding: Finding) -> dict[str, Any]:
    return {
        "id": finding.id,
        "artifact_id": finding.artifact_id,
        "category": finding.category,
        "summary": finding.summary,
        "confidence": finding.confidence,
    }


def _infer_ioc_type(value: str) -> str:
    if _URL_PATTERN.fullmatch(value):
        return "url"
    if _IP_PATTERN.fullmatch(value):
        return "ip_address"
    if value.upper().startswith("HKEY_"):
        return "registry_key"
    if _FILE_PATH_PATTERN.fullmatch(value):
        return "file_path"
    if value.startswith(("Global\\", "Local\\")):
        return "mutex"
    if _DOMAIN_PATTERN.fullmatch(value):
        return "domain"
    return "indicator"


def serialize_iocs(findings: list[Finding]) -> list[dict[str, str]]:
    serialized: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for finding in findings:
        if finding.category != "ioc":
            continue
        for value in finding.metadata.get("ioc_values", []):
            if not isinstance(value, str):
                continue
            ioc_type = _infer_ioc_type(value)
            key = (finding.artifact_id, ioc_type, value)
            if key in seen:
                continue
            seen.add(key)
            serialized.append(
                {
                    "artifact_id": finding.artifact_id,
                    "type": ioc_type,
                    "value": value,
                }
            )
    return serialized


def build_public_run_summary(
    *,
    artifacts: list[ArtifactNode],
    findings: list[Finding],
    root_artifact_id: str | None,
) -> dict[str, Any]:
    verdict: dict[str, Any] | None = None
    final_report_markdown: str | None = None

    for finding in findings:
        if finding.artifact_id != root_artifact_id:
            continue
        if finding.category == "report_synthesis" and final_report_markdown is None:
            final_report_markdown = finding.evidence or None
        if finding.category == "risk_assessment" and verdict is None:
            reasons = finding.metadata.get("reasons")
            verdict = {
                "level": finding.metadata.get("risk_level"),
                "score": finding.metadata.get("risk_score"),
                "reasons": list(reasons) if isinstance(reasons, list) else [],
                "summary": finding.summary,
            }

    return {
        "artifacts": [serialize_artifact(artifact) for artifact in artifacts],
        "findings": [serialize_finding(finding) for finding in findings],
        "iocs": serialize_iocs(findings),
        "verdict": verdict,
        "final_report_markdown": final_report_markdown,
    }


def build_orchestrator_response(
    *,
    run_id: str,
    file_path: str,
    detected_type: str,
    die_data: dict[str, Any],
    analysis_data: Any,
    next_stage_results: list[Any],
    pipeline_log: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "file_path": file_path,
        "detected_type": detected_type,
        "die": dict(die_data),
        "result": normalize_agent_result(analysis_data),
        "next_stage_results": list(next_stage_results),
        "pipeline_log": list(pipeline_log),
    }
