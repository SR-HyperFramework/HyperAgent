#!/usr/bin/env python3
"""Command-line front end for HyperAgent's STATE.json helper.

All state logic (stage table, statuses, recommendations, path resolution)
lives in ``hyperagent.pipeline_state``; this script only parses arguments and
prints the resulting state, so skills, validators and the launcher share one
implementation. It also re-exports that module's names, which lets sibling
helper scripts (``validate_pipeline.py``, ``build_report_context.py``) do
``from pipeline_state import STAGE_TABLE``.

The ``hyperagent`` package is imported from the active environment
(``pip install -e .``); failing that, from the repository this script sits in.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _import_core():
    try:
        from hyperagent import pipeline_state as core
    except ImportError:
        repo_root = Path(__file__).resolve().parents[3]
        if not (repo_root / "hyperagent" / "pipeline_state.py").is_file():
            raise SystemExit(
                "Cannot import hyperagent.pipeline_state: install the package "
                "(pip install -e .) or run this script from the HyperAgent repository."
            ) from None
        sys.path.insert(0, str(repo_root))
        from hyperagent import pipeline_state as core
    return core


_core = _import_core()

SCHEMA_VERSION = _core.SCHEMA_VERSION
STAGE_TABLE = _core.STAGE_TABLE
STAGE_IDS = _core.STAGE_IDS
STAGE_SKILLS = _core.STAGE_SKILLS
STATUS_PENDING = _core.STATUS_PENDING
STATUS_RUNNING = _core.STATUS_RUNNING
STATUS_COMPLETED = _core.STATUS_COMPLETED
VALID_STATUSES = _core.VALID_STATUSES
VALID_RECOMMEND_ACTIONS = _core.VALID_RECOMMEND_ACTIONS
stage_schema_rel = _core.stage_schema_rel
state_path_for = _core.state_path_for
default_output_path = _core.default_output_path
default_progress_path = _core.default_progress_path
resolve_recorded_path = _core.resolve_recorded_path
normalize_state = _core.normalize_state


def main() -> int:
    parser = argparse.ArgumentParser(description="HyperAgent pipeline STATE.json helper")
    parser.add_argument("--report-dir", required=True, help="reports/<sha256> directory")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Create STATE.json if it does not already exist")
    p_init.add_argument("--sample-sha256", required=True)
    p_init.add_argument("--input-path", required=True)

    p_read = sub.add_parser("read", help="Print STATE.json, or a single stage entry with --stage-id")
    p_read.add_argument("--stage-id", default=None)

    p_ckpt = sub.add_parser("checkpoint", help="Mark a stage 'running' with a progress file")
    p_ckpt.add_argument("--stage-id", required=True)
    p_ckpt.add_argument("--progress-path", required=True)
    p_ckpt.add_argument(
        "--recommend-reason",
        default=None,
        help="Optional short explanation stored in top-level recommend_next_stage.reason",
    )

    p_complete = sub.add_parser("complete", help="Mark a stage 'completed' with its final artifact")
    p_complete.add_argument("--stage-id", required=True)
    p_complete.add_argument("--output-path", required=True)
    p_complete.add_argument(
        "--recommend-reason",
        default=None,
        help="Optional short explanation stored in top-level recommend_next_stage.reason",
    )

    p_fail = sub.add_parser("fail", help="Record a pipeline-level error against a stage")
    p_fail.add_argument("--stage-id", required=True)
    p_fail.add_argument("--message", required=True)

    args = parser.parse_args()
    report_dir = Path(args.report_dir).expanduser().resolve()

    try:
        if args.command == "init":
            state = _core.ensure_state(report_dir, args.sample_sha256, args.input_path)
        elif args.command == "read":
            state = _core.load_state(report_dir)
            if args.stage_id:
                _core._validate_stage_id(args.stage_id)
                print(json.dumps(state["stages"][args.stage_id], indent=2, ensure_ascii=False))
                return 0
        elif args.command == "checkpoint":
            state = _core.checkpoint(
                report_dir, args.stage_id, args.progress_path, args.recommend_reason
            )
        elif args.command == "complete":
            state = _core.complete(
                report_dir, args.stage_id, args.output_path, args.recommend_reason
            )
        elif args.command == "fail":
            state = _core.fail(report_dir, args.stage_id, args.message)
        else:  # pragma: no cover - argparse enforces choices
            parser.error("unknown command")
            return 2
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(state, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
