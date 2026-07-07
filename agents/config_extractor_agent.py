from __future__ import annotations

import re
from typing import Any

from core.die_handler import AnalysisType
from core.pipeline_logger import PipelineLogger
from core.result_models import Finding


class ConfigExtractorAgent:
    SIGNAL_PATTERNS = (
        (re.compile(r"\bconfig(?:uration)?\b", re.IGNORECASE), "config_reference"),
        (re.compile(r"\bc2\b", re.IGNORECASE), "c2"),
        (re.compile(r"\bserver(?: address)?\b", re.IGNORECASE), "server_address"),
        (re.compile(r"\bmutex\b", re.IGNORECASE), "mutex"),
        (re.compile(r"\bcampaign id\b", re.IGNORECASE), "campaign_id"),
        (re.compile(r"\bregistry path\b", re.IGNORECASE), "registry_path"),
        (re.compile(r"\bdropped path\b", re.IGNORECASE), "dropped_path"),
        (re.compile(r"\bresource\b", re.IGNORECASE), "resource"),
        (re.compile(r"\bblob\b", re.IGNORECASE), "blob"),
    )

    VALUE_PATTERNS = (
        re.compile(r"https?://[^\s'\"]+", re.IGNORECASE),
        re.compile(r"\b[a-zA-Z]:\\[^\n\r]+"),
        re.compile(r"HKEY_[A-Z_\\]+", re.IGNORECASE),
        re.compile(r"\b[a-zA-Z0-9_.-]+\.(?:com|net|org|ru|cn|xyz)\b", re.IGNORECASE),
        re.compile(r"\b[a-f0-9]{8,64}\b", re.IGNORECASE),
    )

    def _normalize_analysis_type(self, analysis_type: AnalysisType | str | None) -> str | None:
        if isinstance(analysis_type, AnalysisType):
            return analysis_type.name
        if isinstance(analysis_type, str):
            return analysis_type
        return None

    def _extract_config_items(self, report: str) -> list[str]:
        items: list[str] = []
        for pattern, label in self.SIGNAL_PATTERNS:
            if pattern.search(report) and label not in items:
                items.append(label)
        return items

    def _extract_values(self, report: str) -> list[str]:
        values: list[str] = []
        for pattern in self.VALUE_PATTERNS:
            for match in pattern.findall(report):
                value = match.strip().rstrip('.,;')
                if any(value == existing or value in existing for existing in values):
                    continue
                values = [existing for existing in values if existing not in value]
                values.append(value)
        return values[:5]

    @staticmethod
    def _build_summary(config_items: list[str], config_values: list[str]) -> str:
        if config_values:
            return f"Extracted config indicators: {', '.join(config_values[:2])}"
        if config_items:
            if len(config_items) == 1:
                return f"Detected {config_items[0].replace('_', ' ')} indicator"
            joined = ", ".join(item.replace("_", " ") for item in config_items[:2])
            if len(config_items) > 2:
                joined = f"{joined}, and more"
            return f"Detected {joined} config indicators"
        return "Detected config indicators"

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

        config_items = self._extract_config_items(report)
        config_values = self._extract_values(report)
        if not config_items and not config_values:
            return []

        if pipeline_logger:
            pipeline_logger.log(
                "config_extractor",
                "started",
                "Running config extraction specialist",
                artifact_id=artifact_id,
            )

        finding = Finding(
            artifact_id=artifact_id,
            category="config",
            summary=self._build_summary(config_items, config_values),
            evidence=report,
            confidence=0.6,
            metadata={
                "source": "ConfigExtractorAgent",
                "analysis_type": normalized_type,
                "config_items": config_items,
                "config_values": config_values,
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
                "config_extractor",
                "completed",
                "Config extraction specialist completed",
                artifact_id=artifact_id,
                finding_count=1,
            )

        return [finding]
