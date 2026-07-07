from __future__ import annotations

from typing import Any

from core.artifact_registry import ArtifactRegistry
from core.finding_store import FindingStore
from core.pipeline_logger import PipelineLogger
from core.result_models import Finding


class RiskScoringAgent:
    CAPABILITY_WEIGHTS = {
        "command_and_control": 20,
        "persistence": 20,
        "defense_evasion": 15,
        "execution": 10,
    }

    def _collect_artifact_chain(self, artifact_registry: ArtifactRegistry, root_artifact_id: str) -> list[Any]:
        ordered: list[Any] = []

        def visit(artifact_id: str) -> None:
            artifact = artifact_registry.get(artifact_id)
            if artifact is None:
                return
            ordered.append(artifact)
            for child in artifact_registry.get_children(artifact_id):
                visit(child.id)

        visit(root_artifact_id)
        return ordered

    @staticmethod
    def _append_unique(values: list[str], value: str) -> None:
        if value and value not in values:
            values.append(value)

    def _score_findings(self, artifacts: list[Any], findings: list[Finding]) -> tuple[int, list[str], list[dict[str, str]]]:
        score = 10
        reasons: list[str] = []
        finding_refs: list[dict[str, str]] = []
        capability_labels: list[str] = []
        ioc_values: list[str] = []
        has_obfuscation = False

        for finding in findings:
            finding_refs.append(
                {
                    "kind": "finding",
                    "id": finding.id,
                    "category": finding.category,
                }
            )
            if finding.category == "obfuscation" and not has_obfuscation:
                score += 15
                has_obfuscation = True
                reasons.append("Obfuscation indicators were detected")
            if finding.category == "capability":
                for label in finding.metadata.get("capability_labels", []):
                    if isinstance(label, str):
                        self._append_unique(capability_labels, label)
            if finding.category == "ioc":
                for value in finding.metadata.get("ioc_values", []):
                    if isinstance(value, str):
                        self._append_unique(ioc_values, value)

        for label in capability_labels:
            weight = self.CAPABILITY_WEIGHTS.get(label)
            if weight:
                score += weight
                reasons.append(f"Capability mapping flagged {label.replace('_', ' ')}")

        if ioc_values:
            score += min(15, len(ioc_values) * 5)
            reasons.append(f"IOC extraction produced {len(ioc_values)} structured indicators")

        if len(artifacts) > 1:
            score += min(10, (len(artifacts) - 1) * 5)
            reasons.append(f"Analysis expanded to {len(artifacts)} related artifacts")

        if not reasons:
            reasons.append("Only low-signal structured findings were available")

        return min(score, 100), reasons, finding_refs

    @staticmethod
    def _risk_level(score: int) -> str:
        if score >= 75:
            return "critical"
        if score >= 55:
            return "high"
        if score >= 30:
            return "medium"
        return "low"

    @staticmethod
    def _build_summary(risk_level: str) -> str:
        return f"Assigned {risk_level} risk assessment from structured findings"

    @staticmethod
    def _build_evidence(score: int, risk_level: str, reasons: list[str]) -> str:
        lines = [
            "# Risk Assessment",
            "",
            f"- Score: {score}",
            f"- Level: {risk_level}",
            "",
            "## Reasons",
            *[f"- {reason}" for reason in reasons],
        ]
        return "\n".join(lines)

    def analyze(
        self,
        *,
        root_artifact_id: str | None,
        artifact_registry: ArtifactRegistry,
        finding_store: FindingStore,
        pipeline_logger: PipelineLogger | None = None,
    ) -> list[Finding]:
        if not root_artifact_id:
            return []

        artifacts = self._collect_artifact_chain(artifact_registry, root_artifact_id)
        if not artifacts:
            return []

        included_findings: list[Finding] = []
        for artifact in artifacts:
            for finding in finding_store.get(artifact.id):
                if finding.category in {"behavior", "obfuscation", "config", "ioc", "capability", "report_synthesis"}:
                    included_findings.append(finding)

        if not included_findings:
            return []

        if pipeline_logger:
            pipeline_logger.log(
                "risk_scoring",
                "started",
                "Running risk scoring synthesis",
                artifact_id=root_artifact_id,
            )

        score, reasons, finding_refs = self._score_findings(artifacts, included_findings)
        risk_level = self._risk_level(score)
        finding = Finding(
            artifact_id=root_artifact_id,
            category="risk_assessment",
            summary=self._build_summary(risk_level),
            evidence=self._build_evidence(score, risk_level, reasons),
            confidence=0.75,
            metadata={
                "source": "RiskScoringAgent",
                "risk_score": score,
                "risk_level": risk_level,
                "reasons": reasons,
                "artifact_ids": [artifact.id for artifact in artifacts],
                "finding_refs": finding_refs,
            },
        )

        if pipeline_logger:
            pipeline_logger.log(
                "risk_scoring",
                "completed",
                "Risk scoring synthesis completed",
                artifact_id=root_artifact_id,
                finding_count=1,
            )

        return [finding]
