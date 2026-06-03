# Roadmap: x64dbg-mcp Native + DotNet Integration

## Overview

This roadmap delivers additive x64dbg-mcp integration for both `native_agent` and `dotnet_agent` with deterministic contracts, diagnostics, and parity verification.

## Phase Summary

| Phase | Name | Goal | Requirements |
|------:|------|------|--------------|
| 1 | Runtime Foundation and Contracts | Establish shared adapter contracts, state handling, and deterministic failure semantics | RTC-01, RTC-02, RTC-03 |
| 2 | Native Agent x64dbg Path | Deliver native x64dbg integration with deterministic health check and graceful fallback | NAT-01, NAT-02, NAT-03 |
| 3 | DotNet Agent x64dbg Path | Deliver dotnet x64dbg enrichment with parity-aligned behavior and graceful fallback | DOT-01, DOT-02, DOT-03 |
| 4 | Diagnostics and Verification | Add unified diagnostics, docs, and parity validation across both paths | DOC-01, DOC-02, DOC-03 |

## Phase Details

### Phase 1: Runtime Foundation and Contracts

**Goal:** Native and dotnet flows share deterministic adapter contracts, lifecycle behavior, and actionable failure semantics.

**Requirements:** RTC-01, RTC-02, RTC-03

**Success Criteria:**
1. Adapter/runtime selection behaves deterministically for native and dotnet paths under supported configurations.
2. Failure taxonomy maps prerequisite errors to explicit remediation guidance.
3. State-aware startup/probe/timeout/fallback behavior is consistent across both paths.

### Phase 2: Native Agent x64dbg Path

**Goal:** `native_agent` supports x64dbg-mcp enrichment without breaking baseline native analysis behavior.

**Requirements:** NAT-01, NAT-02, NAT-03

**Success Criteria:**
1. Native x64dbg path executes successfully when prerequisites are present.
2. Native health check returns deterministic ready/fail status with actionable remediation text.
3. Baseline native analysis still succeeds when x64dbg is unavailable and strict mode is disabled.

### Phase 3: DotNet Agent x64dbg Path

**Goal:** `dotnet_agent` supports x64dbg-mcp enrichment layered on current static/decompile baseline with parity-aligned behavior.

**Requirements:** DOT-01, DOT-02, DOT-03

**Success Criteria:**
1. Dotnet x64dbg enrichment executes successfully with compatible runtime configuration.
2. Dotnet health check returns deterministic ready/fail status with actionable remediation text.
3. Baseline dotnet analysis remains available when x64dbg path is unavailable and strict mode is disabled.

### Phase 4: Diagnostics and Verification

**Goal:** Reduce operator friction with unified diagnostics, complete setup docs, and parity verification across both agent paths.

**Requirements:** DOC-01, DOC-02, DOC-03

**Success Criteria:**
1. Diagnostics identify missing x64dbg/plugin/MCP/process prerequisites and map each to specific fixes.
2. Native and dotnet setup guides run start-to-finish without undocumented steps.
3. End-to-end native and dotnet samples pass with parity-aligned output structure and behavior.

## Notes

- Scope intentionally excludes broad multi-CLI expansion in this reinitialized phase set.
- Any new v1 requirement must be added to REQUIREMENTS.md and mapped here before execution.

---
*Last updated: 2026-05-06 after reinitialization*
