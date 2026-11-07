"""Wait for the running no_intel expansion (expand_no_intel_ablation.py, 20
samples) to finish on its own, then launch llm-compare so it picks up the
newly-added qwen3_8_27b_fp8 condition.

No deadline/force-kill here (unlike cutoff_glm_then_minimax.py) -- both jobs
share the single VM + idalib-mcp (port 13337), so qwen3_8_27b_fp8 genuinely
cannot start until no_intel's pipeline process releases them. Detection is
by process liveness (CIM query matching the expand_no_intel_ablation command
line), not just progress.jsonl row count, so a crash also unblocks qwen
instead of waiting forever on a dead process.

llm-compare's own resumability (progress.jsonl-keyed skip) means running the
plain command only does fresh work for qwen3_8_27b_fp8 -- deepseek_v4_flash
(reused_from_default_location), gpt_5_6_luna and minimax_m2_7 (already 10/10
recorded, errors included) all resume-skip near-instantly.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

PYTHON = "C:/Users/ADMIN/AppData/Local/Programs/Python/Python311/python.exe"
NO_INTEL_PROGRESS = Path("experiments/results/ablation/no_intel/progress.jsonl")
LLM_COMPARE_LOG = Path("experiments/results/llm_compare/qwen3_8_27b_fp8_launch.log")
POLL_SECONDS = 60


def _row_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _no_intel_still_running() -> bool:
    result = subprocess.run(
        [
            "powershell", "-NoProfile", "-Command",
            "(Get-CimInstance Win32_Process | "
            "Where-Object { $_.CommandLine -like '*expand_no_intel_ablation*' -and $_.Name -eq 'python.exe' } "
            "| Measure-Object).Count",
        ],
        capture_output=True,
        text=True,
    )
    try:
        return int(result.stdout.strip()) > 0
    except ValueError:
        return False


def _kill_idalib_mcp() -> None:
    subprocess.run(
        [
            "powershell", "-NoProfile", "-Command",
            "Get-CimInstance Win32_Process | Where-Object { $_.Name -like '*idalib-mcp*' } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }",
        ],
        capture_output=True,
        text=True,
    )


def main() -> int:
    print(f"[watch] polling for expand_no_intel_ablation.py to exit, every {POLL_SECONDS}s", flush=True)
    while _no_intel_still_running():
        print(f"[watch] still running -- no_intel progress: {_row_count(NO_INTEL_PROGRESS)}/30", flush=True)
        time.sleep(POLL_SECONDS)

    print(f"[watch] no_intel expansion finished -- final progress: {_row_count(NO_INTEL_PROGRESS)}/30", flush=True)
    _kill_idalib_mcp()
    time.sleep(3)
    print("[watch] launching: python -m experiments.run_study llm-compare --verbose", flush=True)
    LLM_COMPARE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with LLM_COMPARE_LOG.open("a", encoding="utf-8") as fh:
        subprocess.Popen(
            [PYTHON, "-m", "experiments.run_study", "llm-compare", "--verbose"],
            stdout=fh,
            stderr=subprocess.STDOUT,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
