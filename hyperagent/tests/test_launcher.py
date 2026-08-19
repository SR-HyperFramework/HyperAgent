"""Tests for hyperagent.engine.launcher."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from hyperagent import pipeline_state
from hyperagent.engine.launcher import STAGES, _artifact_validation_error, _build_stage_prompt, run_pipeline_with_config
from hyperagent.tools.base import ToolDefinition
from hyperagent.providers.base import CompletionResult, LLMProvider
from hyperagent.tools import vmware_tools
from hyperagent.tools.path_scope import compute_run_scope


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
            console_mode="off",
        ),
        vmware=SimpleNamespace(),
        x64dbg_mcp=SimpleNamespace(url="http://127.0.0.1:1/mcp", timeout=2),
        ida_mcp=SimpleNamespace(url="http://127.0.0.1:1/mcp", timeout=2),
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
    monkeypatch.setattr("hyperagent.engine.launcher.ensure_idalib_mcp", lambda _cfg: None)
    monkeypatch.setattr("hyperagent.engine.launcher.stop_idalib_mcp", lambda _proc: None)
    monkeypatch.setattr(
        "hyperagent.engine.launcher.build_full_registry",
        lambda _cfg, _scope: (SimpleNamespace(get_tools_for_stage=lambda _sid: []), []),
    )

    pipeline_state.ensure_state(report_dir, "a" * 64, str(sample_file))
    out = report_dir / "01-prepare-env.json"
    out.write_text("{}", encoding="utf-8")
    pipeline_state.complete(report_dir, "01-prepare-env", str(out))

    result = asyncio.run(run_pipeline_with_config(sample_file, config, stage_id="01-prepare-env"))
    assert result.stages == []


def test_launcher_builds_scope_from_sample_and_report_dir(monkeypatch, sample_file: Path, config):
    _stage_skill_tree(config.skills_root)
    captured = {}
    stage_hash = "scope" * 16
    report_dir = config.reports_root / stage_hash

    class _Registry:
        def get_tools_for_stage(self, _sid):
            return []

    monkeypatch.setattr("hyperagent.engine.launcher._sha256_of", lambda _p: stage_hash)

    def fake_build_full_registry(_cfg, scope):
        captured["scope"] = scope
        return _Registry(), []

    monkeypatch.setattr("hyperagent.engine.launcher.ensure_idalib_mcp", lambda _cfg: None)
    monkeypatch.setattr("hyperagent.engine.launcher.stop_idalib_mcp", lambda _proc: None)

    monkeypatch.setattr("hyperagent.engine.launcher.build_full_registry", fake_build_full_registry)
    monkeypatch.setattr("hyperagent.engine.launcher.create_provider", lambda *a, **k: _DummyProvider())

    class _Loop:
        def __init__(self, *args, **kwargs):
            self.last_messages = []

        def run(self, **kwargs):
            out = report_dir / "01-prepare-env.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("{}", encoding="utf-8")
            pipeline_state.complete(report_dir, "01-prepare-env", str(out))
            return "ok"

    monkeypatch.setattr("hyperagent.engine.launcher.AgentLoop", _Loop)

    result = asyncio.run(run_pipeline_with_config(sample_file, config, stage_id="01-prepare-env"))
    assert len(result.stages) == 1

    expected_scope = compute_run_scope(sample_file, report_dir, config.skills_root)
    assert captured["scope"].read_roots == expected_scope.read_roots
    assert captured["scope"].write_roots == expected_scope.write_roots


def test_launcher_refreshes_x64dbg_tools_before_dynamic_stage(monkeypatch, sample_file: Path, config):
    _stage_skill_tree(config.skills_root)
    report_dir = config.reports_root / ("refresh" * 8)
    report_dir.mkdir(parents=True, exist_ok=True)
    pipeline_state.ensure_state(report_dir, "refresh" * 8, str(sample_file))

    class _Registry:
        def __init__(self):
            self.refresh_calls = []

        def get_tools_for_stage(self, stage_id):
            if stage_id == "05-dynamic":
                return [ToolDefinition(name="debug_init", description="", parameters={}, handler=lambda **_: None, source="x64dbg")]
            return []

    fake_registry = _Registry()

    monkeypatch.setattr("hyperagent.engine.launcher._sha256_of", lambda _p: "refresh" * 8)
    monkeypatch.setattr("hyperagent.engine.launcher.ensure_idalib_mcp", lambda _cfg: None)
    monkeypatch.setattr("hyperagent.engine.launcher.stop_idalib_mcp", lambda _proc: None)
    monkeypatch.setattr("hyperagent.engine.launcher.build_full_registry", lambda _cfg, _scope: (fake_registry, [object(), object()]))
    monkeypatch.setattr("hyperagent.engine.launcher.refresh_x64dbg_tools", lambda registry, clients, endpoint, stage_id, current_client=None: registry.refresh_calls.append(stage_id) or current_client)
    monkeypatch.setattr("hyperagent.engine.launcher.create_provider", lambda *a, **k: _DummyProvider())
    monkeypatch.setattr(vmware_tools, "vm_auto_revert_after_dynamic", lambda cfg: None)

    class _Loop:
        def __init__(self, *args, **kwargs):
            self.last_messages = []

        def run(self, **kwargs):
            out = report_dir / "05-dynamic.json"
            out.write_text("{}", encoding="utf-8")
            pipeline_state.complete(report_dir, "05-dynamic", str(out))
            return "ok"

    monkeypatch.setattr("hyperagent.engine.launcher.AgentLoop", _Loop)

    result = asyncio.run(run_pipeline_with_config(sample_file, config, stage_id="05-dynamic"))
    assert len(result.stages) == 1
    assert result.stages[0].stage_status == "completed"
    assert fake_registry.refresh_calls == ["05-dynamic"]


def test_build_stage_prompt_includes_schema_and_common_scripts_paths(sample_file: Path, config):
    _stage_skill_tree(config.skills_root)
    report_dir = config.reports_root / ("prompt" * 10)
    state_path = report_dir / "STATE.json"
    skill_doc = SimpleNamespace(schema_path=config.skills_root / "hyperagent-prepare-env" / "schema.json")

    prompt = _build_stage_prompt(
        sample_file,
        report_dir,
        STAGES[0],
        state_path,
        skill_doc,
        config.skills_root,
    )

    assert f"Stage schema path: {skill_doc.schema_path}" in prompt
    assert f"Common scripts directory: {config.skills_root / '_hyperagent-common' / 'scripts'}" in prompt
    assert f"Default stage output path: {report_dir / '01-prepare-env.json'}" in prompt
    assert "Operational contract:" in prompt
    assert "Do not manually discover SKILL.md, schema.json, or validator-script paths" in prompt
    assert "Do not write STATE.json directly" in prompt
    assert "If a filesystem path is denied by scope policy" in prompt


def test_build_stage_prompt_omits_schema_line_when_schema_missing(sample_file: Path, config):
    _stage_skill_tree(config.skills_root)
    report_dir = config.reports_root / ("noschema" * 8)
    state_path = report_dir / "STATE.json"
    skill_doc = SimpleNamespace(schema_path=None)

    prompt = _build_stage_prompt(
        sample_file,
        report_dir,
        next(stage for stage in STAGES if stage.stage_id == "08-report"),
        state_path,
        skill_doc,
        config.skills_root,
    )

    assert "Stage schema path:" not in prompt
    assert f"Common scripts directory: {config.skills_root / '_hyperagent-common' / 'scripts'}" in prompt
    assert "Operational contract:" in prompt
    assert "Do not write STATE.json directly" in prompt


def test_launcher_stops_on_state_drift(monkeypatch, sample_file: Path, config):
    _stage_skill_tree(config.skills_root)
    report_dir = config.reports_root / ("b" * 64)
    report_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("hyperagent.engine.launcher._sha256_of", lambda _p: "b" * 64)
    monkeypatch.setattr("hyperagent.engine.launcher.ensure_idalib_mcp", lambda _cfg: None)
    monkeypatch.setattr("hyperagent.engine.launcher.stop_idalib_mcp", lambda _proc: None)
    monkeypatch.setattr(
        "hyperagent.engine.launcher.build_full_registry",
        lambda _cfg, _scope: (SimpleNamespace(get_tools_for_stage=lambda _sid: []), []),
    )

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
    monkeypatch.setattr("hyperagent.engine.launcher.ensure_idalib_mcp", lambda _cfg: None)
    monkeypatch.setattr("hyperagent.engine.launcher.stop_idalib_mcp", lambda _proc: None)
    monkeypatch.setattr("hyperagent.engine.launcher.build_full_registry", lambda _cfg, _scope: (_Registry(), []))
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
    monkeypatch.setattr("hyperagent.engine.launcher.ensure_idalib_mcp", lambda _cfg: None)
    monkeypatch.setattr("hyperagent.engine.launcher.stop_idalib_mcp", lambda _proc: None)
    monkeypatch.setattr("hyperagent.engine.launcher.build_full_registry", lambda _cfg, _scope: (_Registry(), []))
    monkeypatch.setattr("hyperagent.engine.launcher.create_provider", lambda *a, **k: _DummyProvider())
    monkeypatch.setattr("hyperagent.engine.launcher.AgentLoop", _Loop)

    result = asyncio.run(run_pipeline_with_config(sample_file, config, stage_id="01-prepare-env"))
    assert len(result.stages) == 1
    assert result.stages[0].stage_status == "failed"


def test_launcher_fallback_completes_when_artifact_valid_but_state_not_updated(monkeypatch, caplog, sample_file: Path, config):
    _stage_skill_tree(config.skills_root)
    report_dir = config.reports_root / ("aa" * 32)
    report_dir.mkdir(parents=True, exist_ok=True)
    pipeline_state.ensure_state(report_dir, "aa" * 32, str(sample_file))

    class _Registry:
        def get_tools_for_stage(self, _sid):
            return []

    class _Loop:
        def __init__(self, *args, **kwargs):
            self.last_messages = []

        def run(self, **kwargs):
            out = report_dir / "01-prepare-env.json"
            out.write_text("{}", encoding="utf-8")
            return "ok"

    monkeypatch.setattr("hyperagent.engine.launcher._sha256_of", lambda _p: "aa" * 32)
    monkeypatch.setattr("hyperagent.engine.launcher.ensure_idalib_mcp", lambda _cfg: None)
    monkeypatch.setattr("hyperagent.engine.launcher.stop_idalib_mcp", lambda _proc: None)
    monkeypatch.setattr("hyperagent.engine.launcher.build_full_registry", lambda _cfg, _scope: (_Registry(), []))
    monkeypatch.setattr("hyperagent.engine.launcher.create_provider", lambda *a, **k: _DummyProvider())
    monkeypatch.setattr("hyperagent.engine.launcher.AgentLoop", _Loop)

    result = asyncio.run(run_pipeline_with_config(sample_file, config, stage_id="01-prepare-env"))
    assert len(result.stages) == 1
    assert result.stages[0].stage_status == "completed"

    state = pipeline_state.load_state(report_dir)
    entry = state["stages"]["01-prepare-env"]
    assert entry["status"] == pipeline_state.STATUS_COMPLETED
    assert Path(entry["output_path"]) == report_dir / "01-prepare-env.json"
    assert "launcher fallback" in entry["recommend_reason"]
    assert "launcher auto-completed 01-prepare-env from valid artifact" in caplog.text
    assert "without updating STATE.json" in caplog.text


def test_launcher_fallback_does_not_complete_when_artifact_invalid(monkeypatch, sample_file: Path, config):
    _stage_skill_tree(config.skills_root)
    report_dir = config.reports_root / ("ab" * 32)
    report_dir.mkdir(parents=True, exist_ok=True)
    pipeline_state.ensure_state(report_dir, "ab" * 32, str(sample_file))

    class _Registry:
        def get_tools_for_stage(self, _sid):
            return []

    class _Loop:
        def __init__(self, *args, **kwargs):
            self.last_messages = []

        def run(self, **kwargs):
            out = report_dir / "01-prepare-env.json"
            out.write_text('not json', encoding="utf-8")
            return "ok"

    monkeypatch.setattr("hyperagent.engine.launcher._sha256_of", lambda _p: "ab" * 32)
    monkeypatch.setattr("hyperagent.engine.launcher.ensure_idalib_mcp", lambda _cfg: None)
    monkeypatch.setattr("hyperagent.engine.launcher.stop_idalib_mcp", lambda _proc: None)
    monkeypatch.setattr("hyperagent.engine.launcher.build_full_registry", lambda _cfg, _scope: (_Registry(), []))
    monkeypatch.setattr("hyperagent.engine.launcher.create_provider", lambda *a, **k: _DummyProvider())
    monkeypatch.setattr("hyperagent.engine.launcher.AgentLoop", _Loop)

    result = asyncio.run(run_pipeline_with_config(sample_file, config, stage_id="01-prepare-env"))
    assert len(result.stages) == 1
    assert result.stages[0].stage_status == "failed"


def test_launcher_fallback_completes_nonempty_report_stage(monkeypatch, sample_file: Path, config):
    _stage_skill_tree(config.skills_root)
    report_dir = config.reports_root / ("ac" * 32)
    report_dir.mkdir(parents=True, exist_ok=True)
    pipeline_state.ensure_state(report_dir, "ac" * 32, str(sample_file))

    class _Registry:
        def get_tools_for_stage(self, _sid):
            return []

    class _Loop:
        def __init__(self, *args, **kwargs):
            self.last_messages = []

        def run(self, **kwargs):
            out = report_dir / "08-report.md"
            out.write_text("# Report\n\nDone.", encoding="utf-8")
            return "ok"

    monkeypatch.setattr("hyperagent.engine.launcher._sha256_of", lambda _p: "ac" * 32)
    monkeypatch.setattr("hyperagent.engine.launcher.ensure_idalib_mcp", lambda _cfg: None)
    monkeypatch.setattr("hyperagent.engine.launcher.stop_idalib_mcp", lambda _proc: None)
    monkeypatch.setattr("hyperagent.engine.launcher.build_full_registry", lambda _cfg, _scope: (_Registry(), []))
    monkeypatch.setattr("hyperagent.engine.launcher.create_provider", lambda *a, **k: _DummyProvider())
    monkeypatch.setattr("hyperagent.engine.launcher.AgentLoop", _Loop)

    result = asyncio.run(run_pipeline_with_config(sample_file, config, stage_id="08-report"))
    assert len(result.stages) == 1
    assert result.stages[0].stage_status == "completed"


def test_artifact_validation_error_reports_schema_mismatch(tmp_path: Path, config):
    _stage_skill_tree(config.skills_root)
    output = tmp_path / "01-prepare-env.json"
    output.write_text('{"unexpected": true}', encoding="utf-8")
    schema_path = tmp_path / "schema.json"
    schema_path.write_text(
        '{"type":"object","required":["stage_id"],"properties":{"stage_id":{"type":"string"}}}',
        encoding="utf-8",
    )
    skill_doc = SimpleNamespace(schema_path=schema_path)

    error = _artifact_validation_error(STAGES[0], output, skill_doc)
    assert error is not None
    assert "does not match schema" in error


def test_artifact_validation_error_reports_invalid_json(tmp_path: Path, config):
    _stage_skill_tree(config.skills_root)
    output = tmp_path / "01-prepare-env.json"
    output.write_text('not json', encoding="utf-8")
    skill_doc = SimpleNamespace(schema_path=config.skills_root / "hyperagent-prepare-env" / "schema.json")

    error = _artifact_validation_error(STAGES[0], output, skill_doc)
    assert error is not None
    assert "not valid JSON" in error


def test_artifact_validation_error_reports_empty_report(tmp_path: Path, config):
    _stage_skill_tree(config.skills_root)
    output = tmp_path / "08-report.md"
    output.write_text("\n", encoding="utf-8")
    skill_doc = SimpleNamespace(schema_path=config.skills_root / "hyperagent-report" / "schema.json")

    error = _artifact_validation_error(next(stage for stage in STAGES if stage.stage_id == "08-report"), output, skill_doc)
    assert error == f"artifact at {output} is empty"


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
    monkeypatch.setattr("hyperagent.engine.launcher.ensure_idalib_mcp", lambda _cfg: None)
    monkeypatch.setattr("hyperagent.engine.launcher.stop_idalib_mcp", lambda _proc: None)
    monkeypatch.setattr("hyperagent.engine.launcher.build_full_registry", lambda _cfg, _scope: (_Registry(), []))
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
    monkeypatch.setattr("hyperagent.engine.launcher.ensure_idalib_mcp", lambda _cfg: None)
    monkeypatch.setattr("hyperagent.engine.launcher.stop_idalib_mcp", lambda _proc: None)
    monkeypatch.setattr("hyperagent.engine.launcher.build_full_registry", lambda _cfg, _scope: (_Registry(), []))
    monkeypatch.setattr("hyperagent.engine.launcher.create_provider", lambda *a, **k: _DummyProvider())
    monkeypatch.setattr("hyperagent.engine.launcher.AgentLoop", _Loop)

    result = asyncio.run(run_pipeline_with_config(sample_file, config, stage_id="05-dynamic"))
    assert len(result.stages) == 1
    assert result.stages[0].stage_status == "failed"
    assert revert_calls == [config.vmware]
