"""Tests for hyperagent.dashboard (the in-process live web UI)."""

from __future__ import annotations

import socket
import urllib.request
from pathlib import Path

import pytest

from hyperagent import dashboard
from hyperagent.tests.live_fixtures import SHA, build_run_dir


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class _Feed:
    def report_dir_for(self, _sha256):
        return None

    def live_status(self, _sha256):
        return None

    def active_runs(self):
        return []


def test_dashboard_serves_the_live_page_on_loopback(tmp_path: Path):
    build_run_dir(tmp_path)
    server = dashboard.start_dashboard(reports_root=tmp_path, live_feed=_Feed(), port=_free_port())
    try:
        assert server.url.startswith("http://127.0.0.1:")
        with urllib.request.urlopen(f"{server.url}/live/{SHA}", timeout=5) as response:
            body = response.read().decode("utf-8")
        assert response.status == 200
        assert "02-static-pass1" in body
    finally:
        server.close()


def test_dashboard_moves_past_a_busy_port(tmp_path: Path):
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        taken = busy.getsockname()[1]
        server = dashboard.start_dashboard(
            reports_root=tmp_path, live_feed=_Feed(), port=taken, attempts=20
        )
        try:
            assert not server.url.endswith(f":{taken}")
        finally:
            server.close()


@pytest.mark.parametrize("failure", [OSError("address in use"), SystemExit(1)])
def test_dashboard_reports_when_no_port_is_free(tmp_path: Path, monkeypatch, failure):
    # werkzeug signals a failed bind with sys.exit(1); that must surface as
    # DashboardUnavailable, never end the analysis run.
    def refuse(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr("werkzeug.serving.make_server", refuse)

    with pytest.raises(dashboard.DashboardUnavailable, match="no free port"):
        dashboard.start_dashboard(
            reports_root=tmp_path, live_feed=_Feed(), port=_free_port(), attempts=2
        )
