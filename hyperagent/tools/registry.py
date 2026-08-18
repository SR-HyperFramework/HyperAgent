"""Central registry for Agent tools."""
from __future__ import annotations

import logging
from fnmatch import fnmatch
from typing import Any

from ..config import HyperAgentConfig
from .analysis_tools import create_analysis_tools
from .base import ToolDefinition, ToolResult
from .filesystem_tools import create_filesystem_tools
from .ida_tools import create_ida_tools, ida_health_check_tool
from .mcp_client import MCPClient
from .path_scope import PathScope
from .vmware_tools import create_vmware_tools
from .x64dbg_tools import create_x64dbg_tools, x64dbg_health_check_tool

logger = logging.getLogger(__name__)


_FILESYSTEM_TOOLS = [
    "read_file", "write_file", "sha256_file",
    "list_directory", "file_exists", "mkdir",
]
_ANALYSIS_TOOLS = [
    "upx_unpack", "fetch_vt_report",
    "normalize_vt_report", "validate_json_output",
]

STAGE_TOOLS: dict[str, list[str]] = {
    "01-prepare-env":  ["vm_*", *_FILESYSTEM_TOOLS, "x64dbg_health_check"],
    "02-static-pass1": ["source:ida", *_FILESYSTEM_TOOLS, *_ANALYSIS_TOOLS],
    "03-unpack":       ["source:x64dbg", "vm_*", *_FILESYSTEM_TOOLS, *_ANALYSIS_TOOLS],
    "04-static-pass2": ["source:ida", *_FILESYSTEM_TOOLS, *_ANALYSIS_TOOLS],
    "05-dynamic":      ["source:x64dbg", "vm_*", *_FILESYSTEM_TOOLS, *_ANALYSIS_TOOLS],
    "06-intel":        [*_ANALYSIS_TOOLS, *_FILESYSTEM_TOOLS],
    "07-deepdive":     [*_FILESYSTEM_TOOLS],
    "08-report":       [*_FILESYSTEM_TOOLS, *_ANALYSIS_TOOLS],
    "09-summary":      [*_FILESYSTEM_TOOLS],
}


class ToolRegistry:
    """Manages available tools and executes them dynamically."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        """Register a new tool."""
        if tool.name in self._tools:
            logger.warning("Overwriting existing tool: %s", tool.name)
        self._tools[tool.name] = tool

    def register_many(self, tools: list[ToolDefinition]) -> None:
        """Register a list of tools."""
        for t in tools:
            self.register(t)

    def get_tool(self, name: str) -> ToolDefinition | None:
        """Retrieve a tool by name."""
        return self._tools.get(name)

    def get_all_tools(self) -> list[ToolDefinition]:
        """Retrieve all registered tools."""
        return list(self._tools.values())

    def get_tools_for_stage(self, stage_id: str) -> list[ToolDefinition]:
        """Resolve the tool subset a pipeline stage is allowed to use.

        Patterns in ``STAGE_TOOLS[stage_id]`` are matched against registered
        tools as: ``source:<x>`` -> ``tool.source == x``; a pattern containing
        a glob char (``*?[``) -> ``fnmatch(tool.name, pattern)``; otherwise an
        exact ``tool.name`` match. Results are deduped by tool name.
        """
        if stage_id not in STAGE_TOOLS:
            raise KeyError(
                f"Unknown stage_id {stage_id!r}. Known stages: {sorted(STAGE_TOOLS)}"
            )

        patterns = STAGE_TOOLS[stage_id]
        resolved: dict[str, ToolDefinition] = {}
        for tool in self._tools.values():
            for pattern in patterns:
                if pattern.startswith("source:"):
                    matched = tool.source == pattern[len("source:"):]
                elif any(c in pattern for c in "*?["):
                    matched = fnmatch(tool.name, pattern)
                else:
                    matched = tool.name == pattern
                if matched:
                    resolved[tool.name] = tool
                    break
        return list(resolved.values())

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a tool by name with the given arguments."""
        tool = self._tools.get(tool_name)
        if not tool:
            return ToolResult(
                content=f"Tool '{tool_name}' is not registered.", is_error=True
            )

        if not tool.handler:
            return ToolResult(
                content=f"Tool '{tool_name}' has no handler attached.", is_error=True
            )

        try:
            logger.debug("Executing tool %s with args: %s", tool_name, arguments)
            return tool.handler(**arguments)
        except Exception as exc:
            logger.exception("Tool execution failed: %s", tool_name)
            return ToolResult(content=f"Tool execution failed: {exc}", is_error=True)


def build_core_registry(scope: PathScope, scripts_dir=None) -> ToolRegistry:
    """Build a registry pre-populated with core host tools (filesystem, analysis).

    Note: MCP tools (x64dbg, ida) require active connections and must be
    registered at runtime by the pipeline orchestrator.
    """
    registry = ToolRegistry()
    registry.register_many(create_filesystem_tools(scope))
    registry.register_many(create_analysis_tools(scripts_dir, scope))
    return registry


def build_full_registry(
    config: HyperAgentConfig,
    scope: PathScope,
) -> tuple[ToolRegistry, list[MCPClient]]:
    """Build a registry with every tool source: filesystem, analysis, vmware,
    and whatever x64dbg/ida MCP tools are discoverable right now.

    x64dbg/ida MCP servers being unreachable does not raise — those tools are
    simply absent, minus the two health-check tools which are always present.
    Returns the registry plus the opened ``MCPClient``s so the caller can
    ``.close()`` them when the run ends.
    """
    registry = ToolRegistry()
    registry.register_many(create_filesystem_tools(scope))
    registry.register_many(
        create_analysis_tools(config.skills_root / "_hyperagent-common" / "scripts", scope)
    )
    registry.register_many(create_vmware_tools(config.vmware, scope))

    registry.register(x64dbg_health_check_tool(config.x64dbg_mcp))
    registry.register(ida_health_check_tool(config.ida_mcp))

    x64dbg_client, x64dbg_tools = create_x64dbg_tools(config.x64dbg_mcp)
    ida_client, ida_tools = create_ida_tools(config.ida_mcp, scope=scope)
    registry.register_many(x64dbg_tools)
    registry.register_many(ida_tools)

    return registry, [x64dbg_client, ida_client]
