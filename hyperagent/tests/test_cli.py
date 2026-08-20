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
