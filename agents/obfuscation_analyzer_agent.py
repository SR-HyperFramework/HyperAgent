from __future__ import annotations

from typing import Any

from core.die_handler import AnalysisType
from core.pipeline_logger import PipelineLogger
from core.result_models import Finding


class ObfuscationAnalyzerAgent:
    KEYWORD_LABELS = (
        ("packed", "packer"),
        ("packer", "packer"),
        ("loader", "loader"),
        ("string encryption", "string_encryption"),
        ("encrypted strings", "string_encryption"),
        ("reflection", "reflection"),
        ("dynamic resolve", "dynamic_resolution"),
        ("dynamic import", "dynamic_resolution"),
        ("import hashing", "import_hashing"),
        ("decompress", "decompression"),
        ("self-modifying", "self_modifying_code"),
    )

    def _normalize_analysis_type(self, analysis_type: AnalysisType | str | None) -> str | None:
        if isinstance(analysis_type, AnalysisType):
            return analysis_type.name
        if isinstance(analysis_type, str):
            return analysis_type
        return None

    def _extract_labels(self, report: str) -> list[str]:
        lowered = report.lower()
        labels: list[str] = []
        for keyword, label in self.KEYWORD_LABELS:
            if keyword in lowered and label not in labels:
                labels.append(label)
        return labels

    @staticmethod
    def _build_summary(labels: list[str]) -> str:
        if not labels:
            return "Obfuscation indicators detected"
        if len(labels) == 1:
            return f"Detected {labels[0].replace('_', ' ')} indicators"
        joined = ", ".join(label.replace("_", " ") for label in labels[:2])
        if len(labels) > 2:
            joined = f"{joined}, and more"
        return f"Detected {joined} obfuscation indicators"

    def analyze(
        self,
        *,
        artifact_id: str | None,
        analysis_type: AnalysisType | str | None,
        analysis_data: Any,
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

        labels = self._extract_labels(report)
        if not labels:
            return []

        if pipeline_logger:
            pipeline_logger.log(
                "obfuscation_analyzer",
                "started",
                "Running obfuscation specialist analyzer",
                artifact_id=artifact_id,
            )

        finding = Finding(
            artifact_id=artifact_id,
            category="obfuscation",
            summary=self._build_summary(labels),
            evidence=report,
            confidence=0.6,
            metadata={
                "source": "ObfuscationAnalyzerAgent",
                "analysis_type": normalized_type,
                "labels": labels,
                "evidence_refs": [
                    {
                        "kind": "legacy_payload_field",
                        "field": "ai_analysis_report",
                    }
                ],
            },
        )

        if pipeline_logger:
            pipeline_logger.log(
                "obfuscation_analyzer",
                "completed",
                "Obfuscation specialist analyzer completed",
                artifact_id=artifact_id,
                finding_count=1,
            )

        return [finding]
