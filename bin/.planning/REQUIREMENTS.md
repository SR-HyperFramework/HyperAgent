# Requirements: x64dbg-mcp Native + DotNet Integration

**Defined:** 2026-05-06
**Core Value:** Run x64dbg-backed MCP workflows reliably from both `native_agent` and `dotnet_agent` without breaking current HyperAgent analysis.

## v1 Requirements

Requirements for initial release. Each maps to exactly one roadmap phase.

### Shared Runtime Contracts

- [ ] **RTC-01**: User can run HyperAgent and have deterministic adapter/runtime selection for native and dotnet analysis paths
- [ ] **RTC-02**: User receives actionable failure diagnostics when x64dbg-mcp prerequisites are missing or invalid
- [ ] **RTC-03**: User gets consistent state-aware behavior (startup/probe/timeout/fallback) across native and dotnet flows

### Native Agent x64dbg Integration

- [ ] **NAT-01**: User can run `native_agent` with x64dbg-mcp enrichment when enabled by configuration
- [ ] **NAT-02**: User gets deterministic native health check output (ready/fail + remediation) for x64dbg path
- [ ] **NAT-03**: User still receives baseline native analysis when x64dbg is unavailable and strict mode is disabled

### DotNet Agent x64dbg Integration

- [ ] **DOT-01**: User can run `dotnet_agent` with x64dbg-mcp enrichment layered on dnSpy/static baseline
- [ ] **DOT-02**: User gets deterministic dotnet health check output (ready/fail + remediation) for x64dbg path
- [ ] **DOT-03**: User still receives baseline dotnet analysis when x64dbg is unavailable and strict mode is disabled

### Diagnostics, Docs, and Parity

- [ ] **DOC-01**: User can run a diagnostics command that identifies x64dbg/plugin/MCP/process prerequisites for each agent path
- [ ] **DOC-02**: User can follow setup/verification docs for native and dotnet x64dbg integration without hidden prerequisites
- [ ] **DOC-03**: User can run end-to-end sample analyses in native and dotnet flows and receive parity-aligned output structure

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Advanced Runtime Expansion

- **ADV-01**: User can run x64dbg integration with strict semantic parity gates in CI across expanded sample corpus
- **ADV-02**: User can onboard additional debugger/runtime adapters through a generalized adapter plugin framework

## Out of Scope

| Feature | Reason |
|---------|--------|
| Broad multi-CLI integration in this phase | This reinitialization targets native and dotnet agent integration scope |
| GUI setup/configuration tool | Internal users can operate via CLI-first workflow |
| Full tool auto-installation manager | Too broad for v1 |
| Core analysis pipeline rewrite | Goal is additive integration, not architecture replacement |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| RTC-01 | Phase 1 | Pending |
| RTC-02 | Phase 1 | Pending |
| RTC-03 | Phase 1 | Pending |
| NAT-01 | Phase 2 | Pending |
| NAT-02 | Phase 2 | Pending |
| NAT-03 | Phase 2 | Pending |
| DOT-01 | Phase 3 | Pending |
| DOT-02 | Phase 3 | Pending |
| DOT-03 | Phase 3 | Pending |
| DOC-01 | Phase 4 | Pending |
| DOC-02 | Phase 4 | Pending |
| DOC-03 | Phase 4 | Pending |

**Coverage:**
- v1 requirements: 12 total
- Mapped to phases: 12
- Unmapped: 0

---
*Requirements defined: 2026-05-06*
*Last updated: 2026-05-06 after reinitialization*
