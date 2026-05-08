# Technology Stack

**Project:** x64dbg-mcp integration for HyperAgent
**Researched:** 2026-05-06
**Scope:** MCP workflow support for `agents/native_agent.py` and the .NET agent path on Windows

## Recommended Stack (v1)

### Runtime and Core SDKs

| Layer | Technology | Recommended Version | Confidence | Why |
|---|---|---:|---|---|
| Python runtime | CPython | 3.12.x (primary), 3.13.x (validated secondary) | HIGH | Stable production base with mature ecosystem and no dependency on experimental free-threaded builds. |
| Python MCP SDK | `mcp` (Model Context Protocol Python SDK) | 1.27.0 | HIGH | Official SDK, v1.x branch is documented as current stable. |
| .NET runtime | .NET | 10 LTS (preferred), 8 LTS only for compatibility bridges | HIGH | .NET 10 is active LTS through 2028; .NET 8 support ends 2026-11-10. |
| .NET MCP SDK | `ModelContextProtocol` / `ModelContextProtocol.Core` | 1.2.0 | HIGH | Official C# SDK release; supports modern transport defaults and active maintenance. |
| Debugger backend | x64dbg | 2026.04.20 or newer | MEDIUM | Current upstream release line; required for modern x64dbg command/plugin behavior. |

### Process Invocation and Supervision

| Concern | Python Path | .NET Path | Confidence | v1 Guidance |
|---|---|---|---|---|
| Process spawn | `asyncio.create_subprocess_exec(...)` (not shell) | `ProcessStartInfo` + `UseShellExecute=false` + redirected streams | HIGH | Avoid shell quoting bugs and injection risk; pass args explicitly. |
| Timeout/cancel | `asyncio.wait_for(...)` around startup/probe and bounded `communicate()` | `CancellationToken` + bounded waits + kill-on-timeout policy | HIGH | Enforce deterministic startup/probe/teardown deadlines. |
| Health supervision | `psutil` 7.2.2 for PID liveness + child cleanup | `Process.HasExited`, exit code, and stream drains | MEDIUM | Add lightweight process + endpoint checks before analysis work. |
| Readiness probe | MCP handshake probe (`tools/list` or equivalent) after process up | Same handshake probe contract | MEDIUM | Treat "spawned but not responding" as not ready. |

### Packaging and Reproducibility

| Area | Recommendation | Confidence | Why |
|---|---|---|---|
| Python dependency management | `uv` 0.11.x + lockfile-driven installs | HIGH | Official MCP Python SDK docs recommend `uv`; fast and deterministic. |
| Python project metadata | `pyproject.toml` + pinned lower/upper bounds for MCP + ops libs | HIGH | Clear, reproducible environments across maintainers. |
| .NET packaging | `dotnet publish` for `win-x64`; use single-file only where tested with debugger/toolchain paths | HIGH | Microsoft-supported deployment path; avoid accidental runtime mismatch. |
| Distribution strategy | Separate Python and .NET artifacts, coordinated by HyperAgent adapter config | MEDIUM | Reduces coupling and simplifies rollback by path. |

## Supporting Libraries (v1-appropriate)

| Library | Version | Purpose | When to Use | Confidence |
|---|---:|---|---|---|
| `mcp` (Python) | 1.27.0 | MCP client/server protocol implementation | Python-side MCP transport and capability handling | HIGH |
| `ModelContextProtocol` (NuGet) | 1.2.0 | MCP integration in .NET path | .NET-side MCP transport/client-server wiring | HIGH |
| `psutil` | 7.2.2 | Process liveness and cleanup helpers on Windows | Health checks, orphan cleanup, telemetry snapshots | MEDIUM |

## Windows Constraints (Non-Negotiable for v1)

- Target **Windows x64 first**; do not scope Linux/macOS parity in v1 for x64dbg workflows.
- Keep debugger bitness explicit: use correct debugger path/tool mode for target binary architecture.
- Always use absolute executable paths in config (avoid PATH-dependent behavior in service/CI shells).
- Run under user contexts that can launch desktop-bound debugger processes; service-session assumptions often break debugger UI/IPC workflows.
- Reserve deterministic probe ports/ranges and fail with actionable diagnostics on collisions.

## What NOT to Use in v1

| Avoid in v1 | Why Not | Use Instead |
|---|---|---|
| MCP Python SDK v2 pre-alpha (`main` branch docs) | Not stable; API churn risk | MCP Python SDK v1.x (`mcp==1.27.0`) |
| Legacy SSE as primary transport in .NET MCP path | New C# SDK defaults moved away; higher operational risk | Streamable HTTP / modern default transport |
| Shell-based process launch (`create_subprocess_shell`, `cmd /c ...`) as default orchestration path | Injection and quoting fragility under Windows | Explicit exec APIs with argument lists |
| Python free-threaded experimental runtime assumptions | Ecosystem/plugin compatibility uncertainty | Standard CPython builds (3.12/3.13) |
| Full `pythonnet` in-process CLR embedding for core workflow | Raises complexity and fault-domain coupling early | Out-of-process MCP/process boundary between Python and .NET |
| Building v1 around .NET Framework 4.x | Legacy constraints and reduced future runway | .NET 10 LTS (or .NET 8 compatibility bridge only) |

## Implementation Baseline for HyperAgent

1. Keep orchestrator logic additive; place runtime-specific execution in adapters used by `native_agent` and .NET agent paths.
2. Use one process policy contract across both paths:
   - spawn -> readiness probe -> bounded work -> teardown
3. Standardize health checks:
   - binary/path check
   - version check
   - spawn + MCP handshake
   - cleanup verification
4. Package separately but document a single verification command set per runtime path.

## Confidence Notes

| Topic | Confidence | Notes |
|---|---|---|
| MCP SDK versions and stability channel | HIGH | Directly verified from official MCP SDK repos/releases. |
| .NET version recommendation | HIGH | Verified from Microsoft official support policy (LTS timelines). |
| Python package/project tooling (`uv`) | HIGH | Explicitly recommended in MCP Python SDK docs. |
| x64dbg release pin | MEDIUM | Verified current release stream, but integration-specific plugin compatibility still needs phase validation. |
| Health-check library detail (`psutil`) | MEDIUM | Strong ecosystem fit; exact pin should be revalidated during implementation freeze. |

## Sources

- MCP Python SDK README (stable v1.x note + uv recommendation): https://raw.githubusercontent.com/modelcontextprotocol/python-sdk/main/README.md
- MCP Python SDK latest release (`v1.27.0`): https://api.github.com/repos/modelcontextprotocol/python-sdk/releases/latest
- MCP C# SDK README + packages: https://raw.githubusercontent.com/modelcontextprotocol/csharp-sdk/main/README.md
- MCP C# SDK latest release (`v1.2.0`): https://api.github.com/repos/modelcontextprotocol/csharp-sdk/releases/latest
- .NET official support policy (last updated 2026-04-22): https://dotnet.microsoft.com/en-us/platform/support/policy/
- .NET single-file deployment guidance (last updated 2026-03-25): https://learn.microsoft.com/en-us/dotnet/core/deploying/single-file/overview
- Python subprocess docs: https://docs.python.org/3/library/subprocess.html
- Python asyncio subprocess docs: https://docs.python.org/3/library/asyncio-subprocess.html
- .NET `ProcessStartInfo` docs: https://learn.microsoft.com/en-us/dotnet/api/system.diagnostics.processstartinfo?view=net-9.0
- x64dbg documentation index: https://help.x64dbg.com/en/latest/index.html
- x64dbg releases: https://github.com/x64dbg/x64dbg/releases
