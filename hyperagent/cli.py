"""Command-line entry points for HyperAgent."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from . import run_registry
from .config import THINKING_LEVELS, load_config
from .console import ConsoleLogHandler, RunConsole, create_run_console
from .dashboard import DEFAULT_PORT, DashboardUnavailable, LiveDashboard, start_dashboard
from .engine.launcher import STAGES, run_pipeline_with_config


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hyperagent", description="HyperAgent malware-analysis pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser("analyze", help="Run the pipeline for one sample")
    analyze.add_argument("sample_path", type=Path, help="Path to the sample to analyze")
    analyze.add_argument("--stage", choices=[stage.stage_id for stage in STAGES], help="Run only a single stage")
    analyze.add_argument(
        "--profile",
        choices=["full", "intel", "fast", "static-only", "dynamic-only"],
        help=(
            "Select a runtime profile; full runs every local stage, intel adds external "
            "enrichment (06-intel) on top, fast skips dynamic and intel, static-only "
            "additionally skips unpack and static pass 2, dynamic-only skips the static/unpack/"
            "intel stages -- all keep deepdive/report/summary"
        ),
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
    analyze.add_argument(
        "--thinking",
        choices=list(THINKING_LEVELS),
        help="Extended-thinking depth for every stage; 'off' disables it entirely",
    )
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
        help=(
            "Live run console: on a capable terminal a full-screen view with a sidebar "
            "(stages, IoCs, evidence) and a browser dashboard; plain condensed lines otherwise"
        ),
    )
    analyze.add_argument(
        "--no-tui",
        action="store_true",
        help="With --mdebug, print plain lines with a status footer, not the full-screen view",
    )
    analyze.add_argument(
        "--no-dashboard",
        action="store_true",
        help="With --mdebug, do not serve the live browser dashboard",
    )
    analyze.add_argument(
        "--dashboard-port",
        type=int,
        default=DEFAULT_PORT,
        help=f"First port to try for the live dashboard on 127.0.0.1 (default: {DEFAULT_PORT})",
    )

    link = subparsers.add_parser(
        "link-reports",
        help="Record existing report folders in the run index so the dashboard lists them",
    )
    link.add_argument(
        "roots", type=Path, nargs="+", help="Folders to search for <sha256> report directories"
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
    if args.thinking:
        config.provider.thinking_level = args.thinking
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
    dashboard = None
    if args.debug:
        # Turns thinking on only when no level is configured; an explicit
        # --thinking / HYPERAGENT_THINKING_LEVEL still wins, including "off".
        config.provider.extended_thinking = True
        config.provider.console_mode = "full"
        logging.basicConfig(level=logging.DEBUG)
        logging.getLogger("httpx").setLevel(logging.WARNING)
    elif args.mdebug:
        config.provider.console_mode = "minimal"
        run_console = create_run_console(prefer_tui=not args.no_tui)
        handler = ConsoleLogHandler(run_console)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        # One access-log line per dashboard poll would drown the trace.
        logging.getLogger("werkzeug").setLevel(logging.WARNING)
        if not args.no_dashboard:
            dashboard = _start_live_dashboard(run_console, config, args)

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
        if dashboard is not None:
            dashboard.close()

    return 0 if metrics.stages and all(stage.stage_status == "completed" for stage in metrics.stages) else 1


def _start_live_dashboard(
    run_console: RunConsole, config, args: argparse.Namespace
) -> LiveDashboard | None:
    """Serve the web UI for this run; a failure is reported, never fatal."""
    # Same fallback as the launcher's report dir, so /runs/<sha> links resolve.
    reports_root = getattr(config, "reports_root", None) or (
        Path(args.sample_path).expanduser().resolve().parent / "reports"
    )
    try:
        dashboard = start_dashboard(
            reports_root=Path(reports_root), live_feed=run_console, port=args.dashboard_port
        )
    except DashboardUnavailable as exc:
        run_console.set_viewer("failed", detail=str(exc))
        return None
    run_console.set_viewer("running", url=dashboard.url)
    return dashboard


def _cmd_link_reports(args: argparse.Namespace) -> int:
    found = []
    for root in args.roots:
        if not root.is_dir():
            print(f"Not a directory: {root}", file=sys.stderr)
            return 2
        runs = run_registry.find_run_dirs(root)
        print(f"{root}: {len(runs)} run folder(s)")
        found.extend(runs)
    linked = run_registry.link_runs(found)
    print(f"Linked {linked} run(s) in {run_registry.default_index_path()}")
    return 0


def _cmd_batch(_args: argparse.Namespace) -> int:
    raise NotImplementedError("Phase 5")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "analyze":
        return _cmd_analyze(args)
    if args.command == "link-reports":
        return _cmd_link_reports(args)
    if args.command == "batch":
        return _cmd_batch(args)

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
