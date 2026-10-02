"""Tests for hyperagent.cli."""
from __future__ import annotations

from pathlib import Path

from hyperagent import cli


class _Runtime:
    pipeline_profile = "full"
    skip_dynamic = False
    skip_intel = False
    reuse_completed_stages = True
    start_ida_mcp = "auto"


class _Provider:
    name = "anthropic"
    model = ""
    thinking_level = ""
    extended_thinking = False
    console_mode = "off"


class _Config:
    provider = _Provider()
    runtime = _Runtime()


class _Metrics:
    stages = []


def test_analyze_cli_applies_runtime_flags(monkeypatch, tmp_path: Path):
    sample = tmp_path / "sample.exe"
    sample.write_bytes(b"MZ")
    config = _Config()
    captured = {}

    monkeypatch.setattr(cli, "load_config", lambda _path: config)

    async def fake_run_pipeline_with_config(**kwargs):
        captured.update(kwargs)
        metrics = _Metrics()
        metrics.stages = [type("_Stage", (), {"stage_status": "completed"})()]
        return metrics

    monkeypatch.setattr(cli, "run_pipeline_with_config", fake_run_pipeline_with_config)

    rc = cli.main([
        "analyze",
        str(sample),
        "--profile",
        "fast",
        "--skip-dynamic",
        "--skip-intel",
        "--no-cache",
        "--ida-mcp",
        "never",
    ])

    assert rc == 0
    assert captured["sample_path"] == sample
    assert config.runtime.pipeline_profile == "fast"
    assert config.runtime.skip_dynamic is True
    assert config.runtime.skip_intel is True
    assert config.runtime.reuse_completed_stages is False
    assert config.runtime.start_ida_mcp == "never"


def test_analyze_cli_sets_thinking_level(monkeypatch, tmp_path: Path):
    sample = tmp_path / "sample.exe"
    sample.write_bytes(b"MZ")
    config = _Config()

    monkeypatch.setattr(cli, "load_config", lambda _path: config)

    async def fake_run_pipeline_with_config(**_kwargs):
        metrics = _Metrics()
        metrics.stages = [type("_Stage", (), {"stage_status": "completed"})()]
        return metrics

    monkeypatch.setattr(cli, "run_pipeline_with_config", fake_run_pipeline_with_config)

    rc = cli.main(["analyze", str(sample), "--thinking", "high"])

    assert rc == 0
    assert config.provider.thinking_level == "high"


def test_analyze_cli_accepts_dynamic_only_profile(monkeypatch, tmp_path: Path):
    sample = tmp_path / "sample.exe"
    sample.write_bytes(b"MZ")
    config = _Config()

    monkeypatch.setattr(cli, "load_config", lambda _path: config)

    async def fake_run_pipeline_with_config(**_kwargs):
        metrics = _Metrics()
        metrics.stages = [type("_Stage", (), {"stage_status": "completed"})()]
        return metrics

    monkeypatch.setattr(cli, "run_pipeline_with_config", fake_run_pipeline_with_config)

    rc = cli.main(["analyze", str(sample), "--profile", "dynamic-only"])

    assert rc == 0
    assert config.runtime.pipeline_profile == "dynamic-only"


def test_static_only_cli_overrides_profile(monkeypatch, tmp_path: Path):
    sample = tmp_path / "sample.exe"
    sample.write_bytes(b"MZ")
    config = _Config()

    monkeypatch.setattr(cli, "load_config", lambda _path: config)

    async def fake_run_pipeline_with_config(**_kwargs):
        metrics = _Metrics()
        metrics.stages = [type("_Stage", (), {"stage_status": "completed"})()]
        return metrics

    monkeypatch.setattr(cli, "run_pipeline_with_config", fake_run_pipeline_with_config)

    rc = cli.main(["analyze", str(sample), "--profile", "fast", "--static-only"])

    assert rc == 0
    assert config.runtime.pipeline_profile == "static-only"


class _RecordingConsole:
    def __init__(self) -> None:
        self.viewer = None
        self.finished = False

    def set_viewer(self, status, *, url=None, detail=""):
        self.viewer = (status, url, detail)

    def finish(self):
        self.finished = True

    def write_line(self, *_args, **_kwargs):
        return


def _patch_mdebug(monkeypatch, tmp_path: Path, start_dashboard):
    config = _Config()
    config.reports_root = tmp_path / "reports"
    console = _RecordingConsole()
    captured = {}

    def fake_create_run_console(**kwargs):
        captured["console_kwargs"] = kwargs
        return console

    monkeypatch.setattr(cli, "load_config", lambda _path: config)
    monkeypatch.setattr(cli, "create_run_console", fake_create_run_console)
    monkeypatch.setattr(cli, "start_dashboard", start_dashboard)

    async def fake_run_pipeline_with_config(**kwargs):
        captured["run_console"] = kwargs["run_console"]
        metrics = _Metrics()
        metrics.stages = [type("_Stage", (), {"stage_status": "completed"})()]
        return metrics

    monkeypatch.setattr(cli, "run_pipeline_with_config", fake_run_pipeline_with_config)
    return config, console, captured


def test_mdebug_serves_the_live_dashboard_and_closes_it(monkeypatch, tmp_path: Path):
    sample = tmp_path / "sample.exe"
    sample.write_bytes(b"MZ")
    started = {}

    class _Dashboard:
        url = "http://127.0.0.1:5123"
        closed = False

        def close(self):
            _Dashboard.closed = True

    def fake_start_dashboard(**kwargs):
        started.update(kwargs)
        return _Dashboard()

    config, console, captured = _patch_mdebug(monkeypatch, tmp_path, fake_start_dashboard)

    rc = cli.main(["analyze", str(sample), "--mdebug", "--dashboard-port", "5123", "--no-tui"])

    assert rc == 0
    assert captured["console_kwargs"] == {"prefer_tui": False}
    assert captured["run_console"] is console
    assert started["live_feed"] is console
    assert started["port"] == 5123
    assert started["reports_root"] == config.reports_root
    assert console.viewer == ("running", "http://127.0.0.1:5123", "")
    assert console.finished is True
    assert _Dashboard.closed is True


def test_mdebug_keeps_running_when_the_dashboard_cannot_start(monkeypatch, tmp_path: Path):
    sample = tmp_path / "sample.exe"
    sample.write_bytes(b"MZ")

    def failing_start_dashboard(**_kwargs):
        raise cli.DashboardUnavailable("no free port in 5000-5009")

    _config, console, _captured = _patch_mdebug(monkeypatch, tmp_path, failing_start_dashboard)

    rc = cli.main(["analyze", str(sample), "--mdebug"])

    assert rc == 0
    assert console.viewer == ("failed", None, "no free port in 5000-5009")


def test_no_dashboard_skips_the_server(monkeypatch, tmp_path: Path):
    sample = tmp_path / "sample.exe"
    sample.write_bytes(b"MZ")

    def unexpected_start_dashboard(**_kwargs):
        raise AssertionError("dashboard should not start")

    _config, console, _captured = _patch_mdebug(monkeypatch, tmp_path, unexpected_start_dashboard)

    assert cli.main(["analyze", str(sample), "--mdebug", "--no-dashboard"]) == 0
    assert console.viewer is None
