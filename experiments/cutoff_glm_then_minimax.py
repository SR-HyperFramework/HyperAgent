"""One-shot watcher: give glm_5_2 a 30-minute window, then force minimax_m2_7.

glm_5_2 has been slow to progress. This polls
``experiments/results/llm_compare/glm_5_2/progress.jsonl`` every 60s for up
to 30 minutes. If it reaches 10/10 within the window, the already-running
``llm-compare`` process moves on to ``minimax_m2_7`` by itself (both were in
LLM_CONDITIONS when it started) and this watcher exits without touching
anything.

If the 30-minute deadline passes first, it kills the running
``run_study llm-compare`` process and any orphaned ``idalib-mcp`` process,
then relaunches ``python -m experiments.run_study llm-compare``.
``glm_5_2`` has already been removed from ``LLM_CONDITIONS`` in
run_study.py (edited before this watcher started, so the still-running old
process was unaffected) -- the relaunch picks up that edit and goes
straight to ``minimax_m2_7``, skipping whatever glm_5_2 sample was
mid-flight. Runs once and exits -- not a recurring poll.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

GLM_PROGRESS = Path("experiments/results/llm_compare/glm_5_2/progress.jsonl")
LLM_COMPARE_LOG = Path("experiments/results/llm_compare/cutoff_relaunch.log")
POLL_SECONDS = 60
DEADLINE_SECONDS = 30 * 60
EXPECTED_GLM_TOTAL = 10


def _row_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _kill_matching(pattern: str) -> None:
    subprocess.run(
        [
            "powershell", "-NoProfile", "-Command",
            "Get-CimInstance Win32_Process | "
            f"Where-Object {{ $_.CommandLine -like '{pattern}' -or $_.Name -like '{pattern}' }} | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }",
        ],
        capture_output=True,
        text=True,
    )


def wait_for_glm_or_deadline() -> bool:
    """Return True if glm_5_2 finished naturally within the window."""
    deadline = time.monotonic() + DEADLINE_SECONDS
    print(
        f"[cutoff] polling {GLM_PROGRESS} every {POLL_SECONDS}s, "
        f"{DEADLINE_SECONDS // 60}min deadline",
        flush=True,
    )
    while time.monotonic() < deadline:
        count = _row_count(GLM_PROGRESS)
        if count >= EXPECTED_GLM_TOTAL:
            print(f"[cutoff] glm_5_2 reached {count}/{EXPECTED_GLM_TOTAL} within the window -- done, no action needed", flush=True)
            return True
        time.sleep(POLL_SECONDS)
    print(f"[cutoff] 30min deadline hit with {_row_count(GLM_PROGRESS)}/{EXPECTED_GLM_TOTAL} -- cutting glm_5_2 over", flush=True)
    return False


def force_minimax() -> None:
    print("[cutoff] killing run_study llm-compare + idalib-mcp", flush=True)
    _kill_matching("*run_study*llm-compare*")
    _kill_matching("*idalib-mcp*")
    time.sleep(3)
    print("[cutoff] relaunching: python -m experiments.run_study llm-compare --verbose", flush=True)
    LLM_COMPARE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with LLM_COMPARE_LOG.open("a", encoding="utf-8") as fh:
        subprocess.Popen(
            [sys.executable, "-m", "experiments.run_study", "llm-compare", "--verbose"],
            stdout=fh,
            stderr=subprocess.STDOUT,
        )


def main() -> int:
    finished_naturally = wait_for_glm_or_deadline()
    if not finished_naturally:
        force_minimax()
    return 0


if __name__ == "__main__":
    sys.exit(main())
