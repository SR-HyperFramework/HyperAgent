"""Lifecycle management for locally-spawned MCP servers (currently: idalib-mcp).

x64dbg-mcp runs inside the guest VM and is started independently; idalib-mcp
runs on the host and can simply be launched as a subprocess when the
configured endpoint isn't already reachable.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import time
from urllib.parse import urlparse

from ..config import HyperAgentConfig
from ..tools.mcp_client import MCPClient

logger = logging.getLogger(__name__)

_STARTUP_POLL_INTERVAL = 0.5
_STARTUP_TIMEOUT = 20


def ensure_idalib_mcp(config: HyperAgentConfig) -> subprocess.Popen | None:
    """Start ``idalib-mcp`` if the configured IDA MCP endpoint isn't reachable.

    Returns the ``Popen`` handle if this call started the process (so the
    caller can stop it later), or ``None`` if a server was already reachable,
    the ``idalib-mcp`` executable isn't installed, or it failed to come up in
    time. Never raises: an unreachable IDA MCP server degrades to that tool
    source being empty, same as before this function existed.
    """
    endpoint = config.ida_mcp
    probe = MCPClient(endpoint_url=endpoint.url, timeout=5)
    try:
        if probe.health_check():
            logger.info("IDA MCP already reachable at %s; not spawning idalib-mcp.", endpoint.url)
            return None
    finally:
        probe.close()

    exe = shutil.which("idalib-mcp") or shutil.which("idalib-mcp.exe")
    if not exe:
        logger.warning("idalib-mcp executable not found on PATH; IDA tools will be unavailable.")
        return None

    parsed = urlparse(endpoint.url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 13337

    logger.info("Starting idalib-mcp on %s:%d", host, port)
    proc = subprocess.Popen(
        [exe, "--host", host, "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )

    client = MCPClient(endpoint_url=endpoint.url, timeout=5)
    try:
        deadline = time.monotonic() + _STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                logger.warning("idalib-mcp exited early (code %s) during startup.", proc.returncode)
                return None
            if client.health_check():
                logger.info("idalib-mcp is up at %s", endpoint.url)
                return proc
            time.sleep(_STARTUP_POLL_INTERVAL)
    finally:
        client.close()

    logger.warning("idalib-mcp did not become healthy within %ds; leaving it running.", _STARTUP_TIMEOUT)
    return proc


def stop_idalib_mcp(proc: subprocess.Popen | None) -> None:
    """Terminate an idalib-mcp process previously started by ``ensure_idalib_mcp``."""
    if proc is None or proc.poll() is not None:
        return
    logger.info("Stopping idalib-mcp (pid %d)", proc.pid)
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        logger.warning("idalib-mcp did not exit cleanly; killing.")
        proc.kill()
