from __future__ import annotations

from typing import Any

from core.artifact_registry import ArtifactRegistry
from core.finding_store import FindingStore
from core.pipeline_logger import PipelineLogger
from core.result_models import Finding


class ReportSynthesizerAgent:
    INCLUDED_CATEGORIES = (
        "analysis_report",
        "behavior",
        "obfuscation",
        "config",
        "ioc",
        "capability",
    )

    @staticmethod
    def _append_unique(values: list[str], value: str) -> None:
        if value and value not in values:
            values.append(value)

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

    def _build_markdown(self, artifacts: list[Any], findings: list[Finding]) -> tuple[str, list[str], list[str], list[str]]:
        artifact_lines = [f"- `{artifact.path}` ({artifact.kind})" for artifact in artifacts]
        capability_labels: list[str] = []
        ioc_values: list[str] = []
        behavior_summaries: list[str] = []
        key_finding_lines: list[str] = []

        for finding in findings:
            if finding.category == "capability":
                for label in finding.metadata.get("capability_labels", []):
                    if isinstance(label, str):
                        self._append_unique(capability_labels, label)
            if finding.category == "ioc":
                for value in finding.metadata.get("ioc_values", []):
                    if isinstance(value, str):
                        self._append_unique(ioc_values, value)
            if finding.category == "behavior":
                self._append_unique(behavior_summaries, finding.summary)
            if finding.category in {"behavior", "obfuscation", "config", "ioc", "capability"}:
                self._append_unique(key_finding_lines, f"- {finding.category}: {finding.summary}")

        report_lines = [
            "# Final Analysis Report",
            "",
            "## Root Artifact Overview",
            f"- Total artifacts analyzed: {len(artifacts)}",
            f"- Root artifact: `{artifacts[0].path}`",
            "",
            "## Artifact Chain Summary",
            *artifact_lines,
            "",
            "## Key Behaviors and Capabilities",
        ]
        report_lines.extend(key_finding_lines or ["- No specialist findings synthesized"])
        report_lines.extend([
            "",
            "## Extracted IOCs",
        ])
        report_lines.extend([f"- {value}" for value in ioc_values] or ["- None extracted"])
        report_lines.extend([
            "",
            "## Analyst Summary",
        ])

        analyst_parts: list[str] = []
        if behavior_summaries:
            analyst_parts.append(f"Observed behaviors include {', '.join(behavior_summaries[:2])}.")
        if capability_labels:
            analyst_parts.append(
                "Capability signals map to " + ", ".join(label.replace("_", " ") for label in capability_labels) + "."
            )
        if ioc_values:
            analyst_parts.append(f"Top IOCs include {', '.join(ioc_values[:2])}.")
        report_lines.append(" ".join(analyst_parts) if analyst_parts else "No high-confidence structured findings were available.")
        return "\n".join(report_lines), capability_labels, ioc_values, behavior_summaries

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
        finding_refs: list[dict[str, str]] = []
        for artifact in artifacts:
            for finding in finding_store.get(artifact.id):
                if finding.category not in self.INCLUDED_CATEGORIES:
                    continue
                included_findings.append(finding)
                finding_refs.append({
                    "kind": "finding",
                    "id": finding.id,
                    "category": finding.category,
                })

        if not included_findings:
            return []

        if pipeline_logger:
            pipeline_logger.log(
                "report_synthesizer",
                "started",
                "Running report synthesis",
                artifact_id=root_artifact_id,
            )

        evidence, capability_labels, ioc_values, behavior_summaries = self._build_markdown(artifacts, included_findings)
        finding = Finding(
            artifact_id=root_artifact_id,
            category="report_synthesis",
            summary="Synthesized final structured report",
            evidence=evidence,
            confidence=0.8,
            metadata={
                "source": "ReportSynthesizerAgent",
                "artifact_ids": [artifact.id for artifact in artifacts],
                "finding_refs": finding_refs,
                "capability_labels": capability_labels,
                "ioc_values": ioc_values,
                "behavior_summaries": behavior_summaries,
            },
        )

        if pipeline_logger:
            pipeline_logger.log(
                "report_synthesizer",
                "completed",
                "Report synthesis completed",
                artifact_id=root_artifact_id,
                finding_count=1,
            )

        return [finding]
