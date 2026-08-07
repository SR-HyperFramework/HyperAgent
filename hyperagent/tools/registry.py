"""Central registry for Agent tools."""
from __future__ import annotations

import logging
from typing import Any

from .analysis_tools import create_analysis_tools
from .base import ToolDefinition, ToolResult
from .filesystem_tools import create_filesystem_tools

logger = logging.getLogger(__name__)


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


def build_core_registry() -> ToolRegistry:
    """Build a registry pre-populated with core host tools (filesystem, analysis).
    
    Note: MCP tools (x64dbg, ida) require active connections and must be
    registered at runtime by the pipeline orchestrator.
    """
    registry = ToolRegistry()
    registry.register_many(create_filesystem_tools())
    registry.register_many(create_analysis_tools())
    return registry
