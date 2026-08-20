"""Command-line entry points for HyperAgent."""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from .config import load_config
from .console import ConsoleLogHandler, RunConsole
from .engine.launcher import STAGES, run_pipeline_with_config


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hyperagent", description="HyperAgent malware-analysis pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser("analyze", help="Run the pipeline for one sample")
    analyze.add_argument("sample_path", type=Path, help="Path to the sample to analyze")
    analyze.add_argument("--stage", choices=[stage.stage_id for stage in STAGES], help="Run only a single stage")
    analyze.add_argument(
        "--profile",
        choices=["full", "fast", "static-only"],
        help="Select a runtime profile; fast/static-only skip expensive dynamic/intel work",
    )
    analyze.add_argument("--static-only", action="store_true", help="Shortcut for --profile static-only")
    analyze.add_argument("--skip-dynamic", action="store_true", help="Skip the VM-backed dynamic stage")
    analyze.add_argument("--skip-intel", action="store_true", help="Skip external intelligence enrichment")
    analyze.add_argument("--no-cache", action="store_true", help="Do not reuse completed stage artifacts")
    analyze.add_argument(
        "--ida-mcp",
        choices=["auto", "always", "never"],
        help="Control local idalib-mcp startup for this run",
    )
    analyze.add_argument("--provider", help="Override provider name (e.g. anthropic)")
    analyze.add_argument("--model", help="Override model id")
    analyze.add_argument("--config", type=Path, help="Path to config YAML")
    debug_group = analyze.add_mutually_exclusive_group()
    debug_group.add_argument(
        "--debug",
        action="store_true",
        help="Stream full live LLM thinking/text/tool-call output to console",
    )
    debug_group.add_argument(
        "--mdebug",
        action="store_true",
        help="Stream a condensed console view (assistant text + concise tool calls only)",
    )

    batch = subparsers.add_parser("batch", help="Batch evaluation pipeline (Phase 5)")
    batch.add_argument("samples_dir", type=Path, help="Directory of samples")
    batch.add_argument("--output-dir", type=Path, default=Path("experiments/results"))
    batch.add_argument("--config", type=Path, help="Path to config YAML")

    return parser


def _cmd_analyze(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if args.provider:
        config.provider.name = args.provider
    if args.model:
        config.provider.model = args.model
    if args.static_only:
        config.runtime.pipeline_profile = "static-only"
    elif args.profile:
        config.runtime.pipeline_profile = args.profile
    if args.skip_dynamic:
        config.runtime.skip_dynamic = True
    if args.skip_intel:
        config.runtime.skip_intel = True
    if args.no_cache:
        config.runtime.reuse_completed_stages = False
    if args.ida_mcp:
        config.runtime.start_ida_mcp = args.ida_mcp

    run_console = None
    if args.debug:
        config.provider.extended_thinking = True
        config.provider.console_mode = "full"
        logging.basicConfig(level=logging.DEBUG)
        logging.getLogger("httpx").setLevel(logging.WARNING)
    elif args.mdebug:
        config.provider.console_mode = "minimal"
        run_console = RunConsole(enabled=True)
        handler = ConsoleLogHandler(run_console)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
        logging.getLogger("httpx").setLevel(logging.WARNING)

    try:
        metrics = asyncio.run(
            run_pipeline_with_config(
                sample_path=args.sample_path,
                config=config,
                stage_id=args.stage,
                run_console=run_console,
            )
        )
    finally:
        if run_console is not None:
            run_console.finish()

    return 0 if metrics.stages and all(stage.stage_status == "completed" for stage in metrics.stages) else 1


def _cmd_batch(_args: argparse.Namespace) -> int:
    raise NotImplementedError("Phase 5")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "analyze":
        return _cmd_analyze(args)
    if args.command == "batch":
        return _cmd_batch(args)

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
