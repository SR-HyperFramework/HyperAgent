#!/usr/bin/env python3
"""Resolve HyperAgent skill roots without depending on the current working directory."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path


def default_root() -> Path:
    configured = os.environ.get("HYPERAGENT_SKILLS_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = default_root()
    payload = {
        "skills_root": str(root),
        "common_root": str(root / "_hyperagent-common"),
        "skill_root": str(root / args.skill),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        for key, value in payload.items():
            print(f"{key.upper()}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
