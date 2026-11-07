"""Ground-truth database and output evaluation for HyperAgent research.

This module provides the infrastructure needed to measure detection quality
(Precision, Recall, F1, FPR) by comparing pipeline output JSON files against
a hand-labeled or bootstrapped ground-truth corpus.

Ground-truth format (one JSON object per line in ``ground_truth.jsonl``):

.. code-block:: json

    {
      "sha256": "deadbeef...",
      "family": "AsyncRAT",
      "iocs": {
        "ips": ["1.2.3.4"],
        "domains": ["evil.com"],
        "hashes": ["aabbcc..."],
        "registry_keys": ["HKCU\\\\Software\\\\Run\\\\malware"]
      },
      "behaviors": ["process_injection", "persistence_registry", "c2_beaconing"],
      "capabilities": ["keylogging", "screenshot"],
      "verdict": "malicious",
      "risk_score_range": [80, 100],
      "static_indicators": {
        "packed": true,
        "imports": ["VirtualAlloc", "CreateRemoteThread"],
        "sections_anomalous": [".text"]
      },
      "dynamic_indicators": {
        "api_sequences": ["OpenProcess -> VirtualAllocEx -> WriteProcessMemory"],
        "network_patterns": ["beacon_interval_60s"],
        "dropped_files": []
      }
    }
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class GroundTruthRecord:
    """Labeled reference data for one malware sample."""

    sha256: str
    family: str = ""
    verdict: str = "malicious"
    risk_score_range: tuple[int, int] = (0, 100)

    # Indicators of Compromise
    ioc_ips: list[str] = field(default_factory=list)
    ioc_domains: list[str] = field(default_factory=list)
    ioc_hashes: list[str] = field(default_factory=list)
    ioc_registry_keys: list[str] = field(default_factory=list)

    # Behavioral categories (from dynamic stage)
    behaviors: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)

    # Static indicators
    packed: bool | None = None
    anomalous_imports: list[str] = field(default_factory=list)
    anomalous_sections: list[str] = field(default_factory=list)

    # Dynamic indicators
    api_sequences: list[str] = field(default_factory=list)
    network_patterns: list[str] = field(default_factory=list)


@dataclass
class StageEvalResult:
    """Evaluation result for one stage's output against ground truth."""

    stage_id: str
    sha256: str

    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0

    matched_items: list[str] = field(default_factory=list)
    """Human-readable list of correctly identified items."""

    missed_items: list[str] = field(default_factory=list)
    """Items present in ground truth but not in pipeline output."""

    spurious_items: list[str] = field(default_factory=list)
    """Items in pipeline output that are not in ground truth (FP candidates)."""

    @property
    def precision(self) -> float:
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom > 0 else 0.0

    @property
    def recall(self) -> float:
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom > 0 else 0.0

    @property
    def f1_score(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0


# ---------------------------------------------------------------------------
# Ground-truth database
# ---------------------------------------------------------------------------

class GroundTruthDatabase:
    """Loads and provides access to labeled ground-truth records.

    Records are stored one JSON object per line in a ``.jsonl`` file.

    Usage::

        db = GroundTruthDatabase.from_jsonl(Path("data/ground_truth.jsonl"))
        record = db.get("deadbeef...")
        result = evaluate_stage_output("05-dynamic", output_json, record)
    """

    def __init__(self, records: dict[str, GroundTruthRecord]) -> None:
        self._records = records

    @classmethod
    def from_jsonl(cls, path: Path) -> "GroundTruthDatabase":
        """Load ground-truth records from a JSONL file."""
        records: dict[str, GroundTruthRecord] = {}
        if not path.exists():
            logger.warning("Ground-truth file not found: %s", path)
            return cls(records)

        with path.open(encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    obj = json.loads(line)
                    record = _parse_record(obj)
                    records[record.sha256] = record
                except Exception as exc:
                    logger.warning("ground_truth.jsonl line %d parse error: %s", lineno, exc)

        logger.info("Loaded %d ground-truth records from %s", len(records), path)
        return cls(records)

    def get(self, sha256: str) -> GroundTruthRecord | None:
        """Return the ground-truth record for *sha256*, or ``None``."""
        return self._records.get(sha256.lower())

    def __len__(self) -> int:
        return len(self._records)

    def __contains__(self, sha256: str) -> bool:
        return sha256.lower() in self._records


def _parse_record(obj: dict[str, Any]) -> GroundTruthRecord:
    """Parse a raw dict from JSONL into a ``GroundTruthRecord``."""
    iocs = obj.get("iocs", {})
    static = obj.get("static_indicators", {})
    dynamic = obj.get("dynamic_indicators", {})
    risk = obj.get("risk_score_range", [0, 100])

    return GroundTruthRecord(
        sha256=obj["sha256"].lower(),
        family=obj.get("family", ""),
        verdict=obj.get("verdict", "malicious"),
        risk_score_range=(risk[0], risk[1]),
        ioc_ips=iocs.get("ips", []),
        ioc_domains=iocs.get("domains", []),
        ioc_hashes=iocs.get("hashes", []),
        ioc_registry_keys=iocs.get("registry_keys", []),
        behaviors=obj.get("behaviors", []),
        capabilities=obj.get("capabilities", []),
        packed=static.get("packed"),
        anomalous_imports=static.get("imports", []),
        anomalous_sections=static.get("sections_anomalous", []),
        api_sequences=dynamic.get("api_sequences", []),
        network_patterns=dynamic.get("network_patterns", []),
    )


# ---------------------------------------------------------------------------
# Evaluation functions
# ---------------------------------------------------------------------------

def evaluate_stage_output(
    stage_id: str,
    stage_output: dict[str, Any],
    ground_truth: GroundTruthRecord,
) -> StageEvalResult:
    """Evaluate a stage's JSON output against the ground-truth record.

    Dispatches to a stage-specific evaluation function based on *stage_id*.
    For unknown stages, falls back to the generic IOC evaluator.

    Parameters
    ----------
    stage_id:
        Pipeline stage identifier (e.g. ``"05-dynamic"``).
    stage_output:
        The parsed JSON object produced by the pipeline stage.
    ground_truth:
        The labeled reference record for this sample.

    Returns
    -------
    StageEvalResult with TP/FP/FN counts and item lists.
    """
    evaluators = {
        "02-static-pass1": _eval_static,
        "04-static-pass2": _eval_static,
        "05-dynamic":       _eval_dynamic,
        "07-deepdive":      _eval_deepdive,
        "08-report":        _eval_report,
    }
    fn = evaluators.get(stage_id, _eval_iocs_generic)
    return fn(stage_id, stage_output, ground_truth)


# -- Stage-specific evaluators ------------------------------------------------

def _eval_static(
    stage_id: str,
    output: dict[str, Any],
    gt: GroundTruthRecord,
) -> StageEvalResult:
    """Evaluate static analysis output (stages 02 and 04)."""
    result = StageEvalResult(stage_id=stage_id, sha256=gt.sha256)

    # Check predicted imports against ground-truth anomalous imports
    predicted_imports: list[str] = _extract_list(output, "imports", "suspicious_imports",
                                                   "notable_imports")
    tp_imports, fp_imports, fn_imports = _match_items(
        predicted_imports, gt.anomalous_imports, match_fn=_fuzzy_contains
    )
    result.true_positives += tp_imports
    result.false_positives += fp_imports
    result.false_negatives += fn_imports

    # Check packing verdict
    predicted_packed = _extract_bool(output, "packed", "is_packed", "packer_detected")
    if predicted_packed is not None and gt.packed is not None:
        if predicted_packed == gt.packed:
            result.true_positives += 1
            result.matched_items.append(f"packed={gt.packed}")
        else:
            result.false_positives += 1
            result.spurious_items.append(f"packed={predicted_packed} (gt={gt.packed})")

    # IOC hashes
    ioc_result = _eval_iocs_generic(stage_id, output, gt)
    result.true_positives += ioc_result.true_positives
    result.false_positives += ioc_result.false_positives
    result.false_negatives += ioc_result.false_negatives

    return result


def _eval_dynamic(
    stage_id: str,
    output: dict[str, Any],
    gt: GroundTruthRecord,
) -> StageEvalResult:
    """Evaluate dynamic analysis output (stage 05)."""
    result = StageEvalResult(stage_id=stage_id, sha256=gt.sha256)

    # Behaviors
    predicted_behaviors = _extract_list(output, "behaviors", "behavioral_indicators",
                                         "behavior_categories")
    tp, fp, fn = _match_items(predicted_behaviors, gt.behaviors, match_fn=_fuzzy_contains)
    _add_items_to_result(result, tp, fp, fn, predicted_behaviors, gt.behaviors)

    # Capabilities
    predicted_caps = _extract_list(output, "capabilities", "capability_tags")
    tp, fp, fn = _match_items(predicted_caps, gt.capabilities, match_fn=_fuzzy_contains)
    result.true_positives += tp
    result.false_positives += fp
    result.false_negatives += fn

    # Network IOCs
    ioc_result = _eval_iocs_generic(stage_id, output, gt)
    result.true_positives += ioc_result.true_positives
    result.false_positives += ioc_result.false_positives
    result.false_negatives += ioc_result.false_negatives

    return result


def _eval_deepdive(
    stage_id: str,
    output: dict[str, Any],
    gt: GroundTruthRecord,
) -> StageEvalResult:
    """Evaluate deep-dive attribution output (stage 07)."""
    result = StageEvalResult(stage_id=stage_id, sha256=gt.sha256)

    predicted_family = _extract_str(output, "malware_family", "family", "attribution")
    if gt.family and predicted_family:
        if _fuzzy_contains(predicted_family, gt.family):
            result.true_positives += 1
            result.matched_items.append(f"family={gt.family}")
        else:
            result.false_positives += 1
            result.spurious_items.append(f"family={predicted_family} (gt={gt.family})")
            result.false_negatives += 1
            result.missed_items.append(f"family={gt.family}")

    return result


def _eval_report(
    stage_id: str,
    output: dict[str, Any],
    gt: GroundTruthRecord,
) -> StageEvalResult:
    """Evaluate final report output (stage 08) — comprehensive IOC + verdict check."""
    result = StageEvalResult(stage_id=stage_id, sha256=gt.sha256)

    # Verdict
    predicted_verdict = _extract_str(output, "verdict", "classification", "final_verdict")
    if predicted_verdict:
        if _fuzzy_contains(predicted_verdict, gt.verdict):
            result.true_positives += 1
            result.matched_items.append(f"verdict={gt.verdict}")
        else:
            result.false_positives += 1
            result.spurious_items.append(f"verdict={predicted_verdict}")

    # Risk score in range
    predicted_score = _extract_int(output, "risk_score", "severity_score", "threat_score")
    if predicted_score is not None:
        lo, hi = gt.risk_score_range
        if lo <= predicted_score <= hi:
            result.true_positives += 1
            result.matched_items.append(f"risk_score={predicted_score} in [{lo},{hi}]")
        else:
            result.false_positives += 1
            result.spurious_items.append(f"risk_score={predicted_score} out of [{lo},{hi}]")

    # All IOCs in final report
    ioc_result = _eval_iocs_generic(stage_id, output, gt)
    result.true_positives += ioc_result.true_positives
    result.false_positives += ioc_result.false_positives
    result.false_negatives += ioc_result.false_negatives
    result.matched_items.extend(ioc_result.matched_items)
    result.missed_items.extend(ioc_result.missed_items)
    result.spurious_items.extend(ioc_result.spurious_items)

    return result


def _eval_iocs_generic(
    stage_id: str,
    output: dict[str, Any],
    gt: GroundTruthRecord,
) -> StageEvalResult:
    """Generic IOC evaluation: IPs, domains, hashes, registry keys."""
    result = StageEvalResult(stage_id=stage_id, sha256=gt.sha256)

    def _check(predicted: list[str], reference: list[str], label: str) -> None:
        tp, fp, fn = _match_items(predicted, reference, match_fn=_exact_lower)
        result.true_positives += tp
        result.false_positives += fp
        result.false_negatives += fn
        for item in predicted[:tp]:
            result.matched_items.append(f"{label}:{item}")
        for item in reference[tp:]:
            result.missed_items.append(f"{label}:{item}")

    predicted_ips     = _extract_ioc_list(output, "ip", "c2_ips", "ips")
    predicted_domains = _extract_ioc_list(output, "domain", "c2_domains", "domains")
    predicted_hashes  = _extract_ioc_list(output, "hash", "file_hashes", "hashes")
    predicted_keys    = _extract_ioc_list(output, "registry", "registry_keys", "reg_keys")

    _check(predicted_ips,     gt.ioc_ips,           "ip")
    _check(predicted_domains, gt.ioc_domains,        "domain")
    _check(predicted_hashes,  gt.ioc_hashes,         "hash")
    _check(predicted_keys,    gt.ioc_registry_keys,  "registry")

    return result


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------

def _match_items(
    predicted: list[str],
    reference: list[str],
    match_fn=None,
) -> tuple[int, int, int]:
    """Compute TP/FP/FN by greedy matching predicted against reference.

    Returns
    -------
    (true_positives, false_positives, false_negatives)
    """
    if match_fn is None:
        match_fn = _exact_lower

    ref_remaining = list(reference)
    tp = 0

    for pred in predicted:
        for i, ref in enumerate(ref_remaining):
            if match_fn(pred, ref):
                tp += 1
                ref_remaining.pop(i)
                break

    fp = len(predicted) - tp
    fn = len(ref_remaining)
    return tp, fp, fn


def _exact_lower(a: str, b: str) -> bool:
    return a.strip().lower() == b.strip().lower()


def _fuzzy_contains(a: str, b: str) -> bool:
    """True if either string contains the other (case-insensitive)."""
    a_norm = a.strip().lower()
    b_norm = b.strip().lower()
    return a_norm in b_norm or b_norm in a_norm


def _add_items_to_result(
    result: StageEvalResult,
    tp: int,
    fp: int,
    fn: int,
    predicted: list[str],
    reference: list[str],
) -> None:
    result.true_positives += tp
    result.false_positives += fp
    result.false_negatives += fn
    result.matched_items.extend(predicted[:tp])
    result.missed_items.extend(reference[tp:])
    result.spurious_items.extend(predicted[tp:])


# ---------------------------------------------------------------------------
# JSON extraction helpers (tolerant key lookup)
# ---------------------------------------------------------------------------

def _extract_list(obj: dict[str, Any], *keys: str) -> list[str]:
    for k in keys:
        val = _deep_get(obj, k)
        if isinstance(val, list):
            return [str(v) for v in val if v]
    return []


def _extract_ioc_list(obj: dict[str, Any], *keywords: str) -> list[str]:
    """Extract IOC list by searching for keys containing any of the keywords."""
    results: list[str] = []
    for key, val in _flatten(obj):
        if any(kw in key.lower() for kw in keywords):
            if isinstance(val, list):
                results.extend(str(v) for v in val if v)
            elif isinstance(val, str) and val:
                results.append(val)
    return list(set(results))  # deduplicate


def _extract_str(obj: dict[str, Any], *keys: str) -> str:
    for k in keys:
        val = _deep_get(obj, k)
        if isinstance(val, str) and val:
            return val
    return ""


def _extract_int(obj: dict[str, Any], *keys: str) -> int | None:
    for k in keys:
        val = _deep_get(obj, k)
        if isinstance(val, (int, float)):
            return int(val)
    return None


def _extract_bool(obj: dict[str, Any], *keys: str) -> bool | None:
    for k in keys:
        val = _deep_get(obj, k)
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            if val.lower() in ("true", "yes", "1"):
                return True
            if val.lower() in ("false", "no", "0"):
                return False
    return None


def _deep_get(obj: dict[str, Any], key: str) -> Any:
    """Recursively search for *key* in a nested dict (breadth-first)."""
    if key in obj:
        return obj[key]
    for v in obj.values():
        if isinstance(v, dict):
            found = _deep_get(v, key)
            if found is not None:
                return found
    return None


def _flatten(
    obj: Any,
    prefix: str = "",
) -> list[tuple[str, Any]]:
    """Flatten nested dict to (dotted_key, value) pairs."""
    items: list[tuple[str, Any]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            full = f"{prefix}.{k}" if prefix else k
            items.extend(_flatten(v, full))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            items.extend(_flatten(v, f"{prefix}[{i}]"))
    else:
        items.append((prefix, obj))
    return items
