"""Unit tests for the tool layer: analysis wrappers, stage resolution, MCP degradation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hyperagent.config import HyperAgentConfig, MCPEndpoint, VMwareConfig
from hyperagent.tools.analysis_tools import create_analysis_tools
from hyperagent.tools.filesystem_tools import create_filesystem_tools
from hyperagent.tools.ida_tools import create_ida_tools, ida_health_check_tool
from hyperagent.tools.registry import STAGE_TOOLS, ToolRegistry, build_full_registry
from hyperagent.tools.vmware_tools import create_vmware_tools
from hyperagent.tools.x64dbg_tools import create_x64dbg_tools, x64dbg_health_check_tool

FIXTURES = Path(__file__).parent / "fixtures" / "analysis_tools"
REAL_SCRIPTS = (
    Path(__file__).resolve().parents[2]
    / "skill" / "backup" / "hyperagent-malware-analyze" / "v3"
    / "_hyperagent-common" / "scripts"
)

requires_scripts = pytest.mark.skipif(
    not REAL_SCRIPTS.is_dir(),
    reason=f"helper scripts not present at {REAL_SCRIPTS}",
)

# Port 1 is reserved and refuses connections instantly — no server needed.
UNREACHABLE = MCPEndpoint(url="http://127.0.0.1:1/mcp", timeout=2)


def _tool(name: str):
    """Fetch a handler from a scripts-dir-bound analysis tool set."""
    for t in create_analysis_tools(REAL_SCRIPTS):
        if t.name == name:
            return t
    raise AssertionError(f"tool {name} not built")


class TestAnalysisToolGuards:
    """Argument guards must reject before any subprocess is spawned."""

    def test_upx_unpack_missing_args(self):
        res = _tool("upx_unpack").handler(input_path="", output_path="")
        assert res.is_error

    def test_fetch_vt_report_missing_file_id(self):
        res = _tool("fetch_vt_report").handler(file_id="", output_path="/tmp/x.json")
        assert res.is_error

    def test_normalize_vt_report_requires_one_source(self):
        res = _tool("normalize_vt_report").handler(output_path="/tmp/x.json")
        assert res.is_error
        assert "at least one" in res.content.lower()

    def test_validate_json_output_missing_args(self):
        res = _tool("validate_json_output").handler(schema_path="", json_path="")
        assert res.is_error


@requires_scripts
class TestAnalysisToolSubprocess:
    """Real subprocess calls against the real helper scripts — all offline."""

    def test_validate_json_output_valid(self):
        res = _tool("validate_json_output").handler(
            schema_path=str(FIXTURES / "schema.json"),
            json_path=str(FIXTURES / "valid.json"),
        )
        assert not res.is_error
        assert "VALID" in res.content

    def test_validate_json_output_invalid(self):
        res = _tool("validate_json_output").handler(
            schema_path=str(FIXTURES / "schema.json"),
            json_path=str(FIXTURES / "invalid.json"),
        )
        assert res.is_error

    def test_normalize_vt_report_writes_json(self, tmp_path):
        out = tmp_path / "intel.json"
        res = _tool("normalize_vt_report").handler(
            file_info_path=str(FIXTURES / "file_info.json"),
            output_path=str(out),
        )
        assert not res.is_error, res.content
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["stage"] == "intel"
        assert payload["sample_sha256"] == "a" * 64

    def test_fetch_vt_report_rejects_bad_hash_offline(self, tmp_path):
        """The script's own regex check fails before any network I/O."""
        res = _tool("fetch_vt_report").handler(
            file_id="not-a-hash",
            output_path=str(tmp_path / "vt.json"),
        )
        assert res.is_error


class TestStageToolResolution:
    def _registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register_many(create_filesystem_tools())
        registry.register_many(create_analysis_tools(REAL_SCRIPTS))
        registry.register_many(create_vmware_tools(VMwareConfig()))
        registry.register(x64dbg_health_check_tool(UNREACHABLE))
        registry.register(ida_health_check_tool(UNREACHABLE))
        return registry

    def test_prepare_env_exact_tool_set(self):
        names = {t.name for t in self._registry().get_tools_for_stage("01-prepare-env")}
        assert names == {
            "read_file", "write_file", "sha256_file",
            "list_directory", "file_exists", "mkdir",
            "vm_revert_snapshot", "vm_start", "vm_get_guest_ip",
            "vm_copy_to_guest", "vm_run_program", "vm_run_debugger_with_sample",
            "x64dbg_health_check",
        }

    def test_deepdive_is_filesystem_only(self):
        names = {t.name for t in self._registry().get_tools_for_stage("07-deepdive")}
        assert names == {
            "read_file", "write_file", "sha256_file",
            "list_directory", "file_exists", "mkdir",
        }

    def test_source_pseudo_pattern_selects_by_source(self):
        names = {t.name for t in self._registry().get_tools_for_stage("02-static-pass1")}
        # ida_health_check carries source="ida" and so is picked up by "source:ida"
        assert "ida_health_check" in names
        assert "x64dbg_health_check" not in names
        assert not any(n.startswith("vm_") for n in names)

    def test_unknown_stage_raises(self):
        with pytest.raises(KeyError):
            self._registry().get_tools_for_stage("unknown-stage")

    def test_every_stage_resolves(self):
        registry = self._registry()
        for stage_id in STAGE_TOOLS:
            assert registry.get_tools_for_stage(stage_id)


class TestMCPDegradation:
    """An unreachable MCP endpoint must degrade, never raise."""

    def test_create_x64dbg_tools_unreachable(self):
        client, tools = create_x64dbg_tools(UNREACHABLE)
        try:
            assert tools == []
        finally:
            client.close()

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
        registry, clients = build_full_registry(config)
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
