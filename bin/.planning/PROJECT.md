# x64dbg-mcp Native + DotNet Integration

## What This Is

This project adds `x64dbg-mcp` support into HyperAgent for both the native analysis path and the .NET analysis path. v1 focuses on additive integration: keep existing behavior intact, then enable deterministic debugger-backed enrichment when explicitly configured. This is for internal maintainers who need reproducible debugging workflows with clear diagnostics on Windows.

## Core Value

Run x64dbg-backed MCP workflows reliably from both `native_agent` and `dotnet_agent` without breaking current HyperAgent analysis.

## Requirements

### Validated

- ✓ HyperAgent accepts binaries and routes analysis through type-specific agents (existing)
- ✓ HyperAgent supports MCP-based IDA integration and AI-assisted analysis (existing)
- ✓ HyperAgent exposes both CLI and API entry points for analysis workflows (existing)

### Active

- [ ] v1 supports x64dbg-mcp execution path in `native_agent`
- [ ] v1 supports x64dbg-mcp execution path in `dotnet_agent`
- [ ] Shared adapter contracts and runtime state handling are deterministic across both paths
- [ ] Diagnostics report missing x64dbg/plugin/MCP prerequisites with actionable remediation
- [ ] Docs include setup, health checks, and parity verification for native and dotnet flows

### Out of Scope

- GUI configuration workflow — CLI-first maintainer workflow is sufficient for v1
- Automatic installation/repair for external tooling — too broad for initial release
- Rewriting HyperAgent orchestration/routing architecture — integration must remain additive

## Context

HyperAgent already routes binaries to type-specific agents and has MCP integration patterns for IDA/dnSpy-oriented workflows. Research in `.planning/research/` highlights an adapter-first architecture, deterministic health checks, and strict state preconditions as the safest path for x64dbg integration. The highest-risk areas are debugger architecture mismatch, deadlocks from unsafe command sequencing, and environment drift (ports, dependencies, DLL/plugin paths).

## Constraints

- **Compatibility**: Preserve existing native and dotnet baseline behavior when x64dbg is unavailable
- **Environment**: Windows-first execution context with x64dbg architecture/plugin alignment requirements
- **Reliability**: Deterministic process lifecycle, timeouts, and error taxonomy across both agent paths
- **Scope**: v1 must include both `native_agent` and `dotnet_agent`; no broad pipeline rewrite

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Implement x64dbg integration in both native and dotnet paths in v1 | Keeps behavior consistent and avoids split capability between agent types | — Pending |
| Use adapter-based additive architecture instead of orchestrator rewrite | Reduces regression risk and leverages existing integration patterns | — Pending |
| Standardize deterministic health checks and diagnostic taxonomy | Makes failures actionable and easier to operate/verify | — Pending |
| Default to graceful degradation with optional strict mode | Preserves usability when dynamic tooling is unavailable | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? -> Move to Out of Scope with reason
2. Requirements validated? -> Move to Validated with phase reference
3. New requirements emerged? -> Add to Active
4. Decisions to log? -> Add to Key Decisions
5. "What This Is" still accurate? -> Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-05-06 after reinitialization*
