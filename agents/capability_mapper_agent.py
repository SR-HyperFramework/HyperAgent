from __future__ import annotations

from typing import Any

from core.die_handler import AnalysisType
from core.pipeline_logger import PipelineLogger
from core.result_models import Finding


class CapabilityMapperAgent:
    EXECUTION_KEYWORDS = (
        "create process",
        "creates process",
        "spawn",
        "launch",
        "execute",
        "executes",
        "run command",
    )
    PERSISTENCE_KEYWORDS = (
        "startup",
        "autorun",
        "run key",
        "scheduled task",
        "service",
        "persistence",
    )

    def _normalize_analysis_type(self, analysis_type: AnalysisType | str | None) -> str | None:
        if isinstance(analysis_type, AnalysisType):
            return analysis_type.name
        if isinstance(analysis_type, str):
            return analysis_type
        return None

    @staticmethod
    def _append_label(labels: list[str], label: str) -> None:
        if label not in labels:
            labels.append(label)

    @staticmethod
    def _append_finding_ref(evidence_refs: list[dict[str, Any]], finding: Finding) -> None:
        if any(ref.get("kind") == "finding" and ref.get("id") == finding.id for ref in evidence_refs):
            return
        evidence_refs.append(
            {
                "kind": "finding",
                "id": finding.id,
                "category": finding.category,
            }
        )

    def _map_labels(self, report: str, artifact_findings: list[Finding]) -> tuple[list[str], list[dict[str, Any]]]:
        labels: list[str] = []
        evidence_refs: list[dict[str, Any]] = [{"kind": "legacy_payload_field", "field": "ai_analysis_report"}]

        behavior_finding: Finding | None = None
        for finding in artifact_findings:
            if finding.category == "behavior" and behavior_finding is None:
                behavior_finding = finding
            if finding.category == "obfuscation":
                self._append_label(labels, "defense_evasion")
                self._append_finding_ref(evidence_refs, finding)
            if finding.category in {"config", "ioc"}:
                self._append_label(labels, "command_and_control")
                self._append_finding_ref(evidence_refs, finding)

        lowered_report = report.lower()
        if any(keyword in lowered_report for keyword in self.EXECUTION_KEYWORDS):
            self._append_label(labels, "execution")
            if behavior_finding:
                self._append_finding_ref(evidence_refs, behavior_finding)
        if any(keyword in lowered_report for keyword in self.PERSISTENCE_KEYWORDS):
            self._append_label(labels, "persistence")
            if behavior_finding:
                self._append_finding_ref(evidence_refs, behavior_finding)

        return labels, evidence_refs

    @staticmethod
    def _build_summary(labels: list[str]) -> str:
        if not labels:
            return "Mapped capability indicators"
        if len(labels) == 1:
            return f"Mapped {labels[0].replace('_', ' ')} capability"
        joined = ", ".join(label.replace("_", " ") for label in labels[:2])
        if len(labels) > 2:
            joined = f"{joined}, and more"
        return f"Mapped capability indicators: {joined}"

    def analyze(
        self,
        *,
        artifact_id: str | None,
        analysis_type: AnalysisType | str | None,
        analysis_data: Any,
        artifact_findings: list[Finding] | None = None,
        pipeline_logger: PipelineLogger | None = None,
    ) -> list[Finding]:
        normalized_type = self._normalize_analysis_type(analysis_type)
        if not artifact_id or normalized_type != AnalysisType.NATIVE.name:
            return []
        if not isinstance(analysis_data, dict):
            return []

        report = analysis_data.get("ai_analysis_report")
        if not isinstance(report, str) or not report.strip():
            return []

        capability_labels, evidence_refs = self._map_labels(report, artifact_findings or [])
        if not capability_labels:
            return []

        if pipeline_logger:
            pipeline_logger.log(
                "capability_mapper",
                "started",
                "Running capability mapping specialist",
                artifact_id=artifact_id,
            )

        finding = Finding(
            artifact_id=artifact_id,
            category="capability",
            summary=self._build_summary(capability_labels),
            evidence=report,
            confidence=0.7,
            metadata={
                "source": "CapabilityMapperAgent",
                "analysis_type": normalized_type,
                "capability_labels": capability_labels,
                "evidence_refs": evidence_refs,
            },
        )

        if pipeline_logger:
            pipeline_logger.log(
                "capability_mapper",
                "completed",
                "Capability mapping specialist completed",
                artifact_id=artifact_id,
                finding_count=1,
            )

        return [finding]
