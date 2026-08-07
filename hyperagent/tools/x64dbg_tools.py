"""x64dbg MCP tool wrappers.

Wraps the x64dbg-mcp server tools as ``ToolDefinition`` instances that the
agentic loop can offer to the LLM and dispatch at runtime.
"""
from __future__ import annotations

from ..config import MCPEndpoint
from .base import ToolDefinition, ToolResult
from .mcp_client import MCPClient


def create_x64dbg_tools(endpoint: MCPEndpoint) -> tuple[MCPClient, list[ToolDefinition]]:
    """Connect to x64dbg MCP and return (client, tool_definitions).

    The caller is responsible for closing the client when done.
    """
    client = MCPClient(
        endpoint_url=endpoint.url,
        health_url=endpoint.url.rsplit("/", 1)[0] + "/",
        timeout=endpoint.timeout,
        client_name="hyperagent",
    )
    tools = client.get_tool_definitions()
    return client, tools


def x64dbg_health_check_tool(endpoint: MCPEndpoint) -> ToolDefinition:
    """A standalone health-check tool for the prepare-env stage."""
    def handler(**_kwargs) -> ToolResult:
        client = MCPClient(
            endpoint_url=endpoint.url,
            health_url=endpoint.url.rsplit("/", 1)[0] + "/",
            timeout=5,
        )
        try:
            ok = client.health_check()
            if ok:
                return ToolResult(content='{"status": "ok", "service": "x64dbg-mcp"}')
            return ToolResult(content='{"status": "unreachable"}', is_error=True)
        finally:
            client.close()

    return ToolDefinition(
        name="x64dbg_health_check",
        description="Check if the x64dbg MCP server in the guest VM is reachable.",
        parameters={"type": "object", "properties": {}},
        handler=handler,
    )
