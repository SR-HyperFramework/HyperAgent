"""x64dbg MCP tool wrappers.

Wraps the x64dbg-mcp server tools as ``ToolDefinition`` instances that the
agentic loop can offer to the LLM and dispatch at runtime.
"""
from __future__ import annotations

import dataclasses
import logging

from ..config import MCPEndpoint
from .base import ToolDefinition, ToolResult
from .mcp_client import MCPClient

logger = logging.getLogger(__name__)


def create_x64dbg_tools(endpoint: MCPEndpoint) -> tuple[MCPClient, list[ToolDefinition]]:
    """Connect to x64dbg MCP and return (client, tool_definitions).

    If the MCP server is unreachable, degrades to an empty tool list instead
    of raising, so registry construction can proceed with the debugger
    simply unavailable for this run.

    The caller is responsible for closing the client when done.
    """
    client = MCPClient(
        endpoint_url=endpoint.url,
        health_url=endpoint.url.rsplit("/", 1)[0] + "/",
        timeout=endpoint.timeout,
        client_name="hyperagent",
    )
    try:
        tools = client.get_tool_definitions()
    except ConnectionError as exc:
        logger.warning("x64dbg MCP unreachable at %s: %s", endpoint.url, exc)
        return client, []
    return client, [dataclasses.replace(t, source="x64dbg") for t in tools]


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
        source="x64dbg",
    )
