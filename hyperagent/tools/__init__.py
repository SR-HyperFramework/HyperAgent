"""Tools module export."""
from __future__ import annotations

from .analysis_tools import create_analysis_tools
from .base import ToolDefinition, ToolResult
from .filesystem_tools import create_filesystem_tools
from .ida_tools import create_ida_tools, ida_health_check_tool
from .mcp_client import MCPClient
from .path_scope import PathScope, PathScopeError, compute_run_scope
from .registry import STAGE_TOOLS, ToolRegistry, build_core_registry, build_full_registry
from .vmware_tools import create_vmware_tools
from .x64dbg_tools import create_x64dbg_tools, x64dbg_health_check_tool

__all__ = [
    "ToolDefinition",
    "ToolResult",
    "ToolRegistry",
    "build_core_registry",
    "build_full_registry",
    "STAGE_TOOLS",
    "MCPClient",
    "PathScope",
    "PathScopeError",
    "compute_run_scope",
    "create_vmware_tools",
    "create_filesystem_tools",
    "create_analysis_tools",
    "create_x64dbg_tools",
    "x64dbg_health_check_tool",
    "create_ida_tools",
    "ida_health_check_tool",
]
