"""Generic JSON-RPC 2.0 MCP client.

Connects to any MCP-compliant server (x64dbg, IDA Pro, etc.) over HTTP,
handles the ``initialize`` → ``tools/list`` → ``tools/call`` lifecycle,
and exposes discovered tools as ``ToolDefinition`` instances.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

import httpx

from .base import ToolDefinition, ToolResult

logger = logging.getLogger(__name__)


class MCPClient:
    """Stateful client for a single MCP server."""

    def __init__(
        self,
        endpoint_url: str,
        *,
        health_url: str | None = None,
        timeout: int = 30,
        client_name: str = "hyperagent",
        client_version: str = "4.0",
    ) -> None:
        self._endpoint = endpoint_url
        self._health_url = health_url or endpoint_url.rsplit("/", 1)[0] + "/"
        self._timeout = timeout
        self._client_info = {"name": client_name, "version": client_version}
        self._http = httpx.Client(timeout=timeout)
        self._request_id = 0
        self._initialized = False
        self._server_tools: list[dict[str, Any]] = []

    # -- lifecycle ------------------------------------------------------------

    def health_check(self) -> bool:
        """Return True if the MCP server health endpoint responds."""
        try:
            r = self._http.get(self._health_url, timeout=5)
            return r.status_code == 200
        except (httpx.HTTPError, OSError):
            return False

    def initialize(self) -> dict[str, Any]:
        """Send MCP ``initialize`` handshake."""
        result = self._rpc("initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": self._client_info,
        })
        self._initialized = True
        logger.info("MCP initialized: %s", result.get("serverInfo", {}))
        return result

    def list_tools(self) -> list[dict[str, Any]]:
        """Fetch available tools from the server and cache them."""
        if not self._initialized:
            self.initialize()
        result = self._rpc("tools/list", {})
        self._server_tools = result.get("tools", [])
        logger.info("MCP tools discovered: %d", len(self._server_tools))
        return self._server_tools

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        """Invoke a tool and return the text content from the response."""
        if not self._initialized:
            self.initialize()
        result = self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        # MCP tools return content in result.content[0].text
        content_list = result.get("content", [])
        if content_list:
            return content_list[0].get("text", json.dumps(result))
        return json.dumps(result)

    # -- tool definition export -----------------------------------------------

    def get_tool_definitions(
        self,
        handler_factory: Callable[["MCPClient", str], Callable[..., ToolResult]] | None = None,
    ) -> list[ToolDefinition]:
        """Convert discovered MCP tools to ``ToolDefinition`` instances.

        If ``handler_factory`` is provided, it is called with ``(mcp_client, tool_name)``
        and must return a callable ``(**kwargs) -> ToolResult``.
        """
        if not self._server_tools:
            self.list_tools()

        definitions: list[ToolDefinition] = []
        for tool in self._server_tools:
            name = tool.get("name", "")
            desc = tool.get("description", "")
            schema = tool.get("inputSchema", {"type": "object", "properties": {}})

            handler = None
            if handler_factory:
                handler = handler_factory(self, name)
            else:
                handler = self._make_default_handler(name)

            definitions.append(ToolDefinition(
                name=name,
                description=desc,
                parameters=schema,
                handler=handler,
            ))
        return definitions

    # -- internal -------------------------------------------------------------

    def _make_default_handler(self, tool_name: str):
        """Create a default handler that calls the MCP tool and returns a ToolResult."""
        def handler(**kwargs) -> ToolResult:
            try:
                text = self.call_tool(tool_name, kwargs)
                return ToolResult(content=text)
            except Exception as exc:
                return ToolResult(content=f"MCP tool error: {exc}", is_error=True)
        return handler

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON-RPC 2.0 request and return the result dict."""
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params,
        }
        try:
            response = self._http.post(
                self._endpoint,
                json=payload,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ConnectionError(f"MCP request failed for {method}: {exc}") from exc

        data = response.json()
        if "error" in data:
            err = data["error"]
            raise RuntimeError(f"MCP error {err.get('code')}: {err.get('message')}")
        return data.get("result", {})

    def close(self) -> None:
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
