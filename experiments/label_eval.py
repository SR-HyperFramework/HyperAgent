"""Score existing HyperAgent verdicts against DikeDataset labels.

Read-only: this never runs the pipeline. It walks one or more report roots
(``<root>/<sha256>/09-summary.json``), joins each verdict to the official
DikeDataset ``labels/benign.csv`` / ``labels/malware.csv`` by SHA256, and
writes a per-sample CSV, a metrics JSON and a Markdown report.

Scoring choices that the older evaluators left implicit are made explicit here:

* The verdict is read only from ``executive_summary.verdict`` (the field the
  summary schema defines), never from a recursive search that could pick up a
  ``verdict`` key nested inside a finding.
* ``inconclusive`` / ``unknown`` are abstentions. They are never scored as
  benign. Metrics are reported twice: over decided samples only (with
  coverage) and with every abstention counted as an error.
* Two decision policies: ``lenient`` treats ``suspicious`` as positive (the
  convention used by batch_eval and the report), ``strict`` counts only
  ``malicious`` as positive.

Every row also carries validity flags, because a correct verdict is not
evidence if the run could see the label:

* ``intel_present`` -- 06-intel ran. DikeDataset labels are VirusTotal AV
  consensus, and 06-intel reads VirusTotal, so the verdict may restate the label.
* ``reused`` -- the condition's progress.jsonl shows zero tokens and zero
  stages for the sample, i.e. an older 09-summary was read back, not produced.
* ``path_reveals_label`` -- the sample sits in a directory whose name encodes
  the class (``files/b`` vs ``files/m``); the absolute path is in every prompt.

``controlled`` = neither intel nor reused; ``blind`` = controlled and the path
does not reveal the label either. Report numbers from ``controlled`` and state
the path exposure as a limitation until a ``blind`` rerun exists.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import re
import sys
from dataclasses import asdict, dataclass
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
DEFAULT_LABELS_DIR = Path("H:/Dataset/labels")
DEFAULT_OUTPUT_DIR = ROOT / "results" / "label_eval"
SUMMARY_FILE = "09-summary.json"
INTEL_FILE = "06-intel.json"

LABEL_MALWARE = "malware"
LABEL_BENIGN = "benign"
CATEGORY_COLUMNS = ("generic", "trojan", "ransomware", "worm", "backdoor",
                    "spyware", "rootkit", "encrypter", "downloader")
#: Malware rows below this AV-consensus score are reported as borderline.
BORDERLINE_MALICE = 0.8

VERDICTS = ("malicious", "suspicious", "benign", "inconclusive", "unknown")
ABSTAIN = frozenset({"inconclusive", "unknown"})
POLICIES = {
    "lenient": frozenset({"malicious", "suspicious"}),
    "strict": frozenset({"malicious"}),
}
#: Directory names that encode the class when they appear as the sample's parent.
LABEL_HINT_DIRS = frozenset({"b", "m", "benign", "malware", "malicious", "goodware", "clean"})
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Label:
    label: str
    malice: float
    category: str  # argmax of the per-category scores; "" for benign


def load_labels(labels_dir: Path) -> dict[str, Label]:
    """Load DikeDataset labels keyed by lowercase SHA256.

    A hash listed in both files is dropped with a warning rather than guessed.
    """
    labels: dict[str, Label] = {}
    conflicts: set[str] = set()
    for file_name, label in (("benign.csv", LABEL_BENIGN), ("malware.csv", LABEL_MALWARE)):
        path = Path(labels_dir) / file_name
        with path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                sha = row["hash"].strip().lower()
                scores = {c: float(row.get(c) or 0.0) for c in CATEGORY_COLUMNS}
                category = max(scores, key=scores.get) if label == LABEL_MALWARE else ""
                record = Label(label, float(row.get("malice") or 0.0), category)
                if sha in labels and labels[sha].label != label:
                    conflicts.add(sha)
                labels[sha] = record
    for sha in conflicts:
        logger.warning("Hash %s is in both benign.csv and malware.csv; excluded", sha)
        labels.pop(sha, None)
    return labels


# ---------------------------------------------------------------------------
# Per-sample extraction
# ---------------------------------------------------------------------------

@dataclass
class SampleRow:
    condition: str
    sha256: str
    label: str
    malice: float | None
    category: str
    verdict: str
    confidence: float | None
    risk_level: str
    summary_status: str
    intel_present: bool
    reused: bool
    path_reveals_label: bool
    controlled: bool
    blind: bool
    score: float | None
    one_sentence_summary: str
    error: str


def _load_progress(condition_dir: Path) -> dict[str, dict[str, Any]]:
    """Last progress.jsonl row per SHA256, if the condition has one."""
    rows: dict[str, dict[str, Any]] = {}
    path = condition_dir / "progress.jsonl"
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        sha = str(row.get("sample_sha256", "")).lower()
        if sha:
            rows[sha] = row
    return rows


def _is_reused(progress_row: dict[str, Any] | None) -> bool:
    if not progress_row or progress_row.get("error"):
        return False
    return not progress_row.get("input_tokens") and not progress_row.get("stage_count")


def _path_reveals_label(absolute_path: str | None) -> bool:
    if not absolute_path:
        return False
    parts = re.split(r"[\\/]+", absolute_path.strip())
    return len(parts) >= 2 and parts[-2].lower() in LABEL_HINT_DIRS


def verdict_score(verdict: str, confidence: float | None) -> float | None:
    """Map a verdict and its confidence onto [0, 1], higher = more malicious.

    Only the ordering matters for AUC: confident benign < hesitant benign <
    abstention < suspicious < malicious. Brier score does depend on the exact
    values, so it is reported as a heuristic calibration check, not a claim.
    """
    if verdict not in VERDICTS:
        return None
    c = 0.5 if confidence is None else min(max(float(confidence), 0.0), 1.0)
    return {
        "malicious": 0.5 + 0.5 * c,
        "suspicious": 0.5 + 0.25 * c,
        "benign": 0.5 - 0.5 * c,
    }.get(verdict, 0.5)


def read_sample(condition: str, report_dir: Path, labels: dict[str, Label],
                progress: dict[str, dict[str, Any]]) -> SampleRow:
    sha = report_dir.name.lower()
    label = labels.get(sha)
    verdict, confidence, risk, status, summary, error = "", None, "", "", "", ""
    absolute_path = None
    try:
        payload = json.loads((report_dir / SUMMARY_FILE).read_text(encoding="utf-8"))
        executive = payload.get("executive_summary") or {}
        verdict = str(executive.get("verdict") or "").strip().lower()
        confidence = executive.get("confidence")
        risk = str(executive.get("risk_level") or "")
        status = str(payload.get("status") or "")
        summary = str(executive.get("one_sentence_summary") or "")
        absolute_path = (payload.get("sample") or {}).get("absolute_path")
        if verdict not in VERDICTS:
            error = f"verdict not in schema enum: {verdict!r}"
    except FileNotFoundError:
        error = f"no {SUMMARY_FILE}"
    except (OSError, json.JSONDecodeError, AttributeError) as exc:
        error = f"unreadable {SUMMARY_FILE}: {type(exc).__name__}"

    intel = (report_dir / INTEL_FILE).exists()
    reused = _is_reused(progress.get(sha))
    reveals = _path_reveals_label(absolute_path)
    return SampleRow(
        condition=condition,
        sha256=sha,
        label=label.label if label else "unlabeled",
        malice=label.malice if label else None,
        category=label.category if label else "",
        verdict=verdict,
        confidence=float(confidence) if isinstance(confidence, (int, float)) else None,
        risk_level=risk,
        summary_status=status,
        intel_present=intel,
        reused=reused,
        path_reveals_label=reveals,
        controlled=not (error or intel or reused),
        blind=not (error or intel or reused or reveals),
        score=None if error else verdict_score(verdict, confidence),
        one_sentence_summary=summary,
        error=error,
    )


def collect(conditions: dict[str, Path], labels: dict[str, Label]) -> list[SampleRow]:
    """Read every verdict under each root.

    Samples the condition's progress.jsonl planned but that have no
    09-summary.json become error rows, so a run that silently lost samples
    cannot look better than one that kept them.
    """
    rows: list[SampleRow] = []
    for name, reports_root in conditions.items():
        progress = _load_progress(reports_root.parent)
        seen: set[str] = set()
        for report_dir in sorted(p for p in reports_root.iterdir() if p.is_dir()):
            if SHA256_RE.match(report_dir.name.lower()) and (report_dir / SUMMARY_FILE).exists():
                rows.append(read_sample(name, report_dir, labels, progress))
                seen.add(report_dir.name.lower())
        for sha in sorted(set(progress) - seen):
            rows.append(read_sample(name, reports_root / sha, labels, progress))
    return rows


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def _ratio(num: float, den: float) -> float | None:
    return num / den if den else None


def wilson_interval(successes: int, total: int, z: float = 1.96) -> list[float] | None:
    if total == 0:
        return None
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def roc_auc(pairs: list[tuple[bool, float]]) -> float | None:
    """Mann-Whitney AUC; ties count one half."""
    pos = [s for y, s in pairs if y]
    neg = [s for y, s in pairs if not y]
    if not pos or not neg:
        return None
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value from the discordant counts."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def confusion_metrics(rows: list[SampleRow], policy: str, abstain_as_error: bool) -> dict[str, Any]:
    positive = POLICIES[policy]
    tp = fp = tn = fn = abstained = 0
    for row in rows:
        is_malware = row.label == LABEL_MALWARE
        if row.verdict in ABSTAIN:
            abstained += 1
            if not abstain_as_error:
                continue
            predicted = not is_malware  # the wrong answer, whichever class it is
        else:
            predicted = row.verdict in positive
        if is_malware:
            tp, fn = (tp + 1, fn) if predicted else (tp, fn + 1)
        else:
            fp, tn = (fp + 1, tn) if predicted else (fp, tn + 1)

    scored = tp + fp + tn + fn
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    specificity = _ratio(tn, tn + fp)
    f1 = (_ratio(2 * precision * recall, precision + recall)
          if precision is not None and recall is not None else None)
    mcc_den = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    return {
        "policy": policy,
        "abstain_as_error": abstain_as_error,
        "n": len(rows),
        "scored": scored,
        "abstained": abstained,
        "coverage": _round(_ratio(len(rows) - abstained, len(rows))),
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "accuracy": _round(_ratio(tp + tn, scored)),
        "accuracy_ci95": wilson_interval(tp + tn, scored),
        "precision": _round(precision),
        "recall": _round(recall),
        "recall_ci95": wilson_interval(tp, tp + fn),
        "specificity": _round(specificity),
        "specificity_ci95": wilson_interval(tn, tn + fp),
        "fpr": _round(_ratio(fp, fp + tn)),
        "f1": _round(f1),
        "balanced_accuracy": _round((recall + specificity) / 2
                                    if recall is not None and specificity is not None else None),
        "mcc": _round((tp * tn - fp * fn) / mcc_den if mcc_den else None),
    }


def summarize(rows: list[SampleRow]) -> dict[str, Any]:
    labeled = [r for r in rows if r.label != "unlabeled" and not r.error]
    scores = [(r.label == LABEL_MALWARE, r.score) for r in labeled if r.score is not None]
    brier = (sum((s - (1.0 if y else 0.0)) ** 2 for y, s in scores) / len(scores)) if scores else None
    return {
        "samples": len(rows),
        "labeled": len(labeled),
        "malware": sum(r.label == LABEL_MALWARE for r in labeled),
        "benign": sum(r.label == LABEL_BENIGN for r in labeled),
        "unlabeled": sum(r.label == "unlabeled" for r in rows),
        "errors": sum(bool(r.error) for r in rows),
        "missing_or_invalid_labeled": sum(bool(r.error) and r.label != "unlabeled" for r in rows),
        "flags": {
            "intel_present": sum(r.intel_present for r in rows),
            "reused": sum(r.reused for r in rows),
            "path_reveals_label": sum(r.path_reveals_label for r in rows),
            "controlled": sum(r.controlled for r in rows),
            "blind": sum(r.blind for r in rows),
        },
        "summary_status": _count(r.summary_status for r in rows),
        "verdicts": {label: _count(r.verdict for r in labeled if r.label == label)
                     for label in (LABEL_MALWARE, LABEL_BENIGN)},
        "auc": _round(roc_auc(scores)),
        "brier": _round(brier),
        "metrics": [confusion_metrics(labeled, policy, abstain_as_error)
                    for policy in POLICIES for abstain_as_error in (False, True)],
    }


def _count(values: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        out[value or "(none)"] = out.get(value or "(none)", 0) + 1
    return dict(sorted(out.items()))


def _correct(row: SampleRow, policy: str = "lenient") -> bool:
    """Correctness with abstention counted as an error."""
    if row.verdict in ABSTAIN or row.error:
        return False
    return (row.verdict in POLICIES[policy]) == (row.label == LABEL_MALWARE)


def paired_comparisons(rows: list[SampleRow], min_shared: int = 5) -> list[dict[str, Any]]:
    by_condition: dict[str, dict[str, SampleRow]] = {}
    for row in rows:
        if row.label != "unlabeled":
            by_condition.setdefault(row.condition, {})[row.sha256] = row
    out = []
    for a, b in combinations(sorted(by_condition), 2):
        shared = sorted(set(by_condition[a]) & set(by_condition[b]))
        if len(shared) < min_shared:
            continue
        only_a = sum(_correct(by_condition[a][s]) and not _correct(by_condition[b][s]) for s in shared)
        only_b = sum(_correct(by_condition[b][s]) and not _correct(by_condition[a][s]) for s in shared)
        out.append({
            "a": a, "b": b, "shared": len(shared),
            "a_correct": sum(_correct(by_condition[a][s]) for s in shared),
            "b_correct": sum(_correct(by_condition[b][s]) for s in shared),
            "only_a_correct": only_a, "only_b_correct": only_b,
            "mcnemar_p": round(mcnemar_exact(only_a, only_b), 4),
        })
    return out


def evaluate(rows: list[SampleRow]) -> dict[str, Any]:
    conditions = sorted({r.condition for r in rows})
    per_condition = {}
    for name in conditions:
        subset = [r for r in rows if r.condition == name]
        per_condition[name] = {
            "all": summarize(subset),
            "controlled": summarize([r for r in subset if r.controlled]),
            "blind": summarize([r for r in subset if r.blind]),
            "completed_only": summarize([r for r in subset if r.summary_status == "completed"]),
            "borderline_malware": summarize([
                r for r in subset
                if r.label == LABEL_BENIGN or (r.malice is not None and r.malice < BORDERLINE_MALICE)
            ]),
        }
    return {"conditions": per_condition, "paired": paired_comparisons(rows)}


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _fmt(value: Any) -> str:
    if value is None:
        return "–"
    if isinstance(value, float):
        return f"{value:.3f}"
    if isinstance(value, list):
        return f"[{value[0]:.2f}; {value[1]:.2f}]"
    return str(value)


def _metric(summary: dict[str, Any], policy: str, abstain_as_error: bool) -> dict[str, Any]:
    return next(m for m in summary["metrics"]
                if m["policy"] == policy and m["abstain_as_error"] == abstain_as_error)


def render_markdown(result: dict[str, Any], rows: list[SampleRow]) -> str:
    lines = [
        "# Đối chiếu verdict của HyperAgent với nhãn DikeDataset",
        "",
        "Sinh bởi `experiments/label_eval.py` (chỉ đọc 09-summary.json đã có, không chạy lại pipeline).",
        "Quy ước: `lenient` tính malicious và suspicious là dương tính; `strict` chỉ tính malicious.",
        "inconclusive/unknown là từ chối kết luận, không bao giờ được tính là benign.",
        "Khoảng tin cậy 95% theo Wilson.",
        "",
        "Cờ hiệu lực: `intel` = đã chạy 06-intel (VirusTotal, cùng nguồn với nhãn);",
        "`reused` = đọc lại 09-summary cũ, không có lời gọi mô hình mới;",
        "`path` = tên thư mục cha của mẫu tiết lộ nhãn.",
        "`controlled` = không intel, không reused; `blind` = controlled và không lộ nhãn qua đường dẫn.",
        "",
        "## 1. Tổng quan theo điều kiện",
        "",
        "| Điều kiện | Mẫu (M/B) | intel | reused | path | controlled | blind | Thiếu | Coverage | Acc (bỏ abstain) | Acc (abstain = sai) | Recall | Specificity | MCC | AUC |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, block in result["conditions"].items():
        s = block["all"]
        decided = _metric(s, "lenient", False)
        worst = _metric(s, "lenient", True)
        lines.append(
            f"| {name} | {s['labeled']} ({s['malware']}/{s['benign']}) | {s['flags']['intel_present']} | "
            f"{s['flags']['reused']} | {s['flags']['path_reveals_label']} | {s['flags']['controlled']} | {s['flags']['blind']} | {s['missing_or_invalid_labeled']} | "
            f"{_fmt(decided['coverage'])} | {_fmt(decided['accuracy'])} {_fmt(decided['accuracy_ci95'])} | "
            f"{_fmt(worst['accuracy'])} {_fmt(worst['accuracy_ci95'])} | {_fmt(worst['recall'])} | "
            f"{_fmt(worst['specificity'])} | {_fmt(worst['mcc'])} | {_fmt(s['auc'])} |"
        )

    lines += ["", "## 2. Chỉ số trên tập controlled (lenient, abstain = sai)", "",
              "| Điều kiện | n | TP | FP | TN | FN | Abstain | Accuracy (CI95) | Recall (CI95) | Specificity (CI95) | F1 |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, block in result["conditions"].items():
        m = _metric(block["controlled"], "lenient", True)
        if not m["n"]:
            lines.append(f"| {name} | 0 | | | | | | không có mẫu controlled | | | |")
            continue
        lines.append(
            f"| {name} | {m['n']} | {m['tp']} | {m['fp']} | {m['tn']} | {m['fn']} | {m['abstained']} | "
            f"{_fmt(m['accuracy'])} {_fmt(m['accuracy_ci95'])} | {_fmt(m['recall'])} {_fmt(m['recall_ci95'])} | "
            f"{_fmt(m['specificity'])} {_fmt(m['specificity_ci95'])} | {_fmt(m['f1'])} |"
        )

    lines += ["", "## 3. Độ nhạy theo quy ước chấm (toàn bộ mẫu có nhãn)", "",
              "| Điều kiện | lenient/bỏ abstain | lenient/abstain = sai | strict/bỏ abstain | strict/abstain = sai |",
              "|---|---|---|---|---|"]
    for name, block in result["conditions"].items():
        cells = [_fmt(_metric(block["all"], p, a)["accuracy"]) for p in POLICIES for a in (False, True)]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")

    if result["paired"]:
        lines += ["", "## 4. So sánh cặp trên mẫu chung (McNemar exact, lenient, abstain = sai)", "",
                  "| A | B | Mẫu chung | A đúng | B đúng | Chỉ A đúng | Chỉ B đúng | p |",
                  "|---|---|---|---|---|---|---|---|"]
        for p in result["paired"]:
            lines.append(f"| {p['a']} | {p['b']} | {p['shared']} | {p['a_correct']} | {p['b_correct']} | "
                         f"{p['only_a_correct']} | {p['only_b_correct']} | {p['mcnemar_p']} |")

    wrong = [r for r in rows if r.label != "unlabeled" and not _correct(r)]
    lines += ["", "## 5. Mẫu sai hoặc từ chối kết luận", "",
              "| Điều kiện | SHA256 | Nhãn | malice | Verdict | conf | Trạng thái | Cờ | Tóm tắt |",
              "|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(wrong, key=lambda r: (r.condition, r.label, r.sha256)):
        flags = ",".join(f for f, on in (("intel", r.intel_present), ("reused", r.reused),
                                         ("path", r.path_reveals_label)) if on) or "–"
        text = (r.error or r.one_sentence_summary).replace("|", "/").replace("\n", " ")[:140]
        lines.append(f"| {r.condition} | `{r.sha256[:12]}` | {r.label} | {_fmt(r.malice)} | {r.verdict or '–'} | "
                     f"{_fmt(r.confidence)} | {r.summary_status} | {flags} | {text} |")
    return "\n".join(lines) + "\n"


def write_outputs(rows: list[SampleRow], result: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "per_sample.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(SampleRow.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(asdict(r) for r in rows)
    (output_dir / "metrics.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "report.md").write_text(render_markdown(result, rows), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def discover_conditions(results_dir: Path) -> dict[str, Path]:
    """Every ``<results>/**/reports`` directory, named by its path below results."""
    found = {}
    for reports in sorted(results_dir.glob("**/reports")):
        if reports.is_dir() and any(reports.glob(f"*/{SUMMARY_FILE}")):
            found[reports.parent.relative_to(results_dir).as_posix()] = reports
    return found


def _parse_condition(text: str) -> tuple[str, Path]:
    name, sep, path = text.partition("=")
    if not sep:
        raise argparse.ArgumentTypeError("expected NAME=REPORTS_ROOT")
    return name, Path(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--labels-dir", type=Path, default=DEFAULT_LABELS_DIR,
                        help="Directory with DikeDataset benign.csv and malware.csv")
    parser.add_argument("--condition", type=_parse_condition, action="append", default=[],
                        metavar="NAME=REPORTS_ROOT",
                        help="Report root to score; repeatable. Default: every reports/ under experiments/results")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    conditions = dict(args.condition) or discover_conditions(ROOT / "results")
    if not conditions:
        parser.error("no report roots found")
    labels = load_labels(args.labels_dir)
    rows = collect(conditions, labels)
    result = evaluate(rows)
    write_outputs(rows, result, args.output_dir)
    logger.info("Scored %d verdicts across %d condition(s) -> %s",
                len(rows), len(conditions), args.output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
