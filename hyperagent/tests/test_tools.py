"""Unit tests for the tool layer: analysis wrappers, stage resolution, MCP degradation."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from hyperagent.config import HyperAgentConfig, MCPEndpoint, VMwareConfig
from hyperagent.tools.analysis_tools import _get_scripts_dir, create_analysis_tools
from hyperagent.tools.base import ToolDefinition, ToolResult
from hyperagent.tools.filesystem_tools import create_filesystem_tools
from hyperagent.tools.ida_tools import create_ida_tools, ida_health_check_tool
from hyperagent.tools.path_scope import PathScope
from hyperagent.tools.registry import STAGE_TOOLS, ToolRegistry, UnauthorizedToolError, build_full_registry, common_scripts_dir, missing_x64dbg_required_tools, refresh_x64dbg_tools
from hyperagent.tools.vmware_tools import create_vmware_tools
from hyperagent.tools.x64dbg_tools import create_x64dbg_tools, x64dbg_health_check_tool

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures" / "analysis_tools"
REAL_SCRIPTS = REPO_ROOT / "skill" / "_hyperagent-common" / "scripts"

requires_scripts = pytest.mark.skipif(
    not REAL_SCRIPTS.is_dir(),
    reason=f"helper scripts not present at {REAL_SCRIPTS}",
)

# Port 1 is reserved and refuses connections instantly — no server needed.
UNREACHABLE = MCPEndpoint(url="http://127.0.0.1:1/mcp", timeout=2)


class _Completed:
    def __init__(self, *, returncode: int = 0, stdout: str = "OK", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _FakeMCPClient:
    def __init__(self, *args, **kwargs):
        pass

    def close(self):
        return None


def _scope(root: Path) -> PathScope:
    return PathScope(read_roots=(root,), write_roots=(root,))


@pytest.fixture()
def scoped_root(tmp_path: Path) -> Path:
    return tmp_path / "scoped"


@pytest.fixture()
def scope(scoped_root: Path) -> PathScope:
    scoped_root.mkdir(parents=True, exist_ok=True)
    return _scope(scoped_root)


@pytest.fixture()
def scripts_dir(scope: PathScope) -> Path:
    scripts = scope.read_roots[0] / "scripts"
    scripts.mkdir()
    for name in (
        "fetch_vt_file_report.py",
        "normalize_vt_to_intel.py",
        "validate_output.py",
    ):
        (scripts / name).write_text("print('ok')\n", encoding="utf-8")
    return scripts


@pytest.fixture()
def outside_path(tmp_path: Path) -> Path:
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    return outside


@pytest.fixture()
def inside_file(scope: PathScope) -> Path:
    path = scope.read_roots[0] / "inside.txt"
    path.write_text("inside", encoding="utf-8")
    return path


@pytest.fixture()
def inside_json(scope: PathScope) -> Path:
    path = scope.read_roots[0] / "inside.json"
    path.write_text("{}", encoding="utf-8")
    return path


@pytest.fixture()
def sample_output(scope: PathScope) -> Path:
    return scope.write_roots[0] / "out.json"


@pytest.fixture()
def filesystem_tools(scope: PathScope):
    return create_filesystem_tools(scope)


@pytest.fixture()
def analysis_tools(scope: PathScope, scripts_dir: Path):
    return create_analysis_tools(scripts_dir, scope)


@pytest.fixture()
def vm_tools(scope: PathScope):
    return create_vmware_tools(VMwareConfig(), scope)


@pytest.fixture()
def fake_subprocess(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, capture_output, text, timeout, cwd=None, shell=False):
        calls.append(cmd)
        return _Completed(stdout="ok")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def _tool_from(tools, name: str):
    for tool in tools:
        if tool.name == name:
            return tool
    raise AssertionError(f"tool {name} not found")



def _analysis_tool(name: str):
    for t in create_analysis_tools(REAL_SCRIPTS, _scope(REPO_ROOT)):
        if t.name == name:
            return t
    raise AssertionError(f"tool {name} not built")


class TestFilesystemScopeEnforcement:
    def test_read_file_rejects_out_of_scope_path(self, filesystem_tools, outside_path):
        res = _tool_from(filesystem_tools, "read_file").handler(path=str(outside_path))
        assert res.is_error
        assert "allowed analysis scope" in res.content

    def test_write_file_rejects_out_of_scope_path(self, filesystem_tools, outside_path):
        res = _tool_from(filesystem_tools, "write_file").handler(path=str(outside_path), content="x")
        assert res.is_error
        assert "allowed analysis scope" in res.content

    def test_read_file_allows_in_scope_path(self, filesystem_tools, inside_file):
        res = _tool_from(filesystem_tools, "read_file").handler(path=str(inside_file))
        assert not res.is_error
        assert res.content == "inside"


class TestAnalysisToolScopeEnforcement:
    def test_validate_json_output_rejects_out_of_scope_path(
        self,
        analysis_tools,
        outside_path,
        inside_json,
        fake_subprocess,
    ):
        res = _tool_from(analysis_tools, "validate_json_output").handler(
            schema_path=str(inside_json),
            json_path=str(outside_path),
        )
        assert res.is_error
        assert "allowed analysis scope" in res.content
        assert fake_subprocess == []

    def test_fetch_vt_report_rejects_out_of_scope_output(self, analysis_tools, outside_path, fake_subprocess):
        res = _tool_from(analysis_tools, "fetch_vt_report").handler(
            file_id="a" * 64,
            output_path=str(outside_path),
        )
        assert res.is_error
        assert "allowed analysis scope" in res.content
        assert fake_subprocess == []

    def test_upx_unpack_rejects_out_of_scope_input(self, analysis_tools, outside_path, sample_output, fake_subprocess):
        res = _tool_from(analysis_tools, "upx_unpack").handler(
            input_path=str(outside_path),
            output_path=str(sample_output),
        )
        assert res.is_error
        assert "allowed analysis scope" in res.content
        assert fake_subprocess == []

    def test_validate_json_output_allows_in_scope_paths(self, analysis_tools, inside_json, fake_subprocess):
        res = _tool_from(analysis_tools, "validate_json_output").handler(
            schema_path=str(inside_json),
            json_path=str(inside_json),
        )
        assert not res.is_error
        assert fake_subprocess


class TestScopedMCPWrapping:
    def test_create_ida_tools_rejects_out_of_scope_file_path(self, monkeypatch, scope, outside_path):
        class _ScopedFakeMCPClient(_FakeMCPClient):
            def get_tool_definitions(self, handler_factory=None):
                handler = handler_factory(self, "open_file")
                return [
                    ToolDefinition(
                        name="open_file",
                        description="open file",
                        parameters={},
                        handler=handler,
                    )
                ]

            def call_tool(self, name, arguments):
                raise AssertionError("call_tool should not be reached")

        monkeypatch.setattr("hyperagent.tools.ida_tools.MCPClient", _ScopedFakeMCPClient)
        endpoint = MCPEndpoint(url="http://127.0.0.1:1/mcp", timeout=2)
        client, ida_tools = create_ida_tools(endpoint, scope=scope)
        try:
            res = ida_tools[0].handler(file_path=str(outside_path))
            assert res.is_error
            assert "allowed analysis scope" in res.content
        finally:
            client.close()


class TestAnalysisToolGuards:
    """Argument guards must reject before any subprocess is spawned."""

    def test_upx_unpack_missing_args(self):
        res = _analysis_tool("upx_unpack").handler(input_path="", output_path="")
        assert res.is_error

    def test_fetch_vt_report_missing_file_id(self):
        res = _analysis_tool("fetch_vt_report").handler(file_id="", output_path="/tmp/x.json")
        assert res.is_error

    def test_normalize_vt_report_requires_one_source(self):
        res = _analysis_tool("normalize_vt_report").handler(output_path="/tmp/x.json")
        assert res.is_error
        assert "at least one" in res.content.lower()

    def test_validate_json_output_missing_args(self):
        res = _analysis_tool("validate_json_output").handler(schema_path="", json_path="")
        assert res.is_error

    def test_build_report_context_requires_report_dir(self):
        res = _analysis_tool("build_report_context").handler(report_dir="")
        assert res.is_error
        assert "report_dir required" in res.content


@requires_scripts
class TestAnalysisToolSubprocess:
    """Real subprocess calls against the real helper scripts — all offline."""

    def test_validate_json_output_valid(self):
        res = _analysis_tool("validate_json_output").handler(
            schema_path=str(FIXTURES / "schema.json"),
            json_path=str(FIXTURES / "valid.json"),
        )
        assert not res.is_error
        assert "VALID" in res.content

    def test_validate_json_output_invalid(self):
        res = _analysis_tool("validate_json_output").handler(
            schema_path=str(FIXTURES / "schema.json"),
            json_path=str(FIXTURES / "invalid.json"),
        )
        assert res.is_error

    def test_normalize_vt_report_writes_json(self, tmp_path):
        out = REAL_SCRIPTS / "intel.json"
        try:
            res = _analysis_tool("normalize_vt_report").handler(
                file_info_path=str(FIXTURES / "file_info.json"),
                output_path=str(out),
            )
            assert not res.is_error, res.content
            payload = json.loads(out.read_text(encoding="utf-8"))
            assert payload["stage"] == "intel"
            assert payload["sample_sha256"] == "a" * 64
        finally:
            out.unlink(missing_ok=True)

    def test_build_report_context_writes_compact_markdown(self, tmp_path):
        report_dir = tmp_path / "reports" / ("a" * 64)
        report_dir.mkdir(parents=True, exist_ok=True)
        report_tool = _tool_from(create_analysis_tools(REAL_SCRIPTS, _scope(tmp_path)), "build_report_context")

        (report_dir / "01-prepare-env.json").write_text(
            json.dumps({
                "schema_version": "1.0",
                "stage": "prepare-env",
                "sample": {
                    "file_name": "sample.exe",
                    "absolute_path": "C:/samples/sample.exe",
                    "sha256": "a" * 64,
                },
                "workspace": {
                    "report_directory": str(report_dir),
                    "artifact_directory": str(report_dir / "artifacts"),
                },
                "static_environment": {"status": "ready", "components": []},
                "dynamic_environment": {"status": "ready", "components": []},
                "readiness": {"static": "ready", "dynamic": "ready", "overall": "ready"},
                "blockers": [],
                "provenance": [{"type": "file", "location": "STATE.json"}],
            }, indent=2),
            encoding="utf-8",
        )
        (report_dir / "02-static-pass1.json").write_text(
            json.dumps({
                "schema_version": "1.0",
                "stage": "static-pass1",
                "sample": {
                    "original_sha256": "a" * 64,
                    "target_path": "C:/samples/sample.exe",
                    "target_sha256": "a" * 64,
                },
                "status": "completed",
                "summary": "Packed sample with downloader strings.",
                "findings": [{
                    "id": "sp1.loader",
                    "title": "Loader logic",
                    "category": "loader",
                    "status": "confirmed",
                    "confidence": 0.8,
                    "description": "Resolves APIs dynamically.",
                    "reasoning": "Static strings and imports support this.",
                    "sources": [{"stage": "02-static-pass1", "artifact": "02-static-pass1.json", "location": "findings[0]"}],
                    "evidence": [],
                    "limitations": [],
                }],
                "artifacts": [],
                "investigation_targets": [],
                "limitations": [],
                "upstream_inputs": ["01-prepare-env.json"],
                "binary_profile": {
                    "format": "PE32",
                    "architecture": "x86",
                    "entry_point": "0x401000",
                    "image_base": "0x400000",
                    "packer": "UPX",
                    "packed_confidence": 0.91,
                },
                "unpack_decision": {
                    "required": True,
                    "confidence": 0.91,
                    "reasons": ["UPX signatures present"],
                    "strategy": "in_place_dynamic",
                    "breakpoint_plan": [],
                },
            }, indent=2),
            encoding="utf-8",
        )
        (report_dir / "05-dynamic.json").write_text(
            json.dumps({
                "schema_version": "1.0",
                "stage": "dynamic",
                "sample": {
                    "original_sha256": "a" * 64,
                    "target_path": "C:/samples/sample.exe",
                    "target_sha256": "a" * 64,
                },
                "status": "completed",
                "summary": "Observed outbound HTTP beaconing.",
                "findings": [{
                    "id": "dyn.http",
                    "title": "HTTP beacon",
                    "category": "network",
                    "status": "observed",
                    "confidence": 0.9,
                    "description": "Connected to update.example.invalid.",
                    "reasoning": "Traffic observed in guest.",
                    "sources": [{"stage": "05-dynamic", "artifact": "05-dynamic.json", "location": "findings[0]"}],
                    "evidence": [],
                    "limitations": [],
                }],
                "artifacts": [{
                    "id": "art.memdump",
                    "path": "C:/reports/a/memdump.bin",
                    "sha256": "b" * 64,
                    "type": "memory_dump",
                    "validation_status": "validated",
                    "context": "Captured after network activity.",
                }],
                "investigation_targets": [],
                "limitations": ["Short runtime window."],
                "upstream_inputs": ["02-static-pass1.json"],
                "runtime": {
                    "executed": True,
                    "guest_only": True,
                    "aslr_base": "0x500000",
                    "stop_reason": "network observed",
                    "observation_window": "90s",
                },
                "behaviors": [
                    {
                        "id": "beh.net",
                        "type": "network",
                        "status": "observed",
                        "confidence": 0.9,
                        "description": "Outbound HTTP to update.example.invalid.",
                        "evidence_ids": [],
                    },
                    {
                        "id": "beh.persistence",
                        "type": "persistence",
                        "status": "not_observed",
                        "confidence": 0.7,
                        "description": "No autorun write seen.",
                        "evidence_ids": [],
                    }
                ],
                "iocs": {
                    "network": ["update.example.invalid"],
                    "host": [],
                    "persistence": [],
                },
            }, indent=2),
            encoding="utf-8",
        )
        (report_dir / "07-deepdive.json").write_text(
            json.dumps({
                "schema_version": "1.0",
                "stage": "deepdive",
                "sample_sha256": "a" * 64,
                "status": "completed",
                "executive_assessment": {
                    "verdict": "malicious",
                    "confidence": 0.88,
                    "technical_summary": "Downloader behavior confirmed from dynamic evidence.",
                    "highest_value_resolution": "Network activity confirmed the downloader hypothesis.",
                    "remaining_decision_point": "Family attribution remains unconfirmed.",
                },
                "finding_reviews": [
                    {
                        "id": "dd.confirmed.network",
                        "title": "Downloader network behavior",
                        "original_claims": [{
                            "stage": "05-dynamic",
                            "finding_id": "dyn.http",
                            "claim": "Contacts update.example.invalid",
                            "confidence": 0.9,
                        }],
                        "final_status": "confirmed",
                        "final_confidence": 0.9,
                        "evidence_chain": [],
                        "reasoning": "Dynamic evidence is direct.",
                        "confidence_change": {
                            "direction": "unchanged",
                            "previous_max": 0.9,
                            "new": 0.9,
                            "justification": "Direct runtime evidence.",
                        },
                        "report_disposition": "include_confirmed",
                        "limitations": [],
                    },
                    {
                        "id": "dd.caveat.family",
                        "title": "Family attribution",
                        "original_claims": [{
                            "stage": "06-intel",
                            "finding_id": None,
                            "claim": "Public labels suggest ExampleLoader.",
                            "confidence": 0.4,
                        }],
                        "final_status": "partial",
                        "final_confidence": 0.4,
                        "evidence_chain": [],
                        "reasoning": "Public labels alone are insufficient.",
                        "confidence_change": {
                            "direction": "decreased",
                            "previous_max": 0.6,
                            "new": 0.4,
                            "justification": "No local family proof.",
                        },
                        "report_disposition": "include_with_caveat",
                        "limitations": ["No family-unique code path recovered."],
                    }
                ],
                "contradictions": [],
                "hypotheses": [],
                "root_cause_analysis": [],
                "investigation_targets": [{
                    "id": "next.family",
                    "priority": 2,
                    "target": "family attribution",
                    "reason": "Public labels conflict and remain weak.",
                    "recommended_action": "Correlate unpacked code paths with known clusters.",
                    "success_criteria": "Family claim supported by local evidence.",
                }],
                "final_claim_policy": {
                    "allowed_claims": ["Downloader behavior observed at runtime."],
                    "caveated_claims": ["Family attribution remains unconfirmed."],
                    "prohibited_claims": ["Confirmed ExampleLoader family attribution."],
                },
                "limitations": ["Family evidence remains incomplete."],
                "upstream_inputs": ["02-static-pass1.json", "05-dynamic.json", "06-intel.json"],
            }, indent=2),
            encoding="utf-8",
        )
        (report_dir / "06-intel.json").write_text(
            json.dumps({
                "schema_version": "1.0",
                "stage": "intel",
                "sample_sha256": "a" * 64,
                "status": "completed",
                "summary": "VirusTotal labels suggest downloader family names.",
                "provider_queries": [],
                "claim_checks": [{
                    "id": "cc.family",
                    "claim_text": "Public labels suggest ExampleLoader.",
                    "related_stage": "intel",
                    "related_finding_ids": [],
                    "verification_status": "public_label_only",
                    "provider_query_ids": [],
                    "analysis": "Only public labels matched.",
                    "report_use": "followup_only",
                }],
                "ioc_correlation": {
                    "matched_local": [],
                    "local_only_no_public_match": [],
                    "external_only": [],
                },
                "enrichment_candidates": [],
                "limitations": ["Public-only evidence."],
                "upstream_inputs": ["05-dynamic.json"],
            }, indent=2),
            encoding="utf-8",
        )

        out = report_dir / "08-report.context.md"
        res = report_tool.handler(
            report_dir=str(report_dir),
            output_path=str(out),
        )

        assert not res.is_error, res.content
        text = out.read_text(encoding="utf-8")
        assert text.startswith("# Compact report context")
        assert "remains authoritative for verdicts and claim boundaries" in text
        assert "Downloader network behavior" in text
        assert "Family attribution" in text
        assert "VirusTotal labels suggest downloader family names." in text
        assert "Do not widen claims from this section." in text
        assert res.content == text.strip()

    def test_fetch_vt_report_rejects_bad_hash_offline(self, tmp_path):
        """The script's own regex check fails before any network I/O."""
        out = REAL_SCRIPTS / "vt.json"
        try:
            res = _analysis_tool("fetch_vt_report").handler(
                file_id="not-a-hash",
                output_path=str(out),
            )
            assert res.is_error
        finally:
            out.unlink(missing_ok=True)


class TestStageToolResolution:
    @pytest.fixture()
    def registry(self):
        scope = _scope(REAL_SCRIPTS)
        registry = ToolRegistry()
        registry.register_many(create_filesystem_tools(scope))
        registry.register_many(create_analysis_tools(REAL_SCRIPTS, scope))
        registry.register_many(create_vmware_tools(VMwareConfig(), scope))
        registry.register(x64dbg_health_check_tool(UNREACHABLE))
        registry.register(ida_health_check_tool(UNREACHABLE))
        return registry

    def test_prepare_env_exact_tool_set(self, registry):
        names = {t.name for t in registry.get_tools_for_stage("01-prepare-env")}
        assert names == {
            "read_file", "write_file", "sha256_file",
            "list_directory", "file_exists", "mkdir",
            "vm_check_vmrun", "vm_revert_snapshot", "vm_start", "vm_get_guest_ip",
            "vm_copy_to_guest", "vm_run_program", "vm_run_debugger_with_sample",
            "x64dbg_health_check", "ida_health_check", "validate_json_output",
        }

    def test_refresh_x64dbg_tools_adds_debugger_surface_when_server_becomes_live(self, monkeypatch, scope):
        registry = ToolRegistry()
        registry.register(x64dbg_health_check_tool(UNREACHABLE))
        clients = []

        fake_tools = [
            ToolDefinition(name="debug_init", description="", parameters={}, handler=lambda **_: None, source="x64dbg"),
            ToolDefinition(name="debug_get_state", description="", parameters={}, handler=lambda **_: None, source="x64dbg"),
            ToolDefinition(name="module_get_main", description="", parameters={}, handler=lambda **_: None, source="x64dbg"),
            ToolDefinition(name="module_list", description="", parameters={}, handler=lambda **_: None, source="x64dbg"),
            ToolDefinition(name="symbol_resolve", description="", parameters={}, handler=lambda **_: None, source="x64dbg"),
            ToolDefinition(name="breakpoint_set", description="", parameters={}, handler=lambda **_: None, source="x64dbg"),
            ToolDefinition(name="breakpoint_list", description="", parameters={}, handler=lambda **_: None, source="x64dbg"),
            ToolDefinition(name="memory_enumerate", description="", parameters={}, handler=lambda **_: None, source="x64dbg"),
            ToolDefinition(name="memory_read", description="", parameters={}, handler=lambda **_: None, source="x64dbg"),
            ToolDefinition(name="dump_get_dumpable_regions", description="", parameters={}, handler=lambda **_: None, source="x64dbg"),
            ToolDefinition(name="dump_memory_region", description="", parameters={}, handler=lambda **_: None, source="x64dbg"),
            ToolDefinition(name="dump_module", description="", parameters={}, handler=lambda **_: None, source="x64dbg"),
        ]

        class _FakeClient:
            def close(self):
                return None

        monkeypatch.setattr(
            "hyperagent.tools.registry.create_x64dbg_tools",
            lambda endpoint: (_FakeClient(), fake_tools),
        )

        client = refresh_x64dbg_tools(registry, clients, UNREACHABLE, "05-dynamic")
        assert client is not None
        names = {tool.name for tool in registry.get_tools_for_stage("05-dynamic")}
        assert "debug_init" in names
        assert "memory_read" in names
        assert "dump_module" in names
        assert clients == [client]

    def test_refresh_x64dbg_tools_reports_empty_discovery(self, monkeypatch, caplog):
        registry = ToolRegistry()
        registry.register(x64dbg_health_check_tool(UNREACHABLE))
        clients = []

        class _FakeClient:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        fake_client = _FakeClient()
        monkeypatch.setattr(
            "hyperagent.tools.registry.create_x64dbg_tools",
            lambda endpoint: (fake_client, []),
        )

        client = refresh_x64dbg_tools(registry, clients, UNREACHABLE, "05-dynamic")
        assert client is None
        assert fake_client.closed is True
        assert clients == []
        assert "x64dbg MCP discovery returned no tools" in caplog.text
        assert "debug_init" in caplog.text

    def test_refresh_x64dbg_tools_rejects_incomplete_debugger_surface(self, monkeypatch, caplog):
        registry = ToolRegistry()
        clients = []

        class _FakeClient:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        fake_client = _FakeClient()
        monkeypatch.setattr(
            "hyperagent.tools.registry.create_x64dbg_tools",
            lambda endpoint: (
                fake_client,
                [ToolDefinition(name="debug_init", description="", parameters={}, handler=lambda **_: None, source="x64dbg")],
            ),
        )

        client = refresh_x64dbg_tools(registry, clients, UNREACHABLE, "05-dynamic")
        assert client is None
        assert fake_client.closed is True
        assert registry.get_tool("debug_init") is None
        assert "missing required wrappers" in caplog.text
        assert "module_get_main" in caplog.text

    def test_missing_x64dbg_required_tools_lists_unregistered_wrappers(self):
        registry = ToolRegistry()
        registry.register(ToolDefinition(name="debug_init", description="", parameters={}, handler=lambda **_: None, source="x64dbg"))

        missing = missing_x64dbg_required_tools(registry)
        assert "debug_init" not in missing
        assert "module_get_main" in missing
        assert "dump_module" in missing

    def test_refresh_x64dbg_tools_skips_non_debugger_stages(self, monkeypatch):
        registry = ToolRegistry()
        clients = []
        called = {"value": False}

        def _unexpected(endpoint):
            called["value"] = True
            return None, []

        monkeypatch.setattr("hyperagent.tools.registry.create_x64dbg_tools", _unexpected)

        client = refresh_x64dbg_tools(registry, clients, UNREACHABLE, "01-prepare-env")
        assert client is None
        assert not called["value"]

    def test_refresh_x64dbg_tools_keeps_existing_surface(self, monkeypatch):
        registry = ToolRegistry()
        registry.register(ToolDefinition(name="debug_init", description="", parameters={}, handler=lambda **_: None, source="x64dbg"))
        registry.register(ToolDefinition(name="debug_get_state", description="", parameters={}, handler=lambda **_: None, source="x64dbg"))
        registry.register(ToolDefinition(name="module_get_main", description="", parameters={}, handler=lambda **_: None, source="x64dbg"))
        registry.register(ToolDefinition(name="module_list", description="", parameters={}, handler=lambda **_: None, source="x64dbg"))
        registry.register(ToolDefinition(name="symbol_resolve", description="", parameters={}, handler=lambda **_: None, source="x64dbg"))
        registry.register(ToolDefinition(name="breakpoint_set", description="", parameters={}, handler=lambda **_: None, source="x64dbg"))
        registry.register(ToolDefinition(name="breakpoint_list", description="", parameters={}, handler=lambda **_: None, source="x64dbg"))
        registry.register(ToolDefinition(name="memory_enumerate", description="", parameters={}, handler=lambda **_: None, source="x64dbg"))
        registry.register(ToolDefinition(name="memory_read", description="", parameters={}, handler=lambda **_: None, source="x64dbg"))
        registry.register(ToolDefinition(name="dump_get_dumpable_regions", description="", parameters={}, handler=lambda **_: None, source="x64dbg"))
        registry.register(ToolDefinition(name="dump_memory_region", description="", parameters={}, handler=lambda **_: None, source="x64dbg"))
        registry.register(ToolDefinition(name="dump_module", description="", parameters={}, handler=lambda **_: None, source="x64dbg"))
        clients = []
        called = {"value": False}

        def _unexpected(endpoint):
            called["value"] = True
            return None, []

        monkeypatch.setattr("hyperagent.tools.registry.create_x64dbg_tools", _unexpected)

        client = refresh_x64dbg_tools(registry, clients, UNREACHABLE, "05-dynamic")
        assert client is None
        assert not called["value"]

    def test_deepdive_is_filesystem_only(self, registry):
        names = {t.name for t in registry.get_tools_for_stage("07-deepdive")}
        assert names == {
            "read_file", "write_file", "sha256_file",
            "list_directory", "file_exists", "mkdir",
        }

    def test_report_stage_prefers_compact_context_tool(self, registry):
        names = {t.name for t in registry.get_tools_for_stage("08-report")}
        assert names == {"write_file", "build_report_context"}

    def test_source_pseudo_pattern_selects_by_source(self, registry):
        names = {t.name for t in registry.get_tools_for_stage("02-static-pass1")}
        assert "ida_health_check" in names
        assert "x64dbg_health_check" not in names
        assert not any(n.startswith("vm_") for n in names)

    def test_unknown_stage_raises(self, registry):
        with pytest.raises(KeyError):
            registry.get_tools_for_stage("unknown-stage")

    def test_every_stage_resolves(self, registry):
        for stage_id in STAGE_TOOLS:
            assert registry.get_tools_for_stage(stage_id)
    def test_vt_tools_only_available_to_intel(self, registry):
        intel_names = {t.name for t in registry.get_tools_for_stage("06-intel")}
        assert "fetch_vt_report" in intel_names
        assert "normalize_vt_report" in intel_names

        for stage_id in STAGE_TOOLS:
            if stage_id == "06-intel":
                continue
            names = {t.name for t in registry.get_tools_for_stage(stage_id)}
            assert "fetch_vt_report" not in names
            assert "normalize_vt_report" not in names

    def test_execute_for_stage_rejects_unauthorized_tool(self, registry):
        with pytest.raises(UnauthorizedToolError) as exc_info:
            registry.execute_for_stage("08-report", "fetch_vt_report", {"file_id": "a" * 64})

        assert exc_info.value.stage_id == "08-report"
        assert exc_info.value.tool_name == "fetch_vt_report"
        assert "unauthorized_tool_for_stage" in str(exc_info.value)

    def test_execute_for_stage_allows_authorized_tool(self):
        called = []
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="normalize_vt_report",
                description="fake normalize",
                parameters={},
                handler=lambda **kwargs: called.append(kwargs) or ToolResult(content="ok"),
            )
        )
        res = registry.execute_for_stage("06-intel", "normalize_vt_report", {"output_path": "intel.json"})

        assert not res.is_error
        assert called == [{"output_path": "intel.json"}]

    def test_execute_for_stage_allows_report_context_builder(self):
        called = []
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="build_report_context",
                description="fake report context",
                parameters={},
                handler=lambda **kwargs: called.append(kwargs) or ToolResult(content="# Compact report context"),
            )
        )
        res = registry.execute_for_stage(
            "08-report",
            "build_report_context",
            {"report_dir": "reports/abc", "output_path": "reports/abc/08-report.context.md"},
        )

        assert not res.is_error
        assert called == [{"report_dir": "reports/abc", "output_path": "reports/abc/08-report.context.md"}]
        assert res.content.startswith("# Compact report context")

    def test_execute_for_stage_rejects_raw_read_file_for_report(self, registry):
        with pytest.raises(UnauthorizedToolError) as exc_info:
            registry.execute_for_stage("08-report", "read_file", {"path": "reports/abc/06-intel.json"})

        assert exc_info.value.stage_id == "08-report"
        assert exc_info.value.tool_name == "read_file"
        assert "unauthorized_tool_for_stage" in str(exc_info.value)
        assert "build_report_context" in str(exc_info.value)
        assert "write_file" in str(exc_info.value)


def test_common_scripts_dir(tmp_path):
    assert common_scripts_dir(tmp_path) == tmp_path / "_hyperagent-common" / "scripts"


def test_analysis_tools_default_to_repo_skill_scripts(monkeypatch):
    monkeypatch.delenv("HYPERAGENT_SCRIPTS_DIR", raising=False)
    monkeypatch.delenv("HYPERAGENT_SKILLS_ROOT", raising=False)
    expected = REPO_ROOT / "skill" / "_hyperagent-common" / "scripts"
    assert create_analysis_tools(None, _scope(REPO_ROOT))[0].handler.__closure__ is not None
    from hyperagent.tools.analysis_tools import _get_scripts_dir
    assert _get_scripts_dir() == expected


class TestMCPDegradation:
    """An unreachable MCP endpoint must degrade, never raise."""

    def test_create_x64dbg_tools_unreachable(self):
        client, tools = create_x64dbg_tools(UNREACHABLE)
        try:
            assert tools == []
        finally:
            client.close()

    def test_create_x64dbg_tools_degrades_on_mcp_protocol_error(self, monkeypatch, caplog):
        class _ProtocolErrorClient:
            def __init__(self, *args, **kwargs):
                self.closed = False

            def get_tool_definitions(self):
                raise RuntimeError("MCP error -32000: initialized required")

            def close(self):
                self.closed = True

        monkeypatch.setattr("hyperagent.tools.x64dbg_tools.MCPClient", _ProtocolErrorClient)

        client, tools = create_x64dbg_tools(UNREACHABLE)
        assert tools == []
        assert "x64dbg MCP tool discovery failed" in caplog.text
        client.close()
        assert client.closed is True

    def test_create_ida_tools_unreachable(self):
        client, tools = create_ida_tools(UNREACHABLE)
        try:
            assert tools == []
        finally:
            client.close()

    def test_health_check_unreachable_is_error(self):
        assert x64dbg_health_check_tool(UNREACHABLE).handler().is_error
        assert ida_health_check_tool(UNREACHABLE).handler().is_error

    def test_build_full_registry_survives_unreachable_mcp(self, tmp_path):
        config = HyperAgentConfig(
            x64dbg_mcp=UNREACHABLE,
            ida_mcp=UNREACHABLE,
            skills_root=tmp_path,
        )
        scope = _scope(tmp_path)
        registry, clients = build_full_registry(config, scope)
        try:
            mcp_named = {
                t.name for t in registry.get_all_tools()
                if t.source in ("x64dbg", "ida")
            }
            assert mcp_named == {"x64dbg_health_check", "ida_health_check"}
            assert len(clients) == 2
        finally:
            for c in clients:
                c.close()
