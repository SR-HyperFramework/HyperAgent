from __future__ import annotations

from typing import Any

from core.die_handler import AnalysisType
from core.pipeline_logger import PipelineLogger
from core.result_models import Finding


class BehaviorAnalyzerAgent:
    def _normalize_analysis_type(self, analysis_type: AnalysisType | str | None) -> str | None:
        if isinstance(analysis_type, AnalysisType):
            return analysis_type.name
        if isinstance(analysis_type, str):
            return analysis_type
        return None

    @staticmethod
    def _build_summary(report: str) -> str:
        content_lines = [
            line.strip()
            for line in report.splitlines()
            if line.strip() and not line.startswith("**Start of Analysis**") and not line.startswith("**End of Analysis**")
        ]
        if not content_lines:
            return "Behavior analysis extracted from native report"
        return content_lines[0]

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

        if pipeline_logger:
            pipeline_logger.log(
                "behavior_analyzer",
                "started",
                "Running behavior specialist analyzer",
                artifact_id=artifact_id,
            )

        finding = Finding(
            artifact_id=artifact_id,
            category="behavior",
            summary=self._build_summary(report),
            evidence=report,
            confidence=0.5,
            metadata={
                "source": "BehaviorAnalyzerAgent",
                "analysis_type": normalized_type,
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
                "behavior_analyzer",
                "completed",
                "Behavior specialist analyzer completed",
                artifact_id=artifact_id,
                finding_count=1,
            )

        return [finding]
