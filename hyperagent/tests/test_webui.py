"""Smoke tests for the read-only web UI."""
from __future__ import annotations

import json
from pathlib import Path

from hyperagent.console import RunConsole
from hyperagent.tests.live_fixtures import SHA as LIVE_SHA
from hyperagent.tests.live_fixtures import build_run_dir
from webui.app import create_app


SHA = "a" * 64
BROKEN_SHA = "b" * 64


def _write_summary(root: Path, sha256: str = SHA) -> None:
    run_dir = root / sha256
    run_dir.mkdir(parents=True)
    summary = {
        "schema_version": "1.0",
        "stage": "summary",
        "sample": {
            "sha256": sha256,
            "file_name": "sample.exe",
            "absolute_path": "C:/analysis/sample.exe",
            "architecture": "x86",
            "packing_or_protection": "No strong packing evidence was confirmed.",
        },
        "status": "completed",
        "executive_summary": {
            "verdict": "suspicious",
            "confidence": 0.56,
            "confidence_label": "medium",
            "risk_level": "medium",
            "one_sentence_summary": "The sample behaves like a staged loader, but impact is unresolved.",
            "plain_language_assessment": "The run found loader-style behavior, but did not prove final payload execution.",
            "remaining_decision_point": "Validate the unresolved transfer target.",
        },
        "confirmed_findings": [
            {
                "id": "summary.loader",
                "title": "Loader-style staging was supported",
                "summary": "The summary supports staged behavior.",
                "source_refs": ["07-deepdive.json:final_claim_policy.allowed_claims"],
            }
        ],
        "findings_with_caveats": [
            {
                "id": "summary.payload.unresolved",
                "title": "Payload behavior remains unresolved",
                "summary": "A later payload step may exist.",
                "caveat": "Do not claim payload execution yet.",
                "source_refs": ["07-deepdive.json:final_claim_policy.caveated_claims"],
            }
        ],
        "not_supported_claims": [
            {
                "id": "summary.ransomware.unsupported",
                "claim": "The sample is confirmed ransomware.",
                "reason": "The evidence did not support ransomware behavior.",
                "source_refs": ["07-deepdive.json:final_claim_policy.prohibited_claims"],
            }
        ],
        "classification": {
            "malware_type": "loader",
            "malware_family": None,
            "family_status": "unconfirmed",
            "overall_assessment": "Best described as a suspicious loader-like artifact.",
        },
        "confirmed_iocs": {
            "network": [],
            "host": [],
            "persistence": [],
        },
        "recommended_actions": [
            {
                "id": "action.validate-target",
                "priority": 1,
                "target": "Transfer target",
                "action": "Validate the unresolved transfer target.",
                "reason": "It is the highest-value remaining question.",
                "source_refs": ["07-deepdive.json:investigation_targets"],
            }
        ],
        "limitations": [
            "The run did not prove final payload execution.",
        ],
        "upstream_inputs": ["07-deepdive.json"],
    }
    (run_dir / "09-summary.json").write_text(json.dumps(summary), encoding="utf-8")


def test_index_renders_readable_run_cards(tmp_path: Path):
    _write_summary(tmp_path)
    client = create_app(tmp_path).test_client()

    response = client.get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "run-card" in html
    assert "The sample behaves like a staged loader" in html
    assert "readable run cards" not in html
    assert "grid" not in html


def test_detail_renders_dossier_sections_without_tabs(tmp_path: Path):
    _write_summary(tmp_path)
    client = create_app(tmp_path).test_client()

    response = client.get(f"/runs/{SHA}")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Plain-language summary" in html
    assert "Confirmed findings" in html
    assert "Findings with caveats" in html
    assert "Not supported claims" in html
    assert "What this run could not establish" in html
    assert "role=\"tab\"" not in html


def test_recommended_actions_sort_lowest_priority_number_first(tmp_path: Path):
    _write_summary(tmp_path)
    data = json.loads((tmp_path / SHA / "09-summary.json").read_text(encoding="utf-8"))
    data["recommended_actions"].extend(
        [
            {
                "id": "action.lower-priority",
                "priority": 5,
                "target": "Later work",
                "action": "Do this later.",
                "reason": "Lower priority than the main validation target.",
                "source_refs": ["07-deepdive.json:investigation_targets"],
            },
            {
                "id": "action.mid-priority",
                "priority": 3,
                "target": "Middle work",
                "action": "Do this in the middle.",
                "reason": "Medium priority follow-up.",
                "source_refs": ["07-deepdive.json:investigation_targets"],
            },
        ]
    )
    (tmp_path / SHA / "09-summary.json").write_text(json.dumps(data), encoding="utf-8")
    client = create_app(tmp_path).test_client()

    response = client.get(f"/runs/{SHA}")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert html.index("P1") < html.index("P3") < html.index("P5")


def test_unreadable_summary_renders_parse_error(tmp_path: Path):
    run_dir = tmp_path / BROKEN_SHA
    run_dir.mkdir()
    (run_dir / "09-summary.json").write_text("not json", encoding="utf-8")
    client = create_app(tmp_path).test_client()

    response = client.get(f"/runs/{BROKEN_SHA}")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Summary unreadable" in html
    assert "Invalid JSON" in html


def test_invalid_sha_uses_error_template(tmp_path: Path):
    client = create_app(tmp_path).test_client()

    response = client.get("/runs/not-a-sha")

    assert response.status_code == 404
    html = response.get_data(as_text=True)
    assert "Nothing here" in html
    assert "not a valid SHA256" in html


# -- live run page ------------------------------------------------------------


class _Quiet(RunConsole):
    """A run console that keeps its events but prints nothing."""

    def _emit_line_locked(self, line, kind):
        return

    def _emit_inline_locked(self, text, kind):
        return


def _live_console(report_dir: Path) -> RunConsole:
    console = _Quiet(enabled=True, force_tty=False)
    console.bind_run(
        sample_sha256=LIVE_SHA,
        report_dir=report_dir,
        stage_ids=["01-prepare-env", "02-static-pass1", "03-unpack", "05-dynamic"],
        model="claude-opus-5-5",
    )
    console.start()
    console.stage_transition(
        index=3, total=4, stage_id="03-unpack", stage_name="hyperagent-unpack", attempt=2
    )
    console.tool_call("read_file", {"path": "<script>alert(1)</script>"})
    return console


def test_live_page_without_feed_shows_artifacts_only(tmp_path: Path):
    build_run_dir(tmp_path)
    client = create_app(tmp_path).test_client()

    response = client.get(f"/live/{LIVE_SHA}")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "No live console" in html
    assert "No console output was saved" in html
    assert "02-static-pass1" in html
    assert "evil.example.com" in html
    assert "Decoded payload executed" in html
    assert 'data-live-src="/live/' in html
    assert "http-equiv=\"refresh\"" in html


def test_live_page_with_feed_shows_trace_and_running_stage(tmp_path: Path):
    report_dir = build_run_dir(tmp_path)
    console = _live_console(report_dir)
    client = create_app(tmp_path, live_feed=console).test_client()

    html = client.get(f"/live/{LIVE_SHA}").get_data(as_text=True)

    assert 'class="live-pill live-running"' in html
    assert "attempt 2" in html
    assert "Agent trace" in html
    assert "read_file" in html
    # Sample- and model-derived text is escaped, never rendered as markup.
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "stage-running" in html


def test_live_fragment_returns_only_the_swappable_regions(tmp_path: Path):
    report_dir = build_run_dir(tmp_path)
    client = create_app(tmp_path, live_feed=_live_console(report_dir)).test_client()

    html = client.get(f"/live/{LIVE_SHA}?fragment=1").get_data(as_text=True)

    assert "<html" not in html
    regions = ("live-state", "live-hero", "live-trace", "live-stages", "live-iocs", "live-evidence")
    for region in regions:
        assert f'id="{region}"' in html


def test_live_api_returns_snapshot_and_console_state(tmp_path: Path):
    report_dir = build_run_dir(tmp_path)
    console = _live_console(report_dir)
    client = create_app(tmp_path, live_feed=console).test_client()

    payload = client.get(f"/api/live/{LIVE_SHA}").get_json()

    assert payload["state"] == "running"
    assert payload["live"]["stage_id"] == "03-unpack"
    stages = {stage["stage_id"]: stage["status"] for stage in payload["snapshot"]["stages"]}
    assert stages == {
        "01-prepare-env": "completed",
        "02-static-pass1": "completed",
        "03-unpack": "running",
        "05-dynamic": "completed",
    }
    assert payload["report_url"] is None

    console.finish()
    assert client.get(f"/api/live/{LIVE_SHA}").get_json()["state"] == "stopped"


def test_live_page_links_the_full_report_once_the_summary_exists(tmp_path: Path):
    build_run_dir(tmp_path, LIVE_SHA)
    _write_summary(tmp_path / "other", SHA)  # unrelated run in another root
    (tmp_path / LIVE_SHA / "09-summary.json").write_text(
        (tmp_path / "other" / SHA / "09-summary.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    client = create_app(tmp_path).test_client()

    html = client.get(f"/live/{LIVE_SHA}").get_data(as_text=True)

    assert f'href="/runs/{LIVE_SHA}"' in html


def test_live_page_404s_for_unknown_runs(tmp_path: Path):
    client = create_app(tmp_path).test_client()

    response = client.get(f"/live/{'d' * 64}")

    assert response.status_code == 404
    assert "STATE.json" in response.get_data(as_text=True)
    assert client.get("/live/not-a-sha").status_code == 404


def test_index_links_the_active_live_run(tmp_path: Path):
    report_dir = build_run_dir(tmp_path)
    client = create_app(tmp_path, live_feed=_live_console(report_dir)).test_client()

    html = client.get("/").get_data(as_text=True)

    assert f'href="/live/{LIVE_SHA}"' in html
    assert "Watch live" in html


def test_finished_run_keeps_its_console_output_in_the_dashboard(tmp_path: Path):
    report_dir = build_run_dir(tmp_path)
    console = _live_console(report_dir)
    console.assistant_label()
    console.write_inline("streamed answer that was still open")
    console.finish()
    # A dashboard with no live feed -- the CLI has exited, or the page comes
    # from a separately started webui -- reads the saved transcript instead.
    client = create_app(tmp_path).test_client()

    html = client.get(f"/live/{LIVE_SHA}").get_data(as_text=True)

    assert "Saved console output" in html
    assert "ev ev-session" in html
    assert "Stage 3/4 → 03-unpack" in html
    assert "read_file" in html
    assert "streamed answer that was still open" in html
    assert "<script>alert(1)</script>" not in html
    assert f'href="/console/{LIVE_SHA}.txt"' in html

    text = client.get(f"/console/{LIVE_SHA}.txt")
    assert text.mimetype == "text/plain"
    body = text.get_data(as_text=True)
    assert "===== " in body and "Console session · 4 stages · claude-opus-5-5" in body
    assert "tool" in body and "read_file" in body

    payload = client.get(f"/api/console/{LIVE_SHA}").get_json()
    assert payload["sessions"] == 1
    assert [event["kind"] for event in payload["events"]][:2] == ["session", "stage"]


def test_detail_page_links_saved_console_output(tmp_path: Path):
    _write_summary(tmp_path)
    client = create_app(tmp_path).test_client()
    assert "Console output" not in client.get(f"/runs/{SHA}").get_data(as_text=True)

    (tmp_path / SHA / "console.jsonl").write_text(
        json.dumps({"session": "s", "seq": 1, "kind": "info", "text": "hello"}) + "\n",
        encoding="utf-8",
    )
    html = client.get(f"/runs/{SHA}").get_data(as_text=True)

    assert f'href="/live/{SHA}"' in html and "Console output" in html
    # A finished run with only a summary and a transcript still has a page.
    assert "hello" in client.get(f"/live/{SHA}").get_data(as_text=True)


def test_console_routes_404_without_a_transcript(tmp_path: Path):
    build_run_dir(tmp_path)
    client = create_app(tmp_path).test_client()

    assert client.get(f"/console/{LIVE_SHA}.txt").status_code == 404
    response = client.get(f"/api/console/{LIVE_SHA}")
    assert response.status_code == 404
    assert "console.jsonl" in response.get_data(as_text=True)
    assert client.get("/console/..%2f..%2fetc.txt").status_code == 404


def test_live_trace_collapses_tool_bursts_into_expandable_groups(tmp_path: Path):
    report_dir = build_run_dir(tmp_path)
    console = _live_console(report_dir)  # one read_file call, still pending
    client = create_app(tmp_path, live_feed=console).test_client()

    html = client.get(f"/live/{LIVE_SHA}").get_data(as_text=True)
    assert '<details class="actions" data-key="act-' in html
    assert "Read 1 file" in html
    assert 'class="act-pending">&middot; Read script&gt; &hellip;' in html  # basename, escaped
    assert "<script>alert(1)</script>" not in html

    console.tool_result("Error: missing", is_error=True, name="read_file")
    console.finish()
    saved = create_app(tmp_path).test_client().get(f"/live/{LIVE_SHA}").get_data(as_text=True)
    assert "1 failed" in saved
    assert 'class="act act-error"' in saved
    assert "&hellip;</span>" not in saved


def test_dashboard_lists_runs_linked_from_other_folders(tmp_path: Path):
    from hyperagent.run_registry import link_run

    root = tmp_path / "repo-reports"
    root.mkdir()
    _write_summary(tmp_path / "dataset" / "reports", SHA)  # outside the reports root
    link_run(SHA, tmp_path / "dataset" / "reports" / SHA)
    live_dir = build_run_dir(tmp_path / "experiments")  # STATE.json only, no summary
    link_run(LIVE_SHA, live_dir)
    (live_dir / "console.jsonl").write_text(
        json.dumps({"session": "s", "seq": 1, "kind": "info", "text": "linked trace"}) + "\n",
        encoding="utf-8",
    )
    client = create_app(root).test_client()

    index = client.get("/").get_data(as_text=True)
    assert f'href="/runs/{SHA}"' in index
    assert "+2 linked" in index
    detail = client.get(f"/runs/{SHA}").get_data(as_text=True)
    assert "Report folder" in detail and "dataset" in detail
    assert client.get(f"/api/runs/{SHA}").status_code == 200
    assert client.get(f"/search?q={SHA}").headers["Location"].endswith(f"/runs/{SHA}")
    live = client.get(f"/live/{LIVE_SHA}").get_data(as_text=True)
    assert "02-static-pass1" in live and "linked trace" in live
    assert client.get(f"/console/{LIVE_SHA}.txt").status_code == 200
