# Legacy IDA MCP Backup

This directory stores the superseded host-side IDA MCP startup flow that previously opened files via `uv run idalib-mcp`.

Files:
- `native_agent_ida_mcp_legacy.py` — previous `NativeAgent` implementation with subprocess startup, HTTP probing, and cleanup.
- `native_agent_legacy_tests.py` — previous integration tests for the legacy startup/probe flow.

These files are reference backups only and are not wired into the active runtime path.
