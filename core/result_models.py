from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from core.artifact_registry import ArtifactRegistry
    from core.finding_store import FindingStore
    from core.pipeline_logger import PipelineLogger


@dataclass
class ArtifactNode:
    path: str
    sha256: str | None = None
    parent_id: str | None = None
    depth: int = 0
    kind: str = "file"
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid4().hex)


@dataclass
class Finding:
    artifact_id: str
    category: str
    summary: str
    evidence: str = ""
    confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid4().hex)


@dataclass
class AgentResult:
    artifact_id: str | None = None
    status: str = "completed"
    legacy_payload: dict[str, Any] = field(default_factory=dict)
    artifacts: list[ArtifactNode] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunContext:
    run_id: str
    root_file_path: str
    detected_type: str | None = None
    depth: int = 0
    pipeline_logger: PipelineLogger | None = None
    artifact_registry: ArtifactRegistry | None = None
    finding_store: FindingStore | None = None
