from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.die_handler import AnalysisType, DIEHandler


@dataclass
class FileClassification:
    die_data: dict[str, Any]
    analysis_type: AnalysisType


class FileClassifierAgent:
    def __init__(self, config_path: str = "config.yaml", die_handler: DIEHandler | None = None):
        self.die_handler = die_handler or DIEHandler(config_path)

    def identify(self, file_path: str) -> tuple[dict[str, Any], AnalysisType]:
        return self.die_handler.identify(file_path)

    def analyze(self, file_path: str) -> FileClassification:
        die_data, analysis_type = self.identify(file_path)
        return FileClassification(die_data=die_data, analysis_type=analysis_type)
