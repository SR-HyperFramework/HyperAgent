"""Flask web UI for browsing HyperAgent analysis summaries.

Read-only: it serves whatever ``09-summary.json`` files already exist under the
reports tree. It never runs the pipeline, never writes to a report directory,
and never reads a sample binary.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

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

REPO_ROOT = Path(__file__).resolve().parents[1]
SORT_KEYS = ("recent", "verdict", "risk", "confidence", "name")


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


def create_app(reports_root: str | os.PathLike[str] | None = None) -> Flask:
    app = Flask(__name__)
    app.config["REPORTS_ROOT"] = resolve_reports_root(reports_root)

    @app.context_processor
    def inject_globals() -> dict[str, Any]:
        return {
            "reports_root": app.config["REPORTS_ROOT"],
            "verdicts": VERDICTS,
            "risk_levels": RISK_LEVELS,
            "asset": asset_url,
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
        runs = discover_runs(root)

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
        if is_sha256(query) and get_run(app.config["REPORTS_ROOT"], query) is not None:
            return redirect(url_for("run_detail", sha256=query.lower()))
        return redirect(url_for("index", q=query or None))

    @app.route("/runs/<sha256>")
    def run_detail(sha256: str) -> str:
        run = get_run(app.config["REPORTS_ROOT"], sha256)
        if run is None:
            abort(404)
        return render_template("detail.html", run=run)

    @app.route("/api/runs")
    def api_runs() -> Any:
        runs = discover_runs(app.config["REPORTS_ROOT"])
        return jsonify(
            {
                "reports_root": str(app.config["REPORTS_ROOT"]),
                "count": len(runs),
                "runs": [_api_row(run) for run in runs],
            }
        )

    @app.route("/api/runs/<sha256>")
    def api_run(sha256: str) -> Any:
        run = get_run(app.config["REPORTS_ROOT"], sha256)
        if run is None:
            abort(404)
        if not run.ok:
            return jsonify({"sha256": run.sha256, "error": run.error}), 422
        # The stage artifact verbatim — the UI is a view over it, not a rewrite.
        return jsonify(run.data)

    @app.errorhandler(404)
    def not_found(_error: Any) -> tuple[str, int]:
        requested = request.view_args.get("sha256") if request.view_args else None
        if requested and not is_sha256(requested):
            message = "That is not a valid SHA256, so no run directory can match it."
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
