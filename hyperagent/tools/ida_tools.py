"""IDA Pro MCP tool wrappers.

Replaces the Claude Code ``/ida-pro:idapython`` plugin with direct MCP calls
to an IDA Pro MCP server running on the host.
"""
from __future__ import annotations

import dataclasses
import logging
from typing import Any

from ..config import MCPEndpoint
from .base import ToolDefinition, ToolResult
from .mcp_client import MCPClient
from .path_scope import PathScope, PathScopeError

_PATH_KWARGS = {"path", "file_path", "input_path"}


def _scoped_ida_handler_factory(scope: PathScope):
    def factory(client: MCPClient, tool_name: str):
        def handler(**kwargs: Any) -> ToolResult:
            try:
                scoped_kwargs: dict[str, Any] = {}
                for key, value in kwargs.items():
                    if key in _PATH_KWARGS and isinstance(value, str) and value:
                        scoped_kwargs[key] = str(scope.check_read(value))
                    else:
                        scoped_kwargs[key] = value
                text = client.call_tool(tool_name, scoped_kwargs)
                return ToolResult(content=text)
            except PathScopeError as exc:
                return ToolResult(content=str(exc), is_error=True)
            except Exception as exc:
                return ToolResult(content=f"MCP tool error: {exc}", is_error=True)
        return handler
    return factory




logger = logging.getLogger(__name__)


def create_ida_tools(
    endpoint: MCPEndpoint,
    *,
    scope: PathScope | None = None,
) -> tuple[MCPClient, list[ToolDefinition]]:
    """Connect to IDA Pro MCP and return (client, tool_definitions).

    The IDA MCP server is expected to expose tools such as:
    ``survey_binary``, ``server_warmup``, ``imports``, ``find_regex``,
    ``get_bytes``, ``analyze_batch``, ``callgraph``, ``xrefs_to``,
    ``decompile``.

    If the MCP server is unreachable, degrades to an empty tool list instead
    of raising, so registry construction can proceed with IDA simply
    unavailable for this run.

    The caller is responsible for closing the client when done.
    """
    client = MCPClient(
        endpoint_url=endpoint.url,
        health_url=endpoint.url.rsplit("/", 1)[0] + "/",
        timeout=endpoint.timeout,
        client_name="hyperagent",
    )
    try:
        handler_factory = _scoped_ida_handler_factory(scope) if scope is not None else None
        tools = client.get_tool_definitions(handler_factory=handler_factory)
    except ConnectionError as exc:
        logger.warning("IDA Pro MCP unreachable at %s: %s", endpoint.url, exc)
        return client, []
    return client, [dataclasses.replace(t, source="ida") for t in tools]


def ida_health_check_tool(endpoint: MCPEndpoint) -> ToolDefinition:
    """Standalone health-check tool for IDA Pro MCP availability."""
    def handler(**_kwargs) -> ToolResult:
        client = MCPClient(
            endpoint_url=endpoint.url,
            health_url=endpoint.url.rsplit("/", 1)[0] + "/",
            timeout=5,
        )
        try:
            ok = client.health_check()
            if ok:
                return ToolResult(content='{"status": "ok", "service": "ida-pro-mcp"}')
            return ToolResult(content='{"status": "unreachable"}', is_error=True)
        finally:
            client.close()

    return ToolDefinition(
        name="ida_health_check",
        description="Check if the IDA Pro MCP server is reachable on the host.",
        parameters={"type": "object", "properties": {}},
        handler=handler,
        source="ida",
    )
