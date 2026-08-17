"""Tests for hyperagent.engine.launcher."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from hyperagent import pipeline_state
from hyperagent.engine.launcher import STAGES, run_pipeline_with_config
from hyperagent.providers.base import CompletionResult, LLMProvider
from hyperagent.tools import vmware_tools


class _DummyProvider(LLMProvider):
    def complete(self, messages, *, tools=None, system_prompt="", max_tokens=None, temperature=None):
        return CompletionResult(content="done", tool_calls=[], stop_reason="end_turn")

    def count_tokens(self, text: str) -> int:
        return len(text)

    def max_context_tokens(self) -> int:
        return 100_000


@pytest.fixture()
def sample_file(tmp_path: Path) -> Path:
    sample = tmp_path / "sample.exe"
    sample.write_bytes(b"MZ")
    return sample


@pytest.fixture()
def config(tmp_path: Path):
    return SimpleNamespace(
        skills_root=tmp_path / "skills",
        reports_root=tmp_path / "reports",
        max_stage_attempts=2,
        checkpoint_threshold=0.75,
        provider=SimpleNamespace(
            model="claude-sonnet-test",
            name="anthropic",
            api_key="sk-test",
            max_output_tokens=1024,
            temperature=None,
            stage_models={},
        ),
        vmware=SimpleNamespace(),
    )


def _stage_skill_tree(root: Path) -> None:
    for stage in {stage.skill for stage in STAGES}:
        skill_dir = root / stage
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test\ndescription: test\n---\n\n# Role\n\nDo work.\n",
            encoding="utf-8",
        )
        (skill_dir / "schema.json").write_text('{"type":"object"}', encoding="utf-8")


def test_launcher_skips_completed_stage_with_valid_artifact(monkeypatch, sample_file: Path, config):
    _stage_skill_tree(config.skills_root)
    report_dir = config.reports_root / ("a" * 64)
    report_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("hyperagent.engine.launcher._sha256_of", lambda _p: "a" * 64)
    monkeypatch.setattr("hyperagent.engine.launcher.build_full_registry", lambda _cfg: (SimpleNamespace(get_tools_for_stage=lambda _sid: [],), []))

    pipeline_state.ensure_state(report_dir, "a" * 64, str(sample_file))
    out = report_dir / "01-prepare-env.json"
    out.write_text("{}", encoding="utf-8")
    pipeline_state.complete(report_dir, "01-prepare-env", str(out))

    result = asyncio.run(run_pipeline_with_config(sample_file, config, stage_id="01-prepare-env"))
    assert result.stages == []


def test_launcher_stops_on_state_drift(monkeypatch, sample_file: Path, config):
    _stage_skill_tree(config.skills_root)
    report_dir = config.reports_root / ("b" * 64)
    report_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("hyperagent.engine.launcher._sha256_of", lambda _p: "b" * 64)
    monkeypatch.setattr("hyperagent.engine.launcher.build_full_registry", lambda _cfg: (SimpleNamespace(get_tools_for_stage=lambda _sid: []), []))

    pipeline_state.ensure_state(report_dir, "b" * 64, str(sample_file))
    pipeline_state.complete(report_dir, "01-prepare-env", str(report_dir / "missing.json"))

    result = asyncio.run(run_pipeline_with_config(sample_file, config, stage_id="01-prepare-env"))
    assert len(result.stages) == 1
    assert result.stages[0].stage_status == "failed"


def test_launcher_retries_when_stage_checkpointed(monkeypatch, sample_file: Path, config):
    _stage_skill_tree(config.skills_root)
    report_dir = config.reports_root / ("c" * 64)
    report_dir.mkdir(parents=True, exist_ok=True)
    pipeline_state.ensure_state(report_dir, "c" * 64, str(sample_file))

    class _Registry:
        def get_tools_for_stage(self, _sid):
            return []

    calls = {"count": 0}

    class _Loop:
        def __init__(self, *args, **kwargs):
            self.last_messages = []

        def run(self, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                progress = report_dir / "_state" / "01-prepare-env.progress.md"
                progress.parent.mkdir(parents=True, exist_ok=True)
                progress.write_text("resume me", encoding="utf-8")
                pipeline_state.checkpoint(report_dir, "01-prepare-env", str(progress), "test")
            else:
                out = report_dir / "01-prepare-env.json"
                out.write_text("{}", encoding="utf-8")
                pipeline_state.complete(report_dir, "01-prepare-env", str(out))
            return "ok"

    monkeypatch.setattr("hyperagent.engine.launcher._sha256_of", lambda _p: "c" * 64)
    monkeypatch.setattr("hyperagent.engine.launcher.build_full_registry", lambda _cfg: (_Registry(), []))
    monkeypatch.setattr("hyperagent.engine.launcher.create_provider", lambda *a, **k: _DummyProvider())
    monkeypatch.setattr("hyperagent.engine.launcher.AgentLoop", _Loop)

    result = asyncio.run(run_pipeline_with_config(sample_file, config, stage_id="01-prepare-env"))
    assert calls["count"] == 2
    assert len(result.stages) == 1
    assert result.stages[0].stage_status == "completed"


def test_launcher_fails_when_stage_exits_without_state_update(monkeypatch, sample_file: Path, config):
    _stage_skill_tree(config.skills_root)
    report_dir = config.reports_root / ("d" * 64)
    report_dir.mkdir(parents=True, exist_ok=True)
    pipeline_state.ensure_state(report_dir, "d" * 64, str(sample_file))

    class _Registry:
        def get_tools_for_stage(self, _sid):
            return []

    class _Loop:
        def __init__(self, *args, **kwargs):
            self.last_messages = []

        def run(self, **kwargs):
            return "ok"

    monkeypatch.setattr("hyperagent.engine.launcher._sha256_of", lambda _p: "d" * 64)
    monkeypatch.setattr("hyperagent.engine.launcher.build_full_registry", lambda _cfg: (_Registry(), []))
    monkeypatch.setattr("hyperagent.engine.launcher.create_provider", lambda *a, **k: _DummyProvider())
    monkeypatch.setattr("hyperagent.engine.launcher.AgentLoop", _Loop)

    result = asyncio.run(run_pipeline_with_config(sample_file, config, stage_id="01-prepare-env"))
    assert len(result.stages) == 1
    assert result.stages[0].stage_status == "failed"


def test_launcher_reverts_vm_after_dynamic_stage_succeeds(monkeypatch, sample_file: Path, config):
    _stage_skill_tree(config.skills_root)
    report_dir = config.reports_root / ("e" * 64)
    report_dir.mkdir(parents=True, exist_ok=True)
    pipeline_state.ensure_state(report_dir, "e" * 64, str(sample_file))

    class _Registry:
        def get_tools_for_stage(self, _sid):
            return []

    class _Loop:
        def __init__(self, *args, **kwargs):
            self.last_messages = []

        def run(self, **kwargs):
            out = report_dir / "05-dynamic.json"
            out.write_text("{}", encoding="utf-8")
            pipeline_state.complete(report_dir, "05-dynamic", str(out))
            return "ok"

    revert_calls: list[object] = []
    monkeypatch.setattr(vmware_tools, "vm_auto_revert_after_dynamic", lambda cfg: revert_calls.append(cfg))
    monkeypatch.setattr("hyperagent.engine.launcher._sha256_of", lambda _p: "e" * 64)
    monkeypatch.setattr("hyperagent.engine.launcher.build_full_registry", lambda _cfg: (_Registry(), []))
    monkeypatch.setattr("hyperagent.engine.launcher.create_provider", lambda *a, **k: _DummyProvider())
    monkeypatch.setattr("hyperagent.engine.launcher.AgentLoop", _Loop)

    result = asyncio.run(run_pipeline_with_config(sample_file, config, stage_id="05-dynamic"))
    assert len(result.stages) == 1
    assert result.stages[0].stage_status == "completed"
    assert revert_calls == [config.vmware]


def test_launcher_reverts_vm_after_dynamic_stage_fails(monkeypatch, sample_file: Path, config):
    _stage_skill_tree(config.skills_root)
    report_dir = config.reports_root / ("f" * 64)
    report_dir.mkdir(parents=True, exist_ok=True)
    pipeline_state.ensure_state(report_dir, "f" * 64, str(sample_file))

    class _Registry:
        def get_tools_for_stage(self, _sid):
            return []

    class _Loop:
        def __init__(self, *args, **kwargs):
            self.last_messages = []

        def run(self, **kwargs):
            return "ok"

    revert_calls: list[object] = []
    monkeypatch.setattr(vmware_tools, "vm_auto_revert_after_dynamic", lambda cfg: revert_calls.append(cfg))
    monkeypatch.setattr("hyperagent.engine.launcher._sha256_of", lambda _p: "f" * 64)
    monkeypatch.setattr("hyperagent.engine.launcher.build_full_registry", lambda _cfg: (_Registry(), []))
    monkeypatch.setattr("hyperagent.engine.launcher.create_provider", lambda *a, **k: _DummyProvider())
    monkeypatch.setattr("hyperagent.engine.launcher.AgentLoop", _Loop)

    result = asyncio.run(run_pipeline_with_config(sample_file, config, stage_id="05-dynamic"))
    assert len(result.stages) == 1
    assert result.stages[0].stage_status == "failed"
    assert revert_calls == [config.vmware]
