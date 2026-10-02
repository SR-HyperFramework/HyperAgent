"""Point-in-time progress view of one run, read from its report directory.

Both live surfaces -- the console sidebar and the browser dashboard -- render
from this one reader so they can never disagree about what a run has produced.
It only reads: ``STATE.json`` for stage status, the stage artifacts for
findings, evidence and indicators, and the deepdive/summary artifacts for a
verdict. Nothing here writes to the report directory.

Every artifact may be missing, half-written, or hand-edited while a run is in
flight, so each field is read defensively and a bad file degrades to "no data
yet" instead of raising.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from . import pipeline_state

#: Stages whose artifacts carry ``findings[].evidence[]`` in the shared
#: finding shape (see ``skill/hyperagent-static/schema.json``).
FINDING_STAGES: tuple[str, ...] = ("02-static-pass1", "03-unpack", "04-static-pass2", "05-dynamic")

IOC_GROUPS: tuple[str, ...] = ("network", "host", "persistence")

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_CHECKPOINTED = "checkpointed"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


@dataclass(frozen=True)
class StageProgress:
    stage_id: str
    skill: str
    status: str
    #: The artifact's own ``status`` field (``completed``/``partial``/``blocked``),
    #: which can be weaker than "the stage finished".
    artifact_status: str | None = None
    findings: int = 0
    evidence: int = 0
    updated_at: str | None = None


@dataclass(frozen=True)
class Indicator:
    group: str
    value: str
    source: str


@dataclass(frozen=True)
class FindingBrief:
    stage_id: str
    finding_id: str
    title: str
    status: str
    confidence: float | None
    evidence: int


@dataclass(frozen=True)
class Verdict:
    value: str
    confidence: float | None
    source: str


@dataclass(frozen=True)
class RunSnapshot:
    sha256: str
    report_dir: Path
    exists: bool
    stages: tuple[StageProgress, ...] = ()
    indicators: tuple[Indicator, ...] = ()
    findings: tuple[FindingBrief, ...] = ()
    verdict: Verdict | None = None
    last_error: str | None = None

    @property
    def completed_count(self) -> int:
        return sum(1 for stage in self.stages if stage.status == STATUS_COMPLETED)

    @property
    def evidence_total(self) -> int:
        return sum(finding.evidence for finding in self.findings)

    @property
    def has_summary(self) -> bool:
        return any(
            stage.stage_id == "09-summary" and stage.status == STATUS_COMPLETED
            for stage in self.stages
        )

    @property
    def findings_newest_first(self) -> list[FindingBrief]:
        """Latest stage's findings on top, each stage keeping its own order."""
        ordered: list[FindingBrief] = []
        for stage_id in reversed(FINDING_STAGES):
            ordered.extend(item for item in self.findings if item.stage_id == stage_id)
        return ordered

    @property
    def outcome(self) -> str:
        """``completed`` if every listed stage is, ``failed`` if one failed, else ``incomplete``."""
        if self.stages and all(stage.status == STATUS_COMPLETED for stage in self.stages):
            return STATUS_COMPLETED
        if any(stage.status == STATUS_FAILED for stage in self.stages):
            return STATUS_FAILED
        return "incomplete"

    def to_dict(self) -> dict[str, Any]:
        return {
            "sha256": self.sha256,
            "report_dir": str(self.report_dir),
            "exists": self.exists,
            "stages": [asdict(stage) for stage in self.stages],
            "indicators": [asdict(item) for item in self.indicators],
            "findings": [asdict(item) for item in self.findings],
            "verdict": asdict(self.verdict) if self.verdict else None,
            "last_error": self.last_error,
            "completed_count": self.completed_count,
            "evidence_total": self.evidence_total,
            "outcome": self.outcome,
        }


class JsonFileCache:
    """Parsed-JSON cache keyed by path and invalidated by mtime and size.

    The console re-reads a run several times a second; stage artifacts can be
    hundreds of kilobytes, so only files that actually changed get re-parsed.
    """

    def __init__(self) -> None:
        self._entries: dict[Path, tuple[tuple[int, int], Any]] = {}
        self._lock = threading.Lock()

    def load(self, path: Path) -> Any:
        try:
            stat = path.stat()
        except OSError:
            return None
        stamp = (stat.st_mtime_ns, stat.st_size)
        with self._lock:
            cached = self._entries.get(path)
        if cached is not None and cached[0] == stamp:
            return cached[1]
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Mid-write or malformed: report "nothing yet" and retry next read.
            return None
        with self._lock:
            self._entries[path] = (stamp, data)
        return data


def _object_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _artifact_path(report_dir: Path, stage_id: str, entry: dict[str, Any]) -> Path | None:
    """The stage's artifact, kept inside the report directory.

    A recorded ``output_path`` is honoured only when it resolves under
    ``report_dir``; anything else falls back to the canonical filename so a
    stray path in STATE.json cannot point the reader at an arbitrary file.
    """
    default = pipeline_state.default_output_path(report_dir, stage_id)
    recorded = entry.get("output_path")
    if isinstance(recorded, str) and recorded.strip():
        candidate = Path(pipeline_state.resolve_recorded_path(report_dir, recorded))
        try:
            candidate.resolve().relative_to(report_dir.resolve())
        except (OSError, ValueError):
            pass
        else:
            return candidate
    return Path(default) if default else None


def _stage_status(
    stage_id: str,
    state_status: str,
    *,
    active_stage_id: str | None,
    last_error: str | None,
) -> str:
    if state_status == pipeline_state.STATUS_COMPLETED:
        return STATUS_COMPLETED
    if active_stage_id is not None and stage_id == active_stage_id:
        return STATUS_RUNNING
    if last_error and last_error.startswith(f"[{stage_id}]"):
        return STATUS_FAILED
    if state_status == pipeline_state.STATUS_RUNNING:
        # STATE.json says "running" both for the live stage and for one that
        # checkpointed and is waiting to be resumed. Only a caller that knows
        # which stage is live can tell the two apart.
        return STATUS_CHECKPOINTED if active_stage_id is not None else STATUS_RUNNING
    return STATUS_PENDING


def _findings(stage_id: str, artifact: dict[str, Any]) -> list[FindingBrief]:
    briefs = []
    for index, finding in enumerate(_object_list(artifact.get("findings")), start=1):
        briefs.append(
            FindingBrief(
                stage_id=stage_id,
                finding_id=_text(finding.get("id")) or f"{stage_id}#{index}",
                title=_text(finding.get("title")) or "Untitled finding",
                status=_text(finding.get("status")) or "unknown",
                confidence=_number(finding.get("confidence")),
                evidence=len(_object_list(finding.get("evidence"))),
            )
        )
    return briefs


def _indicators_from_dynamic(artifact: dict[str, Any]) -> list[Indicator]:
    raw = artifact.get("iocs")
    if not isinstance(raw, dict):
        return []
    found = []
    for group in IOC_GROUPS:
        values = raw.get(group)
        if not isinstance(values, list):
            continue
        for value in values:
            text = _text(value)
            if text:
                found.append(Indicator(group=group, value=text, source="05-dynamic"))
    return found


def _indicators_from_summary(artifact: dict[str, Any]) -> list[Indicator]:
    raw = artifact.get("confirmed_iocs")
    if not isinstance(raw, dict):
        return []
    found = []
    for group in IOC_GROUPS:
        for item in _object_list(raw.get(group)):
            text = _text(item.get("value"))
            if text:
                found.append(Indicator(group=group, value=text, source="09-summary"))
    return found


def _verdict(artifacts: dict[str, Any]) -> Verdict | None:
    """The summary's verdict once it exists, else the deepdive's."""
    summary = artifacts.get("09-summary")
    if isinstance(summary, dict):
        block = summary.get("executive_summary")
        if isinstance(block, dict) and _text(block.get("verdict")):
            return Verdict(
                _text(block.get("verdict")) or "", _number(block.get("confidence")), "09-summary"
            )
    deepdive = artifacts.get("07-deepdive")
    if isinstance(deepdive, dict):
        block = deepdive.get("executive_assessment")
        if isinstance(block, dict) and _text(block.get("verdict")):
            return Verdict(
                _text(block.get("verdict")) or "", _number(block.get("confidence")), "07-deepdive"
            )
    return None


def load_snapshot(
    report_dir: Path,
    *,
    stage_ids: Iterable[str] | None = None,
    active_stage_id: str | None = None,
    cache: JsonFileCache | None = None,
) -> RunSnapshot:
    """Read ``report_dir`` into a :class:`RunSnapshot`.

    ``stage_ids`` limits the stage list to the ones a run actually selected
    (a profile leaves the rest ``pending`` forever, which would read as "not
    done yet"). ``active_stage_id`` is the stage a live console knows is
    executing right now: None when that is unknown, ``""`` when it is known
    that nothing is (the run has ended).
    """
    report_dir = Path(report_dir)
    cache = cache or JsonFileCache()
    state = cache.load(pipeline_state.state_path_for(report_dir))
    if not isinstance(state, dict):
        return RunSnapshot(sha256=report_dir.name, report_dir=report_dir, exists=False)

    stages_raw = state.get("stages") if isinstance(state.get("stages"), dict) else {}
    last_error = _text(state.get("last_error"))
    wanted = [
        sid for sid in (stage_ids or pipeline_state.STAGE_IDS) if sid in pipeline_state.STAGE_TABLE
    ]

    artifacts: dict[str, Any] = {}
    stages: list[StageProgress] = []
    findings: list[FindingBrief] = []
    for stage_id in pipeline_state.STAGE_IDS:
        # An artifact left behind by an earlier run of a stage this run did not
        # select is not this run's evidence, so it is not read at all.
        if stage_id not in wanted:
            continue
        entry = stages_raw.get(stage_id) if isinstance(stages_raw.get(stage_id), dict) else {}
        path = _artifact_path(report_dir, stage_id, entry)
        artifact = cache.load(path) if path is not None and path.suffix == ".json" else None
        if isinstance(artifact, dict):
            artifacts[stage_id] = artifact
        stage_findings = (
            _findings(stage_id, artifact)
            if stage_id in FINDING_STAGES and isinstance(artifact, dict)
            else []
        )
        findings.extend(stage_findings)
        stages.append(
            StageProgress(
                stage_id=stage_id,
                skill=_text(entry.get("skill"))
                or str(pipeline_state.STAGE_TABLE[stage_id]["skill"]),
                status=_stage_status(
                    stage_id,
                    str(entry.get("status") or pipeline_state.STATUS_PENDING),
                    active_stage_id=active_stage_id,
                    last_error=last_error,
                ),
                artifact_status=_text(artifact.get("status"))
                if isinstance(artifact, dict)
                else None,
                findings=len(stage_findings),
                evidence=sum(item.evidence for item in stage_findings),
                updated_at=_text(entry.get("updated_at")),
            )
        )

    # Confirmed summary indicators lead; dynamic ones fill in what the summary
    # did not carry forward (or everything, before the summary exists).
    indicators: list[Indicator] = []
    seen: set[tuple[str, str]] = set()
    for item in _indicators_from_summary(
        artifacts.get("09-summary") or {}
    ) + _indicators_from_dynamic(artifacts.get("05-dynamic") or {}):
        key = (item.group, item.value)
        if key not in seen:
            seen.add(key)
            indicators.append(item)

    return RunSnapshot(
        sha256=_text(state.get("sample_sha256")) or report_dir.name,
        report_dir=report_dir,
        exists=True,
        stages=tuple(stages),
        indicators=tuple(indicators),
        findings=tuple(findings),
        verdict=_verdict(artifacts),
        last_error=last_error,
    )
