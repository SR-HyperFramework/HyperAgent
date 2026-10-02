"""Flask web UI for browsing HyperAgent analysis summaries.

Read-only: report pages serve whatever ``09-summary.json`` files already exist
under the reports tree, and the live page (``/live/<sha256>``) follows a run in
progress through its ``STATE.json`` and stage artifacts. When the CLI hosts
this app in-process it also passes a *live feed* -- the run console -- so the
live page can show the agent trace too. It never runs the pipeline, never
writes to a report directory, and never reads a sample binary.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Protocol

from flask import Flask, Response, abort, jsonify, redirect, render_template, request, url_for

REPO_ROOT = Path(__file__).resolve().parents[1]

try:
    from hyperagent.console_actions import group_events
    from hyperagent.console_log import has_console_log, read_console_log
    from hyperagent.run_registry import report_dirs as linked_report_dirs
    from hyperagent.run_snapshot import JsonFileCache, RunSnapshot, load_snapshot
except ImportError:  # `python webui/app.py` from a checkout that is not pip-installed
    sys.path.insert(0, str(REPO_ROOT))
    from hyperagent.console_actions import group_events
    from hyperagent.console_log import has_console_log, read_console_log
    from hyperagent.run_registry import report_dirs as linked_report_dirs
    from hyperagent.run_snapshot import JsonFileCache, RunSnapshot, load_snapshot

try:  # `flask --app webui.app` / `python -m webui.app`
    from .summaries import (
        RISK_LEVELS,
        VERDICTS,
        RunSummary,
        discover_runs,
        filter_runs,
        get_run,
        is_sha256,
        overview,
        sort_runs,
    )
except ImportError:  # `python webui/app.py`
    from summaries import (
        RISK_LEVELS,
        VERDICTS,
        RunSummary,
        discover_runs,
        filter_runs,
        get_run,
        is_sha256,
        overview,
        sort_runs,
    )

SORT_KEYS = ("recent", "verdict", "risk", "confidence", "name")


class LiveFeed(Protocol):
    """What the live page needs from a running console (see ``RunConsole``)."""

    def report_dir_for(self, sha256: str) -> Path | None: ...

    def live_status(self, sha256: str) -> dict[str, Any] | None: ...

    def active_runs(self) -> list[dict[str, Any]]: ...


def resolve_reports_root(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Reports tree to browse: explicit argument, then env, then ``<repo>/reports``."""
    if explicit:
        return Path(explicit).expanduser().resolve()
    configured = os.environ.get("HYPERAGENT_REPORTS_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (REPO_ROOT / "reports").resolve()


def asset_url(filename: str) -> str:
    """Static URL carrying the file's mtime, so an edited stylesheet or script
    is fetched fresh instead of being served from a stale browser cache."""
    path = Path(__file__).parent / "static" / filename
    try:
        version = int(path.stat().st_mtime)
    except OSError:
        return url_for("static", filename=filename)
    return url_for("static", filename=filename, v=version)


#: Page-level state of a live run, and how the page names it.
LIVE_STATE_LABELS = {
    "running": "Running",
    "completed": "Completed",
    "failed": "Failed",
    "stopped": "Stopped",
    "offline": "No live console",
}


#: Saved console records the live page renders; the rest is a download away.
SAVED_EVENT_LIMIT = 1000


def live_state(snapshot: RunSnapshot, live: dict[str, Any] | None) -> str:
    """Collapse console liveness and stage outcomes into one page state.

    Without a live feed there is no way to tell a run that is still going in
    another process from one that was abandoned, so that case is "offline"
    rather than a guess.
    """
    if live is not None and not live.get("finished"):
        return "running"
    if snapshot.outcome in ("completed", "failed"):
        return snapshot.outcome
    return "stopped" if live is not None else "offline"


def create_app(
    reports_root: str | os.PathLike[str] | None = None,
    *,
    live_feed: LiveFeed | None = None,
    run_index: str | os.PathLike[str] | None = None,
) -> Flask:
    app = Flask(__name__)
    app.config["REPORTS_ROOT"] = resolve_reports_root(reports_root)
    app.config["LIVE_FEED"] = live_feed
    #: The run index (``~/.hyperagent/runs.json`` by default) links report
    #: folders outside REPORTS_ROOT; see hyperagent.run_registry.
    app.config["RUN_INDEX"] = Path(run_index) if run_index else None
    snapshot_cache = JsonFileCache()

    def linked_dirs() -> list[Path]:
        return linked_report_dirs(app.config["RUN_INDEX"])

    def locate_run_dir(sha256: str, linked: list[Path] | None = None) -> Path:
        """The folder a run's STATE.json, artifacts and console log live in.

        The reports root first, then any linked folder; of several copies the
        most recently written wins. With none on disk, the reports-root path.
        """
        sha256 = sha256.lower()
        default = app.config["REPORTS_ROOT"] / sha256
        candidates = [default] + [
            path for path in (linked if linked is not None else linked_dirs())
            if path.name.lower() == sha256
        ]

        def freshness(path: Path) -> float:
            stamps = []
            for name in ("STATE.json", "09-summary.json", "console.jsonl"):
                try:
                    stamps.append((path / name).stat().st_mtime)
                except OSError:
                    pass
            return max(stamps, default=-1.0)

        best = max(candidates, key=freshness)
        return best if freshness(best) >= 0 else default

    @app.context_processor
    def inject_globals() -> dict[str, Any]:
        feed: LiveFeed | None = app.config["LIVE_FEED"]
        return {
            "reports_root": app.config["REPORTS_ROOT"],
            "linked_count": len(linked_dirs()),
            "verdicts": VERDICTS,
            "risk_levels": RISK_LEVELS,
            "asset": asset_url,
            "live_runs": feed.active_runs() if feed is not None else [],
        }

    def live_context(sha256: str) -> dict[str, Any] | None:
        """Everything the live page shows for one run, or None if it is unknown."""
        if not is_sha256(sha256):
            return None
        sha256 = sha256.lower()
        feed: LiveFeed | None = app.config["LIVE_FEED"]
        live = feed.live_status(sha256) if feed is not None else None
        linked = linked_dirs()
        report_dir = (feed.report_dir_for(sha256) if feed is not None else None) or (
            locate_run_dir(sha256, linked)
        )
        snapshot = load_snapshot(
            report_dir,
            stage_ids=live.get("stage_ids") if live else None,
            active_stage_id=live.get("active_stage_id") if live else None,
            cache=snapshot_cache,
        )
        # A console attached in this process streams its in-memory log; any
        # other run shows what its console saved to console.jsonl, which is
        # also how a dashboard started separately follows a run in progress.
        saved = None if live is not None else read_console_log(report_dir, limit=SAVED_EVENT_LIMIT)
        if not snapshot.exists and live is None and not (saved and saved.exists):
            return None
        state = live_state(snapshot, live)
        events = live["events"] if live is not None else saved.events if saved else []
        report = get_run(app.config["REPORTS_ROOT"], sha256, linked)
        has_report = report is not None and report.ok
        report_url = url_for("run_detail", sha256=sha256) if has_report else None
        return {
            "sha256": sha256,
            "snapshot": snapshot,
            "findings": snapshot.findings_newest_first,
            "live": live,
            "events": events,
            # Tool bursts folded into ActionGroups (see console_actions).
            "trace": group_events(events),
            "saved_console": saved if saved and saved.exists else None,
            "console_text_url": url_for("console_text", sha256=sha256)
            if live is not None or (saved and saved.exists)
            else None,
            "state": state,
            "state_label": LIVE_STATE_LABELS[state],
            "report_url": report_url,
        }

    @app.after_request
    def no_stale_markup(response):
        """Never let a browser reuse cached markup.

        Templates and the stylesheet change together; a cached page paired with a
        fresh stylesheet renders as unstyled wreckage because the class names no
        longer match. Static files are versioned by mtime instead (see
        ``asset_url``), so only the markup needs this.
        """
        if response.mimetype == "text/html":
            response.headers["Cache-Control"] = "no-store, must-revalidate"
        return response

    @app.route("/")
    def index() -> str:
        root: Path = app.config["REPORTS_ROOT"]
        runs = discover_runs(root, linked_dirs())

        query = request.args.get("q", "", type=str)
        verdict = request.args.get("verdict", "", type=str)
        risk = request.args.get("risk", "", type=str)
        sort_key = request.args.get("sort", "recent", type=str)
        if verdict not in VERDICTS:
            verdict = ""
        if risk not in RISK_LEVELS:
            risk = ""
        if sort_key not in SORT_KEYS:
            sort_key = "recent"

        visible = sort_runs(
            filter_runs(runs, query=query, verdict=verdict, risk=risk),
            sort_key,
        )

        return render_template(
            "index.html",
            runs=visible,
            stats=overview(runs),
            total_runs=len(runs),
            query=query,
            active_verdict=verdict,
            active_risk=risk,
            sort_key=sort_key,
            sort_keys=SORT_KEYS,
        )

    @app.route("/search")
    def search() -> Any:
        """Header search. A pasted SHA256 that exists jumps straight to its
        report; anything else becomes a filter on the index."""
        query = request.args.get("q", "", type=str).strip()
        if (
            is_sha256(query)
            and get_run(app.config["REPORTS_ROOT"], query, linked_dirs()) is not None
        ):
            return redirect(url_for("run_detail", sha256=query.lower()))
        return redirect(url_for("index", q=query or None))

    @app.route("/runs/<sha256>")
    def run_detail(sha256: str) -> str:
        linked = linked_dirs()
        run = get_run(app.config["REPORTS_ROOT"], sha256, linked)
        if run is None:
            abort(404)
        console_url = (
            url_for("live_run", sha256=run.sha256.lower())
            if has_console_log(locate_run_dir(run.sha256, linked))
            else None
        )
        return render_template("detail.html", run=run, console_url=console_url)

    @app.route("/api/runs")
    def api_runs() -> Any:
        runs = discover_runs(app.config["REPORTS_ROOT"], linked_dirs())
        return jsonify(
            {
                "reports_root": str(app.config["REPORTS_ROOT"]),
                "count": len(runs),
                "runs": [_api_row(run) for run in runs],
            }
        )

    @app.route("/api/runs/<sha256>")
    def api_run(sha256: str) -> Any:
        run = get_run(app.config["REPORTS_ROOT"], sha256, linked_dirs())
        if run is None:
            abort(404)
        if not run.ok:
            return jsonify({"sha256": run.sha256, "error": run.error}), 422
        # The stage artifact verbatim — the UI is a view over it, not a rewrite.
        return jsonify(run.data)

    @app.route("/live/<sha256>")
    def live_run(sha256: str) -> str:
        """A run in progress. ``?fragment=1`` returns just the regions the
        page's poller swaps in, rendered by the same template as the page."""
        context = live_context(sha256)
        if context is None:
            abort(404)
        if request.args.get("fragment"):
            return render_template("_live_body.html", **context)
        return render_template("live.html", **context)

    @app.route("/api/live/<sha256>")
    def api_live(sha256: str) -> Any:
        context = live_context(sha256)
        if context is None:
            abort(404)
        return jsonify(
            {
                "sha256": context["sha256"],
                "state": context["state"],
                "snapshot": context["snapshot"].to_dict(),
                "live": context["live"],
                "report_url": context["report_url"],
            }
        )

    def console_report_dir(sha256: str) -> Path:
        feed: LiveFeed | None = app.config["LIVE_FEED"]
        return (feed.report_dir_for(sha256) if feed is not None else None) or (
            locate_run_dir(sha256)
        )

    @app.route("/api/console/<sha256>")
    def api_console(sha256: str) -> Any:
        """A run's saved console transcript (the newest 4 MB of it)."""
        if not is_sha256(sha256):
            abort(404)
        sha256 = sha256.lower()
        saved = read_console_log(console_report_dir(sha256), limit=None)
        if not saved.exists:
            abort(404)
        return jsonify(
            {
                "sha256": sha256,
                "total": saved.total,
                "truncated": saved.truncated,
                "sessions": saved.sessions,
                "events": saved.events,
            }
        )

    @app.route("/console/<sha256>.txt")
    def console_text(sha256: str) -> Any:
        """The transcript as plain text, one ``time kind text`` line per event."""
        if not is_sha256(sha256):
            abort(404)
        sha256 = sha256.lower()
        saved = read_console_log(console_report_dir(sha256), limit=None)
        if not saved.exists:
            abort(404)
        lines = []
        for event in saved.events:
            if event["kind"] == "session":
                lines.append(f"\n===== {event['ts']} {event['text']} =====")
            else:
                lines.append(f"{event['clock']} {event['kind']:<12} {event['text']}")
        return Response(
            "\n".join(lines).lstrip("\n") + "\n",
            mimetype="text/plain",
            headers={"Content-Disposition": f'inline; filename="console-{sha256[:12]}.txt"'},
        )

    @app.errorhandler(404)
    def not_found(_error: Any) -> tuple[str, int]:
        requested = request.view_args.get("sha256") if request.view_args else None
        if requested and not is_sha256(requested):
            message = "That is not a valid SHA256, so no run directory can match it."
        elif requested and request.endpoint in ("live_run", "api_live"):
            message = f"No {requested[:12]}… run with a STATE.json under the reports tree."
        elif requested and request.endpoint in ("api_console", "console_text"):
            message = f"No {requested[:12]}… run with a saved console.jsonl under the reports tree."
        elif requested:
            message = f"No {requested[:12]}… run with a 09-summary.json under the reports tree."
        else:
            message = "No such page."
        return render_template("error.html", message=message), 404

    return app


def _api_row(run: RunSummary) -> dict[str, Any]:
    return {
        "sha256": run.sha256,
        "file_name": run.file_name,
        "status": run.status,
        "verdict": run.verdict,
        "risk_level": run.risk_level,
        "confidence": run.confidence,
        "one_sentence_summary": run.headline,
        "ioc_count": run.ioc_count,
        "counts": run.finding_counts,
        "summary_path": str(run.summary_path),
        "modified_at": run.modified_at.isoformat(),
        "error": run.error,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the HyperAgent report web UI")
    parser.add_argument(
        "--reports-dir",
        help="Reports tree to browse. Defaults to $HYPERAGENT_REPORTS_DIR, then <repo>/reports.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="Bind port (default: 5000)")
    parser.add_argument("--debug", action="store_true", help="Enable Flask debug reloader")
    args = parser.parse_args()

    app = create_app(args.reports_dir)
    root: Path = app.config["REPORTS_ROOT"]
    print(f"Reports root: {root}", flush=True)
    if not root.is_dir():
        print("Warning: that directory does not exist; the run list will be empty.", flush=True)
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
