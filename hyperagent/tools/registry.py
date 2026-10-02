"""Central registry for Agent tools."""
from __future__ import annotations

import logging
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Iterable

from ..config import HyperAgentConfig, MCPEndpoint
from .analysis_tools import create_analysis_tools
from .base import ToolDefinition, ToolResult
from .filesystem_tools import create_filesystem_tools
from .ida_tools import create_ida_tools, ida_health_check_tool, ida_lifecycle_tools
from .mcp_client import MCPClient
from .path_scope import PathScope
from .vmware_tools import create_vmware_tools
from .x64dbg_tools import create_x64dbg_tools, x64dbg_health_check_tool

logger = logging.getLogger(__name__)


_FILESYSTEM_TOOLS = [
    "read_file", "write_file", "sha256_file",
    "list_directory", "file_exists", "mkdir",
]
_LOCAL_ANALYSIS_TOOLS = [
    "upx_unpack", "validate_json_output",
]
_INTEL_ENRICHMENT_TOOLS = [
    "fetch_vt_report", "normalize_vt_report",
]
_X64DBG_REQUIRED_TOOLS = [
    "debug_init",
    "debug_get_state",
    "module_get_main",
    "module_list",
    "symbol_resolve",
    "breakpoint_set",
    "breakpoint_list",
    "memory_enumerate",
    "memory_read",
    "dump_get_dumpable_regions",
    "dump_memory_region",
    "dump_module",
]

STAGE_TOOLS: dict[str, list[str]] = {
    "01-prepare-env": [
        "vm_*",
        *_FILESYSTEM_TOOLS,
        "x64dbg_health_check",
        "idalib_open",
        "idalib_health",
        "ida_health_check",
        "validate_json_output",
    ],
    "02-static-pass1": ["source:ida", *_FILESYSTEM_TOOLS, *_LOCAL_ANALYSIS_TOOLS],
    "03-unpack": ["source:x64dbg", "vm_*", *_FILESYSTEM_TOOLS, *_LOCAL_ANALYSIS_TOOLS],
    "04-static-pass2": ["source:ida", *_FILESYSTEM_TOOLS, *_LOCAL_ANALYSIS_TOOLS],
    "05-dynamic": ["source:x64dbg", "vm_*", *_FILESYSTEM_TOOLS, *_LOCAL_ANALYSIS_TOOLS],
    "06-intel": [*_INTEL_ENRICHMENT_TOOLS, *_FILESYSTEM_TOOLS, "validate_json_output"],
    "07-deepdive": [*_FILESYSTEM_TOOLS, "validate_json_output"],
    "08-report": ["write_file", "build_report_context"],
    "09-summary": [*_FILESYSTEM_TOOLS, "validate_json_output"],
}

_X64DBG_REFRESH_STAGES = {
    stage_id for stage_id, patterns in STAGE_TOOLS.items() if "source:x64dbg" in patterns
}


class UnauthorizedToolError(Exception):
    """Raised when a stage attempts to execute a tool outside its policy."""

    def __init__(self, stage_id: str, tool_name: str, allowed_tools: Iterable[str]) -> None:
        self.stage_id = stage_id
        self.tool_name = tool_name
        self.allowed_tools = tuple(sorted(allowed_tools))
        super().__init__(
            "unauthorized_tool_for_stage: "
            f"stage_id={stage_id!r} tool={tool_name!r} "
            f"allowed={', '.join(self.allowed_tools) or '<none>'}"
        )


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

    def has_tools(self, tool_names: list[str]) -> bool:
        """Return True when every named tool is registered."""
        return all(name in self._tools for name in tool_names)

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

    def execute_for_stage(self, stage_id: str, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a tool only when it is authorized for the given stage."""
        allowed_tools = {tool.name for tool in self.get_tools_for_stage(stage_id)}
        if tool_name not in allowed_tools:
            raise UnauthorizedToolError(stage_id, tool_name, allowed_tools)
        return self.execute(tool_name, arguments)

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


def common_scripts_dir(skills_root: Path) -> Path:
    """Return the canonical _hyperagent-common/scripts directory for a skills root."""
    return skills_root / "_hyperagent-common" / "scripts"


def missing_x64dbg_required_tools(registry: ToolRegistry) -> list[str]:
    """Return required x64dbg wrapper names that are not registered."""
    get_tool = getattr(registry, "get_tool", None)
    if callable(get_tool):
        return [name for name in _X64DBG_REQUIRED_TOOLS if get_tool(name) is None]

    get_all_tools = getattr(registry, "get_all_tools", None)
    if callable(get_all_tools):
        registered = {tool.name for tool in get_all_tools()}
        return [name for name in _X64DBG_REQUIRED_TOOLS if name not in registered]

    return list(_X64DBG_REQUIRED_TOOLS)


def _close_mcp_client(client: MCPClient, label: str) -> None:
    try:
        client.close()
    except Exception:
        logger.warning("Failed to close %s MCP client cleanly", label, exc_info=True)


def refresh_x64dbg_tools(
    registry: ToolRegistry,
    clients: list[MCPClient],
    endpoint: MCPEndpoint,
    stage_id: str,
    *,
    current_client: MCPClient | None = None,
) -> MCPClient | None:
    """Refresh x64dbg MCP tools for stages that need them after the guest is ready.

    The debugger MCP server may be unreachable during initial registry build and
    only become live after prepare-env boots the VM and launches x64dbg. For
    stages that depend on ``source:x64dbg`` tools, retry discovery just in time.
    """
    if stage_id not in _X64DBG_REFRESH_STAGES:
        return current_client
    missing_before = missing_x64dbg_required_tools(registry)
    if not missing_before:
        return current_client

    client, tools = create_x64dbg_tools(endpoint)
    if not tools:
        _close_mcp_client(client, "x64dbg")
        logger.warning(
            "x64dbg MCP discovery returned no tools for %s; missing required wrappers: %s",
            stage_id,
            ", ".join(missing_before),
        )
        return current_client

    existing_names = {tool.name for tool in registry.get_all_tools()}
    discovered_names = {tool.name for tool in tools}
    missing_after = [
        name for name in _X64DBG_REQUIRED_TOOLS
        if name not in existing_names and name not in discovered_names
    ]
    if missing_after:
        _close_mcp_client(client, "x64dbg")
        logger.warning(
            "x64dbg MCP discovered %d tools for %s but missing required wrappers: %s. Discovered: %s",
            len(tools),
            stage_id,
            ", ".join(missing_after),
            ", ".join(sorted(discovered_names)) or "<none>",
        )
        return current_client

    registry.register_many(tools)

    if current_client is not None and current_client in clients and current_client is not client:
        idx = clients.index(current_client)
        clients[idx] = client
        _close_mcp_client(current_client, "stale x64dbg")
    elif client not in clients:
        clients.append(client)

    logger.info(
        "x64dbg MCP registered required debugger wrappers for %s: %s",
        stage_id,
        ", ".join(_X64DBG_REQUIRED_TOOLS),
    )
    return client


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
        create_analysis_tools(common_scripts_dir(config.skills_root), scope)
    )
    registry.register_many(create_vmware_tools(config.vmware, scope))

    registry.register(x64dbg_health_check_tool(config.x64dbg_mcp))
    registry.register(ida_health_check_tool(config.ida_mcp))
    ida_lifecycle_client, ida_lifecycle = ida_lifecycle_tools(config.ida_mcp, scope=scope)
    registry.register_many(ida_lifecycle)

    x64dbg_client, x64dbg_tools = create_x64dbg_tools(config.x64dbg_mcp)
    ida_client, ida_tools = create_ida_tools(config.ida_mcp, scope=scope)
    registry.register_many(x64dbg_tools)
    registry.register_many(ida_tools)

    return registry, [x64dbg_client, ida_client, ida_lifecycle_client]
