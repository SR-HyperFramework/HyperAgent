"""A report directory in mid-run, shared by the live-view tests."""

from __future__ import annotations

import json
from pathlib import Path

from hyperagent import pipeline_state

SHA = "c" * 64
ESCAPE = "\x1b[2J"


def _finding(fid: str, title: str, status: str, confidence: float, evidence: int) -> dict:
    return {
        "id": fid,
        "title": title,
        "category": "execution",
        "status": status,
        "confidence": confidence,
        "description": f"{title}.",
        "reasoning": "Fixture.",
        "sources": [],
        "evidence": [
            {
                "id": f"{fid}-ev{n}",
                "kind": "static",
                "source": {},
                "observation": "seen",
                "confidence": confidence,
            }
            for n in range(evidence)
        ],
        "limitations": [],
    }


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def build_run_dir(root: Path, sha256: str = SHA, *, with_summary: bool = False) -> Path:
    """01/02/05 completed, 03 checkpointed, the rest pending.

    The dynamic artifact carries one indicator with an embedded terminal
    escape so renderers can be checked for sanitizing sample-derived text.
    """
    report_dir = root / sha256
    pipeline_state.ensure_state(report_dir, sha256, "C:/samples/sample.exe")

    write_json(report_dir / "01-prepare-env.json", {"stage": "prepare-env"})
    pipeline_state.complete(report_dir, "01-prepare-env", str(report_dir / "01-prepare-env.json"))

    write_json(
        report_dir / "02-static-pass1.json",
        {
            "status": "completed",
            "findings": [
                _finding("fin-001", "Packed PE32 loader", "confirmed", 1.0, 2),
                _finding("fin-002", "Possible anti-debug check", "hypothesized", 0.4, 1),
            ],
        },
    )
    pipeline_state.complete(report_dir, "02-static-pass1", str(report_dir / "02-static-pass1.json"))

    progress = report_dir / "_state" / "03-unpack.progress.md"
    progress.parent.mkdir(parents=True, exist_ok=True)
    progress.write_text("# Checkpoint", encoding="utf-8")
    pipeline_state.checkpoint(report_dir, "03-unpack", str(progress))

    write_json(
        report_dir / "05-dynamic.json",
        {
            "status": "partial",
            "findings": [_finding("fin-dyn-001", "Decoded payload executed", "confirmed", 0.9, 3)],
            "iocs": {
                "network": ["evil.example.com"],
                "host": [f"C:/Users/Public/drop{ESCAPE}.exe"],
                "persistence": ["HKCU/Software/Microsoft/Windows/CurrentVersion/Run/updater"],
            },
        },
    )
    pipeline_state.complete(report_dir, "05-dynamic", str(report_dir / "05-dynamic.json"))

    write_json(
        report_dir / "07-deepdive.json",
        {"executive_assessment": {"verdict": "suspicious", "confidence": 0.6}},
    )

    if with_summary:
        write_json(
            report_dir / "09-summary.json",
            {
                "executive_summary": {"verdict": "malicious", "confidence": 0.85},
                "confirmed_iocs": {
                    "network": [
                        {
                            "value": "evil.example.com",
                            "label": None,
                            "note": None,
                            "source_refs": [],
                        }
                    ],
                    "host": [],
                    "persistence": [],
                },
            },
        )
    return report_dir
