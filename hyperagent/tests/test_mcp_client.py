"""Tests for the generic MCP client, focused on liveness detection.

Uses a real loopback HTTP server rather than a stubbed transport: the bug
these cover was precisely a mismatch between what the client probed and what
a real MCP server serves, which a stubbed client cannot reproduce.
"""
from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from hyperagent.config import MCPEndpoint
from hyperagent.tools.ida_tools import ida_health_check_tool
from hyperagent.tools.mcp_client import MCPClient

# Port 1 is reserved and refuses connections instantly — no server needed.
UNREACHABLE = "http://127.0.0.1:1/mcp"


class _JsonRpcOnlyHandler(BaseHTTPRequestHandler):
    """Mimics idalib-mcp: JSON-RPC on POST /mcp, nothing else served."""

    def log_message(self, *_args):  # noqa: D102 - silence test output
        pass

    def _send(self, status: int, body: bytes, content_type: str = "text/plain") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        self._send(405 if self.path == "/mcp" else 404, b"Not Found\n")

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path != "/mcp":
            self._send(404, b"Not Found\n")
            return
        length = int(self.headers.get("Content-Length", 0))
        request = json.loads(self.rfile.read(length) or b"{}")
        payload = {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "result": {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake-idalib-mcp", "version": "1"},
            },
        }
        self._send(200, json.dumps(payload).encode("utf-8"), "application/json")


@pytest.fixture()
def jsonrpc_only_server() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _JsonRpcOnlyHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/mcp"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_health_check_accepts_server_that_only_speaks_jsonrpc(jsonrpc_only_server: str):
    """A GET-only probe reported idalib-mcp as unreachable while it worked."""
    client = MCPClient(endpoint_url=jsonrpc_only_server, timeout=5)
    try:
        assert client.health_check() is True
    finally:
        client.close()


def test_health_check_false_when_nothing_is_listening():
    client = MCPClient(endpoint_url=UNREACHABLE, timeout=2)
    try:
        assert client.health_check() is False
    finally:
        client.close()


def test_health_check_uses_plain_health_url_when_it_answers(monkeypatch):
    """The cheap GET stays the fast path; no handshake when it returns 200."""
    client = MCPClient(endpoint_url=UNREACHABLE, timeout=2)

    class _Response:
        status_code = 200

    monkeypatch.setattr(client._http, "get", lambda *a, **k: _Response())

    def fail_initialize():
        raise AssertionError("handshake must not run when the health URL answers")

    monkeypatch.setattr(client, "initialize", fail_initialize)
    try:
        assert client.health_check() is True
    finally:
        client.close()


def test_ida_health_check_tool_reports_ok_for_jsonrpc_only_server(jsonrpc_only_server: str):
    result = ida_health_check_tool(MCPEndpoint(url=jsonrpc_only_server, timeout=5)).handler()
    assert not result.is_error
    assert "ok" in result.content
