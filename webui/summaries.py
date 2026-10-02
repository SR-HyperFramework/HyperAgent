"""Discovery and normalization for HyperAgent ``09-summary.json`` artifacts.

The web UI reads only the summary stage. Everything shown in the browser comes
from ``reports/<sha256>/09-summary.json`` (see the ``hyperagent-summary``
schema); no other stage file is consulted and nothing here writes to disk.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SHA256_RE = re.compile(r"^[A-Fa-f0-9]{64}$")
SUMMARY_FILENAME = "09-summary.json"

VERDICTS = ("malicious", "suspicious", "inconclusive", "unknown", "benign")
RISK_LEVELS = ("critical", "high", "medium", "low", "unknown")

# Most-severe first, so the default listing surfaces the runs an analyst
# should look at before the quiet ones.
_VERDICT_RANK = {value: index for index, value in enumerate(VERDICTS)}
_RISK_RANK = {value: index for index, value in enumerate(RISK_LEVELS)}


def is_sha256(value: str) -> bool:
    return bool(SHA256_RE.fullmatch(value))


@dataclass(frozen=True)
class RunSummary:
    """One analysis run, as far as the summary stage describes it."""

    sha256: str
    summary_path: Path
    modified_at: datetime
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    # --- convenience accessors -------------------------------------------------
    # Every field is optional at read time: the schema marks them required, but a
    # half-written or hand-edited file must render as "unknown" rather than 500.

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def short_sha(self) -> str:
        return self.sha256[:12]

    @property
    def sample(self) -> dict[str, Any]:
        return self.data.get("sample") or {}

    @property
    def executive_summary(self) -> dict[str, Any]:
        return self.data.get("executive_summary") or {}

    @property
    def classification(self) -> dict[str, Any]:
        return self.data.get("classification") or {}

    @property
    def display_name(self) -> str | None:
        """The sample's own name, or None when it adds nothing.

        Pipeline runs over a hash-named corpus set ``file_name`` to the SHA256
        itself. Printing that as a title above the hash shows the same 64
        characters twice, so callers render the hash alone instead.
        """
        name = self.sample.get("file_name")
        if not isinstance(name, str) or not name.strip():
            return None
        name = name.strip()
        return None if name.lower() == self.sha256.lower() else name

    @property
    def file_name(self) -> str:
        return self.display_name or self.short_sha

    @property
    def status(self) -> str:
        value = self.data.get("status")
        return value if isinstance(value, str) else "unknown"

    @property
    def verdict(self) -> str:
        value = self.executive_summary.get("verdict")
        return value if value in VERDICTS else "unknown"

    @property
    def risk_level(self) -> str:
        value = self.executive_summary.get("risk_level")
        return value if value in RISK_LEVELS else "unknown"

    @property
    def confidence(self) -> float | None:
        value = self.executive_summary.get("confidence")
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def confidence_percent(self) -> int:
        value = self.confidence
        return 0 if value is None else max(0, min(100, round(value * 100)))

    @property
    def confidence_label(self) -> str:
        value = self.executive_summary.get("confidence_label")
        return value if isinstance(value, str) else "unknown"

    @property
    def headline(self) -> str:
        value = self.executive_summary.get("one_sentence_summary")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return self.error or "No summary text recorded."

    @property
    def plain_language_assessment(self) -> str:
        value = self.executive_summary.get("plain_language_assessment")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return "No plain-language assessment was recorded."

    @property
    def remaining_decision_point(self) -> str | None:
        value = self.executive_summary.get("remaining_decision_point")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    @property
    def sample_sha256(self) -> str:
        value = self.sample.get("sha256")
        return value if isinstance(value, str) and value.strip() else self.sha256

    @property
    def sample_absolute_path(self) -> str | None:
        value = self.sample.get("absolute_path")
        return value if isinstance(value, str) and value.strip() else None

    @property
    def sample_architecture(self) -> str | None:
        value = self.sample.get("architecture")
        return value if isinstance(value, str) and value.strip() else None

    @property
    def sample_packing_or_protection(self) -> str | None:
        value = self.sample.get("packing_or_protection")
        return value if isinstance(value, str) and value.strip() else None

    @property
    def malware_type(self) -> str | None:
        value = self.classification.get("malware_type")
        return value if isinstance(value, str) and value.strip() else None

    @property
    def malware_family(self) -> str | None:
        value = self.classification.get("malware_family")
        return value if isinstance(value, str) and value.strip() else None

    @property
    def family_status(self) -> str:
        value = self.classification.get("family_status")
        return value if isinstance(value, str) else "not_applicable"

    @property
    def overall_assessment(self) -> str:
        value = self.classification.get("overall_assessment")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return "No classification assessment was recorded."

    def _object_list(self, key: str) -> list[dict[str, Any]]:
        value = self.data.get(key)
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    @property
    def confirmed_findings(self) -> list[dict[str, Any]]:
        return self._object_list("confirmed_findings")

    @property
    def findings_with_caveats(self) -> list[dict[str, Any]]:
        return self._object_list("findings_with_caveats")

    @property
    def not_supported_claims(self) -> list[dict[str, Any]]:
        return self._object_list("not_supported_claims")

    @property
    def recommended_actions(self) -> list[dict[str, Any]]:
        """Highest priority first; an unusable priority sorts last rather than raising."""

        def rank(item: dict[str, Any]) -> int:
            priority = item.get("priority")
            return priority if isinstance(priority, int) else 99

        return sorted(self._object_list("recommended_actions"), key=rank)

    @property
    def iocs(self) -> dict[str, list[dict[str, Any]]]:
        raw = self.data.get("confirmed_iocs")
        raw = raw if isinstance(raw, dict) else {}
        groups: dict[str, list[dict[str, Any]]] = {}
        for group in ("network", "host", "persistence"):
            value = raw.get(group)
            groups[group] = [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
        return groups

    @property
    def limitations(self) -> list[str]:
        value = self.data.get("limitations")
        return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []

    @property
    def upstream_inputs(self) -> list[str]:
        value = self.data.get("upstream_inputs")
        return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []

    @property
    def ioc_count(self) -> int:
        return sum(len(items) for items in self.iocs.values())

    @property
    def finding_counts(self) -> dict[str, int]:
        return {
            "confirmed": len(self.confirmed_findings),
            "caveated": len(self.findings_with_caveats),
            "not_supported": len(self.not_supported_claims),
            "actions": len(self.recommended_actions),
        }


def candidate_summary_paths(run_dir: Path) -> list[Path]:
    """Where a run's ``09-summary.json`` can legitimately be found.

    The nested ``<sha>/reports/<sha>/`` form is not a design choice — some
    recorded runs landed there because a stage passed a relative
    ``reports/<sha256>/...`` output path that got joined onto a report dir
    already ending in ``reports/<sha256>``. The UI reads those runs as-is
    instead of pretending they do not exist.
    """
    return [
        run_dir / SUMMARY_FILENAME,
        run_dir / "reports" / run_dir.name / SUMMARY_FILENAME,
    ]


def load_run(run_dir: Path) -> RunSummary | None:
    """Read one run directory, or return None when it holds no summary at all."""
    summary_path = next((path for path in candidate_summary_paths(run_dir) if path.is_file()), None)
    if summary_path is None:
        return None

    modified_at = datetime.fromtimestamp(summary_path.stat().st_mtime, tz=timezone.utc)

    try:
        raw = summary_path.read_text(encoding="utf-8")
    except OSError as exc:
        return RunSummary(run_dir.name, summary_path, modified_at, error=f"Unreadable file: {exc}")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return RunSummary(run_dir.name, summary_path, modified_at, error=f"Invalid JSON: {exc}")

    if not isinstance(data, dict):
        return RunSummary(
            run_dir.name, summary_path, modified_at, error="Top-level JSON value is not an object."
        )

    return RunSummary(run_dir.name, summary_path, modified_at, data=data)


def _newest(runs: Iterable[RunSummary | None]) -> RunSummary | None:
    present = [run for run in runs if run is not None]
    return max(present, key=lambda run: run.modified_at) if present else None


def _unique_dirs(dirs: Iterable[Path]) -> list[Path]:
    seen: set[str] = set()
    unique = []
    for path in dirs:
        key = os.path.normcase(os.path.abspath(path))
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def discover_runs(reports_root: Path, linked_dirs: Iterable[Path] = ()) -> list[RunSummary]:
    """All runs, most recently updated first.

    Runs are the ``<sha256>`` folders under ``reports_root`` plus *linked_dirs*
    (report folders recorded in the run index, wherever they live). When one
    sample was analysed into several folders, the newest summary wins.
    """
    candidates: list[Path] = []
    if reports_root.is_dir():
        candidates.extend(
            child for child in reports_root.iterdir() if child.is_dir() and is_sha256(child.name)
        )
    candidates.extend(path for path in linked_dirs if is_sha256(path.name))

    by_sha: dict[str, RunSummary] = {}
    for run_dir in _unique_dirs(candidates):
        run = load_run(run_dir)
        if run is None:
            continue
        key = run.sha256.lower()
        best = _newest([by_sha.get(key), run])
        if best is not None:
            by_sha[key] = best

    return sorted(by_sha.values(), key=lambda run: run.modified_at, reverse=True)


def get_run(
    reports_root: Path, sha256: str, linked_dirs: Iterable[Path] = ()
) -> RunSummary | None:
    """One run by hash. Rejects anything that is not a bare SHA256."""
    if not is_sha256(sha256):
        return None
    sha256 = sha256.lower()
    candidates = [reports_root / sha256]
    candidates.extend(path for path in linked_dirs if path.name.lower() == sha256)
    return _newest(load_run(path) for path in _unique_dirs(candidates))


def _matches_query(run: RunSummary, needle: str) -> bool:
    haystack = " ".join(
        part
        for part in (
            run.sha256,
            run.file_name,
            run.headline,
            str(run.sample.get("absolute_path") or ""),
            str(run.classification.get("malware_type") or ""),
            str(run.classification.get("malware_family") or ""),
        )
        if part
    )
    return needle in haystack.lower()


def filter_runs(
    runs: Iterable[RunSummary],
    *,
    query: str = "",
    verdict: str = "",
    risk: str = "",
) -> list[RunSummary]:
    needle = query.strip().lower()
    selected = []
    for run in runs:
        if verdict and run.verdict != verdict:
            continue
        if risk and run.risk_level != risk:
            continue
        if needle and not _matches_query(run, needle):
            continue
        selected.append(run)
    return selected


def sort_runs(runs: list[RunSummary], key: str) -> list[RunSummary]:
    if key == "verdict":
        return sorted(runs, key=lambda run: (_VERDICT_RANK.get(run.verdict, 99), run.sha256))
    if key == "risk":
        return sorted(runs, key=lambda run: (_RISK_RANK.get(run.risk_level, 99), run.sha256))
    if key == "confidence":
        return sorted(runs, key=lambda run: run.confidence_percent, reverse=True)
    if key == "name":
        return sorted(runs, key=lambda run: run.file_name.lower())
    return sorted(runs, key=lambda run: run.modified_at, reverse=True)


def overview(runs: list[RunSummary]) -> dict[str, Any]:
    """Counts for the dashboard strip on the index page."""
    by_verdict = {value: 0 for value in VERDICTS}
    by_risk = {value: 0 for value in RISK_LEVELS}
    unreadable = 0
    for run in runs:
        if not run.ok:
            unreadable += 1
            continue
        by_verdict[run.verdict] = by_verdict.get(run.verdict, 0) + 1
        by_risk[run.risk_level] = by_risk.get(run.risk_level, 0) + 1
    return {
        "total": len(runs),
        "unreadable": unreadable,
        "by_verdict": by_verdict,
        "by_risk": by_risk,
    }
