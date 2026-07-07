from __future__ import annotations

from dataclasses import dataclass, field

from core.result_models import Finding


@dataclass
class FindingStore:
    by_artifact_id: dict[str, list[Finding]] = field(default_factory=dict)

    def add(self, finding: Finding) -> Finding:
        self.by_artifact_id.setdefault(finding.artifact_id, []).append(finding)
        return finding

    def add_many(self, findings: list[Finding]) -> None:
        for finding in findings:
            self.add(finding)

    def get(self, artifact_id: str) -> list[Finding]:
        return list(self.by_artifact_id.get(artifact_id, []))

    def all(self) -> list[Finding]:
        return [finding for findings in self.by_artifact_id.values() for finding in findings]
