"""One-off: remove leaked-intel artifacts and reset 06-intel/07-09 outputs
across every isolated llm_compare condition, so the next run applies the
no_intel skip (now wired into run_llm_compare unconditionally) cleanly
instead of mixing pre-fix and post-fix samples.

Motivation: 06-intel.json's claim_checks state the ground-truth verdict in
plain language (e.g. "widely flagged by multiple AV engines as malicious" /
claim id "cc-goodware-verdict" -> "CLEAN/harmless"), confirmed 2026-08-27 in
gpt_5_6_terra/gpt_5_6_sol's seeded data. Any sample whose 07-09 already ran
saw that text before reasoning, so those verdicts are invalid evidence for
a synthesis-quality comparison and must be redone, not just stripped of the
now-leaked file going forward.

Scope decision (confirmed with user 2026-08-27): all 6 isolated
llm_compare/<slug>/reports/ conditions, INCLUDING the 4 with already-
completed 07-09 work under the leaked intel (gpt_5_6_luna 10/10,
minimax_m2_7 10/10, glm_5_3_flash 7/10, gpt_5_6_terra 4/10) -- their
existing verdicts are purged and re-earned, not kept as "historical".
Excludes deepseek_v4_flash, which has no isolated reports/ of its own and
instead reads baseline_30's shared default-location data; touching that
would edit baseline_30 itself, out of scope for this cleanup.

Resets progress.jsonl/results.json per condition to absent so the next
`run_study llm-compare` invocation re-runs every sample from 07-deepdive
fresh (06-intel itself is permanently skipped by the no_intel ablation
config now passed in run_llm_compare, so it never needs to "complete").
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from experiments import run_study as rs

TARGET_CONDITIONS = [
    "gpt_5_6_luna",
    "minimax_m2_7",
    "glm_5_3_flash",
    "minimax_m3",
    "gpt_5_6_terra",
    "gpt_5_6_sol",
]

_RESET_STAGES = ["06-intel", "07-deepdive", "08-report", "09-summary"]
_RESET_OUTPUT_FILES = [
    "06-intel.json",
    "07-deepdive.json",
    "08-report.context.md",
    "08-report.md",
    "09-summary.json",
]


def _purge_sample(dest: Path) -> None:
    for rel in _RESET_OUTPUT_FILES:
        p = dest / rel
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()

    intel_dir = dest / "_intel"
    if intel_dir.exists():
        shutil.rmtree(intel_dir)

    state_dir = dest / "_state"
    if state_dir.exists():
        for stage_id in _RESET_STAGES:
            for stray in state_dir.glob(f"{stage_id}*"):
                stray.unlink()

    state_path = dest / "STATE.json"
    if not state_path.exists():
        return
    state = json.loads(state_path.read_text(encoding="utf-8"))
    for stage_id, entry in state.get("stages", {}).items():
        if stage_id in _RESET_STAGES:
            entry["status"] = "pending"
            entry["output_path"] = None
            entry["progress_path"] = None
            entry["updated_at"] = None
    state["current_stage_id"] = "07-deepdive"
    state["last_error"] = None
    state.pop("recommend_next_stage", None)
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    for slug in TARGET_CONDITIONS:
        cond_root = rs.RESULTS_ROOT / "llm_compare" / slug
        reports_root = cond_root / "reports"
        if not reports_root.exists():
            print(f"[skip] {slug}: no reports/ directory")
            continue
        print(f"=== {slug} ===")
        for sample_dir in sorted(reports_root.iterdir()):
            if not sample_dir.is_dir():
                continue
            _purge_sample(sample_dir)
            print(f"  [ok] {sample_dir.name[:12]}: purged intel + 07-09, reset to pending")

        for fname in ("progress.jsonl", "results.json"):
            p = cond_root / fname
            if p.exists():
                p.unlink()
                print(f"  [ok] removed {fname}")

    print(
        "\ndone. Re-run with: python -m experiments.run_study llm-compare "
        + " ".join(f"--condition {slug}" for slug in TARGET_CONDITIONS)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
