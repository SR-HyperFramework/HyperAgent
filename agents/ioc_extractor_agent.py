from __future__ import annotations

import re
from typing import Any

from core.die_handler import AnalysisType
from core.pipeline_logger import PipelineLogger
from core.result_models import Finding


class IOCExtractorAgent:
    IOC_PATTERNS = (
        (
            "url",
            re.compile(r"https?://[^\s'\"<>]+", re.IGNORECASE),
        ),
        (
            "ip_address",
            re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b"),
        ),
        (
            "registry_key",
            re.compile(r"\bHKEY_[A-Z0-9_]+(?:\\[^\s'\",;]+)+", re.IGNORECASE),
        ),
        (
            "file_path",
            re.compile(r"\b[a-zA-Z]:\\(?:[^\\/:*?\"<>|\r\n ]+\\)*[^\\/:*?\"<>|\r\n ]+"),
        ),
        (
            "domain",
            re.compile(
                r"\b(?!(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b)(?:[a-zA-Z0-9-]+\.)+(?:com|net|org|ru|cn|xyz|biz|info|io)\b",
                re.IGNORECASE,
            ),
        ),
    )
    MUTEX_PATTERNS = (
        re.compile(r"\bmutex(?: name)?\b\s*[:=]?\s*([A-Za-z0-9_./\\:-]{3,})", re.IGNORECASE),
        re.compile(r"\bnamed mutex\b\s*[:=]?\s*([A-Za-z0-9_./\\:-]{3,})", re.IGNORECASE),
    )

    def _normalize_analysis_type(self, analysis_type: AnalysisType | str | None) -> str | None:
        if isinstance(analysis_type, AnalysisType):
            return analysis_type.name
        if isinstance(analysis_type, str):
            return analysis_type
        return None

    @staticmethod
    def _normalize_value(value: str) -> str:
        return value.strip().rstrip('.,;')

    def _append_value(self, values: list[str], value: str) -> bool:
        normalized_value = self._normalize_value(value)
        lowered_value = normalized_value.lower()
        for existing in values:
            lowered_existing = existing.lower()
            if lowered_value == lowered_existing or lowered_value in lowered_existing:
                return False
        values[:] = [existing for existing in values if existing.lower() not in lowered_value]
        values.append(normalized_value)
        return True

    def _extract_iocs(self, report: str) -> tuple[list[str], list[str]]:
        items: list[str] = []
        values: list[str] = []
        for label, pattern in self.IOC_PATTERNS:
            found = False
            for match in pattern.findall(report):
                if self._append_value(values, match):
                    found = True
            if found:
                items.append(label)
        mutex_found = False
        for pattern in self.MUTEX_PATTERNS:
            for match in pattern.findall(report):
                if self._append_value(values, match):
                    mutex_found = True
        if mutex_found:
            items.append("mutex")
        return items, values[:8]

    @staticmethod
    def _build_summary(ioc_items: list[str], ioc_values: list[str]) -> str:
        if ioc_values:
            return f"Extracted IOCs: {', '.join(ioc_values[:2])}"
        if ioc_items:
            if len(ioc_items) == 1:
                return f"Detected {ioc_items[0].replace('_', ' ')} indicator"
            joined = ", ".join(item.replace("_", " ") for item in ioc_items[:2])
            if len(ioc_items) > 2:
                joined = f"{joined}, and more"
            return f"Detected {joined} IOC indicators"
        return "Detected IOC indicators"

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

        ioc_items, ioc_values = self._extract_iocs(report)
        if not ioc_items and not ioc_values:
            return []

        if pipeline_logger:
            pipeline_logger.log(
                "ioc_extractor",
                "started",
                "Running IOC extraction specialist",
                artifact_id=artifact_id,
            )

        finding = Finding(
            artifact_id=artifact_id,
            category="ioc",
            summary=self._build_summary(ioc_items, ioc_values),
            evidence=report,
            confidence=0.7,
            metadata={
                "source": "IOCExtractorAgent",
                "analysis_type": normalized_type,
                "ioc_items": ioc_items,
                "ioc_values": ioc_values,
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
                "ioc_extractor",
                "completed",
                "IOC extraction specialist completed",
                artifact_id=artifact_id,
                finding_count=1,
            )

        return [finding]
