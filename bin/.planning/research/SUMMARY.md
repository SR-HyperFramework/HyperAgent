# Research Summary

**Project:** HyperAgent v1 x64dbg-mcp integration  
**Scope:** Add x64dbg-mcp support for both `NativeAgent` and `.NET` agent paths without breaking existing analysis behavior  
**Synthesized:** 2026-05-06

## Executive Summary

HyperAgent v1 should deliver a Windows-first, additive integration of `x64dbg-mcp` as an optional dynamic-analysis capability layered beneath existing agent flows. The highest-leverage direction is an adapter-based design inside `NativeAgent` and `DotNetAgent`, not an orchestrator rewrite. This preserves current routing, response envelope, and baseline static behavior while enabling deterministic runtime tooling when explicitly configured.

The recommended technical baseline is stable MCP SDKs (`mcp==1.27.0` for Python and `ModelContextProtocol 1.2.0` for .NET), explicit process execution APIs (no shell orchestration), and bounded startup/probe/collection timeouts. Reliability depends on shared contracts across native and .NET paths: same adapter lifecycle, same diagnostics taxonomy, and same fallback semantics.

The key risks are operational, not conceptual: x64dbg architecture/plugin mismatch (`.dp32`/`.dp64`), debugger-thread deadlocks from unsafe command chaining, runtime state-precondition violations, and environment-specific dependency/port failures. v1 should mitigate these through strict preflight diagnostics, deterministic state-machine checks, explicit config-driven behavior, and parity tests across both agent paths.

## Key Findings

### Stack Choices (v1)

- **Python runtime:** `CPython 3.12.x` primary (`3.13.x` validated secondary) for stability.
- **Python MCP SDK:** `mcp==1.27.0` (stable v1 channel; avoid v2 pre-alpha).
- **.NET runtime:** `.NET 10 LTS` preferred; `.NET 8 LTS` compatibility bridge only.
- **.NET MCP SDK:** `ModelContextProtocol` / `ModelContextProtocol.Core` `1.2.0`.
- **Debugger backend:** `x64dbg 2026.04.20+` with explicit arch alignment.
- **Process policy:** use `asyncio.create_subprocess_exec` / `ProcessStartInfo` + redirected streams, never shell-based launch.
- **Packaging:** reproducible Python (`uv` + lockfile) and separate Python/.NET artifacts coordinated via adapter config.

### Table Stakes (must-have for v1)

- Deterministic runtime detection and explicit unknown-runtime failure path.
- Shared adapter boundary that keeps core analysis runtime-agnostic.
- Deterministic health checks per runtime path (spawn -> probe -> ready/fail).
- Canonical diagnostics and error taxonomy (spawn/probe/path/timeout/protocol mismatch).
- Parity contract across native and .NET outputs and remediation guidance.

### Architecture Principles

- Keep `HyperAgentOrchestrator` routing unchanged; add integration inside agents.
- Introduce `AnalysisPlanBuilder` + `ToolAdapterRegistry` for deterministic execution planning.
- Wrap existing IDA/dnSpy behavior behind adapter interfaces before adding x64dbg.
- Use optional dynamic enrichment by default (graceful degrade), strict mode opt-in for fail-fast.
- Normalize static + dynamic artifacts into shared bundle before summarization.
- Enforce additive config: no key changes required for existing installs.

### Top Pitfalls and Mitigations

1. **Plugin architecture mismatch (`.dp64`/`.dp32`)**  
   Mitigate with startup arch checks, plugin-load assertions, and targeted remediation output.
2. **Debugger-thread deadlocks from sync command chaining**  
   Mitigate with thread-safe async command model and explicit pause-state synchronization probes.
3. **State preconditions ignored (`paused/running/no-session`)**  
   Mitigate via shared state-aware command router and automatic state normalization.
4. **Dependency and DLL-path resolution drift across environments**  
   Mitigate by packaging deterministic local dependencies and fingerprinting supported x64dbg builds.
5. **Port/process lifecycle conflicts and timeout underestimation**  
   Mitigate via configurable port ranges, PID-aware diagnostics, and operation-tiered timeout profiles.

## Implications for Requirements and Roadmap

### Recommended Phase Structure

1. **Runtime Foundation and Contracts**  
   Deliver shared adapter interface, plan builder/registry, state machine, config contract (timeouts/ports/modes), and canonical error taxonomy.  
   **Why first:** every later feature depends on deterministic selection, state handling, and shared contracts.

2. **Native Path x64dbg Integration (Claude/Codex compatible)**  
   Deliver `X64DbgAdapter` for native workflow with preflight checks, bounded probes, fallback behavior, and unchanged response envelope.  
   **Why second:** highest risk concentration (plugin load, debugger threading, precondition handling) and earliest validation of dynamic path.

3. **.NET Path Dynamic Enrichment + Parity Enforcement**  
   Deliver dotnet hybrid flow (dnSpy baseline + x64dbg runtime enrichment), single-file bundle detection/fallbacks, and response-shape parity tests.  
   **Why third:** leverages proven adapter mechanics and targets known .NET-specific edge cases.

4. **Diagnostics, Verification, and Hardening Gate**  
   Deliver unified health/diagnostics command, clean-room setup validation, parity report, regression gates, and operator-facing remediation docs.  
   **Why fourth:** converts implementation into production-grade maintainability and low-triage operations.

### Research Flags

- **Needs deeper phase research:**  
  - Native x64dbg command sequencing and deadlock-safe probe design.  
  - .NET single-file bundle handling strategy and confidence annotation policy.  
  - Port allocation and multi-session limits under realistic concurrent usage.
- **Well-documented / lower-research risk:**  
  - MCP SDK version baselines and transport defaults.  
  - Additive adapter architecture and non-breaking orchestration approach.  
  - Deterministic diagnostic taxonomy and fallback-mode behavior.

## Confidence Assessment

| Area | Confidence | Notes |
|---|---|---|
| Stack | HIGH | Versions and support windows are clear and current from official SDK/runtime sources. |
| Features | HIGH | Strong alignment with project v1 goals: deterministic dual-path MCP integration and additive behavior. |
| Architecture | HIGH | Clear incremental migration path with strong preservation of existing contracts. |
| Pitfalls | MEDIUM-HIGH | Core failure modes are well identified; some plugin/runtime edge behavior still needs implementation-time validation. |

**Overall confidence:** **HIGH** for roadmap direction, **MEDIUM-HIGH** for execution complexity in debugger behavior and environment portability.

## Gaps to Address During Planning

- Decide strict default for `optional_dynamic` vs stricter policy by environment/profile.
- Define exact parity assertions (schema-only vs semantic baseline checks) and CI gates.
- Specify minimum deterministic dynamic probe set for v1 to avoid scope creep.
- Finalize supported x64dbg snapshot/version policy and compatibility test matrix.

## Source Inputs

- `.planning/research/STACK.md`
- `.planning/research/FEATURES.md`
- `.planning/research/ARCHITECTURE.md`
- `.planning/research/PITFALLS.md`
