"""Tests for hyperagent.engine.launcher."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from hyperagent import pipeline_state
from hyperagent.engine import launcher
from hyperagent.skills import SkillDoc
from hyperagent.engine.launcher import (
    STAGES,
    _artifact_validation_error,
    _build_stage_prompt,
    _selected_stages,
    run_pipeline_with_config,
)
from hyperagent.config import default_skills_root
from hyperagent.tools.base import ToolDefinition
from hyperagent.providers.base import CompletionResult, LLMProvider, Message
from hyperagent.tools.registry import missing_x64dbg_required_tools
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
        runtime=SimpleNamespace(
            pipeline_profile="full",
            skip_dynamic=False,
            skip_intel=False,
            reuse_completed_stages=True,
            start_ida_mcp="auto",
            fast_max_stage_attempts=2,
        ),
        x64dbg_mcp=SimpleNamespace(url="http://127.0.0.1:1/mcp", timeout=2),
        ida_mcp=SimpleNamespace(url="http://127.0.0.1:1/mcp", timeout=2),
    )


def _stage_skill_tree(root: Path) -> None:
    (root / "_hyperagent-common" / "scripts").mkdir(parents=True, exist_ok=True)
    for stage in {stage.skill for stage in STAGES}:
        skill_dir = root / stage
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test\ndescription: test\n---\n\n# Role\n\nDo work.\n",
            encoding="utf-8",
        )
        (skill_dir / "schema.json").write_text('{"type":"object"}', encoding="utf-8")


def test_default_skills_root_points_at_repo_skill_dir():
    assert default_skills_root() == Path(__file__).resolve().parents[2] / "skill"


def test_selected_stages_supports_runtime_profiles():
    assert [stage.stage_id for stage in _selected_stages(None)] == [stage.stage_id for stage in STAGES]
    assert [stage.stage_id for stage in _selected_stages(None, profile="fast")] == [
        "01-prepare-env",
        "02-static-pass1",
        "03-unpack",
        "04-static-pass2",
        "07-deepdive",
        "08-report",
        "09-summary",
    ]
    assert [stage.stage_id for stage in _selected_stages(None, profile="static-only")] == [
        "01-prepare-env",
        "02-static-pass1",
        "03-unpack",
        "04-static-pass2",
        "07-deepdive",
        "08-report",
        "09-summary",
    ]


def test_selected_stages_applies_skip_flags():
    selected = _selected_stages(None, skip_dynamic=True, skip_intel=True)
    assert "05-dynamic" not in {stage.stage_id for stage in selected}
    assert "06-intel" not in {stage.stage_id for stage in selected}


def test_launcher_skips_idalib_mcp_when_profile_does_not_need_ida(monkeypatch, sample_file: Path, config):
    _stage_skill_tree(config.skills_root)
    config.runtime.pipeline_profile = "fast"
    config.runtime.start_ida_mcp = "auto"
    calls = {"ensure": 0, "stop": 0}

    class _Registry:
        def get_tools_for_stage(self, _sid):
            return []

    class _Loop:
        def __init__(self, *args, **kwargs):
            self.last_messages = []

        def run(self, **kwargs):
            out = config.reports_root / ("lazyida" * 8) / f"{kwargs['stage_id']}.json"
            if kwargs["stage_id"] == "08-report":
                out = out.with_suffix(".md")
                out.write_text("# Report", encoding="utf-8")
            else:
                out.write_text("{}", encoding="utf-8")
            pipeline_state.complete(out.parent, kwargs["stage_id"], str(out))
            return "ok"

    def fail_ensure(_cfg):
        calls["ensure"] += 1
        raise AssertionError("IDA MCP should not start for this selected stage set")

    monkeypatch.setattr("hyperagent.engine.launcher._sha256_of", lambda _p: "lazyida" * 8)
    monkeypatch.setattr("hyperagent.engine.launcher.ensure_idalib_mcp", fail_ensure)
    monkeypatch.setattr("hyperagent.engine.launcher.stop_idalib_mcp", lambda _proc: calls.__setitem__("stop", calls["stop"] + 1))
    monkeypatch.setattr("hyperagent.engine.launcher.build_full_registry", lambda _cfg, _scope: (_Registry(), []))
    monkeypatch.setattr("hyperagent.engine.launcher.create_provider", lambda *a, **k: _DummyProvider())
    monkeypatch.setattr("hyperagent.engine.launcher.AgentLoop", _Loop)

    result = asyncio.run(run_pipeline_with_config(sample_file, config, stage_id="07-deepdive"))

    assert len(result.stages) == 1
    assert result.stages[0].stage_status == "completed"
    assert calls == {"ensure": 0, "stop": 1}


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
            self.tools = {
                name: ToolDefinition(name=name, description="", parameters={}, handler=lambda **_: None, source="x64dbg")
                for name in missing_x64dbg_required_tools(None)
            }

        def get_tool(self, name):
            return self.tools.get(name)

        def get_all_tools(self):
            return list(self.tools.values())

        def get_tools_for_stage(self, stage_id):
            if stage_id == "05-dynamic":
                return list(self.tools.values())
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


def test_launcher_refreshes_x64dbg_tools_on_each_dynamic_attempt(monkeypatch, sample_file: Path, config):
    _stage_skill_tree(config.skills_root)
    report_dir = config.reports_root / ("retryx64" * 8)
    report_dir.mkdir(parents=True, exist_ok=True)
    pipeline_state.ensure_state(report_dir, "retryx64" * 8, str(sample_file))

    class _Registry:
        def __init__(self):
            self.refresh_calls = []
            self.debug_tools_available = False
            self.tools = {
                name: ToolDefinition(name=name, description="", parameters={}, handler=lambda **_: None, source="x64dbg")
                for name in missing_x64dbg_required_tools(None)
            }

        def get_tool(self, name):
            if not self.debug_tools_available:
                return None
            return self.tools.get(name)

        def get_all_tools(self):
            if not self.debug_tools_available:
                return []
            return list(self.tools.values())

        def get_tools_for_stage(self, stage_id):
            if stage_id == "05-dynamic" and self.debug_tools_available:
                return list(self.tools.values())
            return []

    fake_registry = _Registry()
    seen_tools = []

    def fake_refresh(registry, clients, endpoint, stage_id, current_client=None):
        registry.refresh_calls.append(stage_id)
        if len(registry.refresh_calls) == 2:
            registry.debug_tools_available = True
        return current_client

    monkeypatch.setattr("hyperagent.engine.launcher._sha256_of", lambda _p: "retryx64" * 8)
    monkeypatch.setattr("hyperagent.engine.launcher.ensure_idalib_mcp", lambda _cfg: None)
    monkeypatch.setattr("hyperagent.engine.launcher.stop_idalib_mcp", lambda _proc: None)
    monkeypatch.setattr("hyperagent.engine.launcher.build_full_registry", lambda _cfg, _scope: (fake_registry, [object(), object()]))
    monkeypatch.setattr("hyperagent.engine.launcher.refresh_x64dbg_tools", fake_refresh)
    monkeypatch.setattr("hyperagent.engine.launcher.create_provider", lambda *a, **k: _DummyProvider())
    monkeypatch.setattr(vmware_tools, "vm_auto_revert_after_dynamic", lambda cfg: None)
    recovery_calls = []
    monkeypatch.setattr(
        vmware_tools,
        "vm_auto_recover_dynamic_env",
        lambda cfg, sample_path, scope: recovery_calls.append(1) or SimpleNamespace(is_error=False, content="stub"),
    )

    class _Loop:
        def __init__(self, *args, **kwargs):
            self.last_messages = []

        def run(self, **kwargs):
            seen_tools.append(kwargs["stage_tools"])
            out = report_dir / "05-dynamic.json"
            out.write_text("{}", encoding="utf-8")
            pipeline_state.complete(report_dir, "05-dynamic", str(out))
            return "ok"

    monkeypatch.setattr("hyperagent.engine.launcher.AgentLoop", _Loop)

    result = asyncio.run(run_pipeline_with_config(sample_file, config, stage_id="05-dynamic"))
    assert len(result.stages) == 1
    assert result.stages[0].stage_status == "completed"
    assert fake_registry.refresh_calls == ["05-dynamic", "05-dynamic"]
    assert len(recovery_calls) == 1
    assert len(seen_tools) == 1
    assert set(seen_tools[0]) == set(missing_x64dbg_required_tools(None))


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


def test_launcher_passes_intel_only_vt_tools(monkeypatch, sample_file: Path, config):
    _stage_skill_tree(config.skills_root)
    captured: dict[str, list[str]] = {}

    class _Registry:
        def get_tools_for_stage(self, stage_id):
            names = ["write_file"]
            if stage_id == "06-intel":
                names.extend(["fetch_vt_report", "normalize_vt_report"])
            if stage_id == "08-report":
                names.append("build_report_context")
            return [
                ToolDefinition(name=name, description="", parameters={}, handler=lambda **_: None)
                for name in names
            ]

    class _Loop:
        def __init__(self, *args, **kwargs):
            self.last_messages = []

        def run(self, **kwargs):
            stage_id = kwargs["stage_id"]
            captured[stage_id] = kwargs["stage_tools"]
            out = config.reports_root / ("launchtools" * 6 + "1234") / f"{stage_id}.json"
            if stage_id == "08-report":
                out = out.with_suffix(".md")
            out.parent.mkdir(parents=True, exist_ok=True)
            if stage_id == "08-report":
                out.write_text("# Report\n\nDone.", encoding="utf-8")
            else:
                out.write_text("{}", encoding="utf-8")
            pipeline_state.complete(out.parent, stage_id, str(out))
            return "ok"

    monkeypatch.setattr("hyperagent.engine.launcher._sha256_of", lambda _p: "launchtools" * 6 + "1234")
    monkeypatch.setattr("hyperagent.engine.launcher.ensure_idalib_mcp", lambda _cfg: None)
    monkeypatch.setattr("hyperagent.engine.launcher.stop_idalib_mcp", lambda _proc: None)
    monkeypatch.setattr("hyperagent.engine.launcher.build_full_registry", lambda _cfg, _scope: (_Registry(), []))
    monkeypatch.setattr("hyperagent.engine.launcher.create_provider", lambda *a, **k: _DummyProvider())
    monkeypatch.setattr("hyperagent.engine.launcher.AgentLoop", _Loop)

    intel_result = asyncio.run(run_pipeline_with_config(sample_file, config, stage_id="06-intel"))
    report_result = asyncio.run(run_pipeline_with_config(sample_file, config, stage_id="08-report"))

    assert intel_result.stages[0].stage_status == "completed"
    assert report_result.stages[0].stage_status == "completed"
    assert "fetch_vt_report" in captured["06-intel"]
    assert "normalize_vt_report" in captured["06-intel"]
    assert "build_report_context" in captured["08-report"]
    assert "fetch_vt_report" not in captured["08-report"]
    assert "normalize_vt_report" not in captured["08-report"]


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


def test_launcher_fallback_completes_valid_artifact_after_checkpoint(monkeypatch, caplog, sample_file: Path, config):
    _stage_skill_tree(config.skills_root)
    report_dir = config.reports_root / ("ca" * 32)
    report_dir.mkdir(parents=True, exist_ok=True)
    pipeline_state.ensure_state(report_dir, "ca" * 32, str(sample_file))

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
            return "ok"

    monkeypatch.setattr("hyperagent.engine.launcher._sha256_of", lambda _p: "ca" * 32)
    monkeypatch.setattr("hyperagent.engine.launcher.ensure_idalib_mcp", lambda _cfg: None)
    monkeypatch.setattr("hyperagent.engine.launcher.stop_idalib_mcp", lambda _proc: None)
    monkeypatch.setattr("hyperagent.engine.launcher.build_full_registry", lambda _cfg, _scope: (_Registry(), []))
    monkeypatch.setattr("hyperagent.engine.launcher.create_provider", lambda *a, **k: _DummyProvider())
    monkeypatch.setattr("hyperagent.engine.launcher.AgentLoop", _Loop)

    result = asyncio.run(run_pipeline_with_config(sample_file, config, stage_id="01-prepare-env"))
    assert calls["count"] == 2
    assert len(result.stages) == 1
    assert result.stages[0].stage_status == "completed"

    state = pipeline_state.load_state(report_dir)
    entry = state["stages"]["01-prepare-env"]
    assert entry["status"] == pipeline_state.STATUS_COMPLETED
    assert Path(entry["output_path"]) == report_dir / "01-prepare-env.json"
    assert "launcher fallback" in state["recommend_next_stage"]["reason"]
    assert "after a resumed attempt exited without updating STATE.json" in caplog.text


def test_launcher_retries_when_stage_ends_without_state_update(monkeypatch, caplog, sample_file: Path, config):
    _stage_skill_tree(config.skills_root)
    report_dir = config.reports_root / ("d" * 64)
    report_dir.mkdir(parents=True, exist_ok=True)
    pipeline_state.ensure_state(report_dir, "d" * 64, str(sample_file))

    class _Registry:
        def get_tools_for_stage(self, _sid):
            return []

    calls = {"count": 0}

    class _Loop:
        def __init__(self, *args, **kwargs):
            self.last_messages = []

        def run(self, **kwargs):
            calls["count"] += 1
            if calls["count"] == 2:
                out = report_dir / "01-prepare-env.json"
                out.write_text("{}", encoding="utf-8")
            return "ok"

    monkeypatch.setattr("hyperagent.engine.launcher._sha256_of", lambda _p: "d" * 64)
    monkeypatch.setattr("hyperagent.engine.launcher.ensure_idalib_mcp", lambda _cfg: None)
    monkeypatch.setattr("hyperagent.engine.launcher.stop_idalib_mcp", lambda _proc: None)
    monkeypatch.setattr("hyperagent.engine.launcher.build_full_registry", lambda _cfg, _scope: (_Registry(), []))
    monkeypatch.setattr("hyperagent.engine.launcher.create_provider", lambda *a, **k: _DummyProvider())
    monkeypatch.setattr("hyperagent.engine.launcher.AgentLoop", _Loop)

    result = asyncio.run(run_pipeline_with_config(sample_file, config, stage_id="01-prepare-env"))
    assert calls["count"] == 2
    assert len(result.stages) == 1
    assert result.stages[0].stage_status == "completed"

    state = pipeline_state.load_state(report_dir)
    entry = state["stages"]["01-prepare-env"]
    assert entry["status"] == pipeline_state.STATUS_COMPLETED
    assert Path(entry["output_path"]) == report_dir / "01-prepare-env.json"
    assert Path(entry["progress_path"]).name == "01-prepare-env.progress.md"
    assert "ended without artifact/state update; checkpointed" in caplog.text


def test_launcher_fails_after_retries_when_stage_never_updates_state(monkeypatch, sample_file: Path, config):
    _stage_skill_tree(config.skills_root)
    report_dir = config.reports_root / ("de" * 32)
    report_dir.mkdir(parents=True, exist_ok=True)
    pipeline_state.ensure_state(report_dir, "de" * 32, str(sample_file))

    class _Registry:
        def get_tools_for_stage(self, _sid):
            return []

    class _Loop:
        def __init__(self, *args, **kwargs):
            self.last_messages = []

        def run(self, **kwargs):
            return "ok"

    monkeypatch.setattr("hyperagent.engine.launcher._sha256_of", lambda _p: "de" * 32)
    monkeypatch.setattr("hyperagent.engine.launcher.ensure_idalib_mcp", lambda _cfg: None)
    monkeypatch.setattr("hyperagent.engine.launcher.stop_idalib_mcp", lambda _proc: None)
    monkeypatch.setattr("hyperagent.engine.launcher.build_full_registry", lambda _cfg, _scope: (_Registry(), []))
    monkeypatch.setattr("hyperagent.engine.launcher.create_provider", lambda *a, **k: _DummyProvider())
    monkeypatch.setattr("hyperagent.engine.launcher.AgentLoop", _Loop)

    result = asyncio.run(run_pipeline_with_config(sample_file, config, stage_id="01-prepare-env"))
    assert len(result.stages) == 1
    assert result.stages[0].stage_status == "failed"


def test_launcher_force_finalizes_after_exhausting_attempts(monkeypatch, caplog, sample_file: Path, config):
    _stage_skill_tree(config.skills_root)
    report_dir = config.reports_root / ("f" * 64)
    report_dir.mkdir(parents=True, exist_ok=True)
    pipeline_state.ensure_state(report_dir, "f" * 64, str(sample_file))

    class _Registry:
        def get_tools_for_stage(self, _sid):
            return []

    calls = {"count": 0}

    class _Loop:
        def __init__(self, *args, **kwargs):
            self.last_messages = []

        def run(self, **kwargs):
            calls["count"] += 1
            if calls["count"] <= config.max_stage_attempts:
                # Every regular attempt checkpoints but never finishes, same
                # as a stage that keeps overflowing context or hitting a
                # flaky tool -- burning the whole attempt budget with nothing
                # to show for it.
                progress = report_dir / "_state" / "01-prepare-env.progress.md"
                progress.parent.mkdir(parents=True, exist_ok=True)
                progress.write_text(f"attempt {calls['count']} notes", encoding="utf-8")
                pipeline_state.checkpoint(report_dir, "01-prepare-env", str(progress), "test")
            else:
                # The forced finalize round succeeds where the real attempts
                # didn't: it just writes down what's already known.
                out = report_dir / "01-prepare-env.json"
                out.write_text("{}", encoding="utf-8")
            return "ok"

    monkeypatch.setattr("hyperagent.engine.launcher._sha256_of", lambda _p: "f" * 64)
    monkeypatch.setattr("hyperagent.engine.launcher.ensure_idalib_mcp", lambda _cfg: None)
    monkeypatch.setattr("hyperagent.engine.launcher.stop_idalib_mcp", lambda _proc: None)
    monkeypatch.setattr("hyperagent.engine.launcher.build_full_registry", lambda _cfg, _scope: (_Registry(), []))
    monkeypatch.setattr("hyperagent.engine.launcher.create_provider", lambda *a, **k: _DummyProvider())
    monkeypatch.setattr("hyperagent.engine.launcher.AgentLoop", _Loop)

    result = asyncio.run(run_pipeline_with_config(sample_file, config, stage_id="01-prepare-env"))

    assert calls["count"] == config.max_stage_attempts + 1
    assert len(result.stages) == 1
    assert result.stages[0].stage_status == "completed"

    state = pipeline_state.load_state(report_dir)
    entry = state["stages"]["01-prepare-env"]
    assert entry["status"] == pipeline_state.STATUS_COMPLETED
    assert Path(entry["output_path"]) == report_dir / "01-prepare-env.json"
    assert "force-finalized" in caplog.text


def test_checkpoint_summary_or_compact_uses_compaction_when_possible(config):
    from types import SimpleNamespace as _SN

    from hyperagent.engine.launcher import _checkpoint_summary_or_compact

    class _SummarizingProvider(_DummyProvider):
        def complete(self, messages, *, tools=None, system_prompt="", max_tokens=None, temperature=None):
            return CompletionResult(
                content="Found OEP at 0x401000; breakpoint on VirtualAlloc worked.",
                tool_calls=[],
                stop_reason="end_turn",
            )

    loop = _SN(
        last_messages=[
            Message(role="user", content="Analyze sample: " + "x" * 2000),
            Message(role="assistant", content="Stepping through the unpacking stub. " * 50),
        ]
    )
    summary = _checkpoint_summary_or_compact(loop, _SummarizingProvider(), "05-dynamic", config)
    assert "Found OEP at 0x401000" in summary
    assert "## Prior progress (compacted)" in summary


def test_checkpoint_summary_or_compact_falls_back_when_compaction_not_possible(config):
    from types import SimpleNamespace as _SN

    from hyperagent.engine.launcher import _checkpoint_summary_or_compact

    # A single message is not enough conversation history to compact, so
    # compact_messages raises and this should fall back to the raw preview.
    loop = _SN(last_messages=[Message(role="user", content="only one message")])
    summary = _checkpoint_summary_or_compact(loop, _DummyProvider(), "05-dynamic", config)
    assert "## Recent conversation" in summary
    assert "## Prior progress (compacted)" not in summary


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
    assert "launcher fallback" in state["recommend_next_stage"]["reason"]
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


def test_launcher_updates_run_console_for_stage_attempt(monkeypatch, sample_file: Path, config):
    _stage_skill_tree(config.skills_root)
    config.provider.console_mode = "minimal"
    report_dir = config.reports_root / ("console" * 8)
    report_dir.mkdir(parents=True, exist_ok=True)
    pipeline_state.ensure_state(report_dir, "console" * 8, str(sample_file))

    class _Registry:
        def get_tools_for_stage(self, _sid):
            return []

    class _Console:
        def __init__(self):
            self.started = False
            self.finished = False
            self.transitions = []

        def start(self):
            self.started = True

        def finish(self):
            self.finished = True

        def stage_transition(self, **kwargs):
            self.transitions.append(kwargs)

    console = _Console()

    class _Loop:
        def __init__(self, *args, **kwargs):
            self.last_messages = []
            assert kwargs["run_console"] is console
            assert kwargs["console_mode"] == "minimal"

        def run(self, **kwargs):
            out = report_dir / "01-prepare-env.json"
            out.write_text("{}", encoding="utf-8")
            pipeline_state.complete(report_dir, "01-prepare-env", str(out))
            return "ok"

    def fake_create_provider(*args, **kwargs):
        assert kwargs["run_console"] is console
        return _DummyProvider()

    monkeypatch.setattr("hyperagent.engine.launcher._sha256_of", lambda _p: "console" * 8)
    monkeypatch.setattr("hyperagent.engine.launcher.ensure_idalib_mcp", lambda _cfg: None)
    monkeypatch.setattr("hyperagent.engine.launcher.stop_idalib_mcp", lambda _proc: None)
    monkeypatch.setattr("hyperagent.engine.launcher.build_full_registry", lambda _cfg, _scope: (_Registry(), []))
    monkeypatch.setattr("hyperagent.engine.launcher.create_provider", fake_create_provider)
    monkeypatch.setattr("hyperagent.engine.launcher.AgentLoop", _Loop)

    result = asyncio.run(run_pipeline_with_config(sample_file, config, stage_id="01-prepare-env", run_console=console))

    assert len(result.stages) == 1
    assert console.started is True
    assert console.finished is True
    assert console.transitions == [
        {
            "index": 1,
            "total": 1,
            "stage_id": "01-prepare-env",
            "stage_name": "hyperagent-prepare-env",
            "attempt": 1,
            "guarded": False,
        }
    ]



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
    monkeypatch.setattr("hyperagent.engine.launcher.missing_x64dbg_required_tools", lambda _registry: [])
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
    recovery_calls: list[object] = []
    monkeypatch.setattr(vmware_tools, "vm_auto_revert_after_dynamic", lambda cfg: revert_calls.append(cfg))
    monkeypatch.setattr(
        vmware_tools,
        "vm_auto_recover_dynamic_env",
        lambda cfg, sample_path, scope: recovery_calls.append(1) or SimpleNamespace(is_error=True, content="stub: still missing"),
    )
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
    # Capped at _MAX_VM_AUTO_RECOVERY_ATTEMPTS even though every attempt still
    # reports x64dbg missing -- later attempts fall through to the plain
    # checkpoint-and-retry path instead of re-reverting the VM every time.
    assert len(recovery_calls) == launcher._MAX_VM_AUTO_RECOVERY_ATTEMPTS


# -- ablation: telling downstream stages what was withheld --------------------


class _Ablation:
    def __init__(self, name, skip_stages):
        self.name = name
        self.skip_stages = skip_stages


def _stage(stage_id):
    return next(s for s in launcher.STAGES if s.stage_id == stage_id)


def test_ablated_note_names_only_upstream_skips():
    """A2 disables 05-dynamic, so 07-deepdive must be told and 03-unpack must not."""
    cfg = _Ablation("A2_no_dynamic", ["05-dynamic"])

    downstream = "\n".join(launcher._ablated_upstream_note(_stage("07-deepdive"), cfg))
    upstream = launcher._ablated_upstream_note(_stage("03-unpack"), cfg)

    assert "05-dynamic" in downstream
    assert "A2_no_dynamic" in downstream
    assert upstream == []


def test_ablated_note_is_empty_without_skips():
    """A4/A5/A6 change no stage set, so nothing is announced."""
    cfg = _Ablation("A4_no_cache", [])
    assert launcher._ablated_upstream_note(_stage("07-deepdive"), cfg) == []


def test_ablated_note_frames_absence_as_run_profile_not_error():
    """The wording decides whether the ablation measures information or plumbing.

    Deepdive's claim policy correctly refuses to assert behaviour it has no
    evidence for. If a withheld artifact reads as a blocker, every A1/A2 run
    collapses to an inconclusive verdict, which scores as benign — a recall drop
    that reflects the policy rather than the contribution of the missing stage.
    """
    note = "\n".join(
        launcher._ablated_upstream_note(
            _stage("07-deepdive"), _Ablation("A1_no_static", ["02-static-pass1", "04-static-pass2"])
        )
    ).lower()

    assert "not as an error" in note and "not as a blocker" in note
    assert "do not invent replacement findings" in note
    assert "limitations" in note


def test_build_stage_prompt_carries_the_ablation_note(tmp_path):
    prompt = launcher._build_stage_prompt(
        tmp_path / "sample.exe",
        tmp_path / "reports" / ("a" * 64),
        _stage("07-deepdive"),
        tmp_path / "STATE.json",
        SkillDoc(name="hyperagent-deepdive", description="d", instructions="x"),
        tmp_path / "skills",
        _Ablation("A2_no_dynamic", ["05-dynamic"]),
    )

    assert "05-dynamic" in prompt
    assert "Run profile: A2_no_dynamic" in prompt
