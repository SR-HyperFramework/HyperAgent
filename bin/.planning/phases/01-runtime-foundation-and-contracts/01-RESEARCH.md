# Phase 1: Runtime Foundation and Contracts - Research

**Researched:** 2026-05-06  
**Domain:** Shared runtime contracts for native/dotnet x64dbg integration  
**Confidence:** HIGH

## User Constraints (from CONTEXT.md)

### Locked Decisions
### Adapter Contract Shape
- **D-01:** Use one strict shared adapter interface with identical method names and return schema for both native and dotnet paths.
- **D-02:** Require fully normalized outputs at contract level (same keys and value types across runtimes).
- **D-03:** Represent adapter failures with typed error codes/taxonomy as contract primitives (stable identifiers, not message-only).

### Claude's Discretion
- No additional discretion granted in this session; the above contract decisions are explicitly locked.

### Deferred Ideas (OUT OF SCOPE)
None - discussion stayed within phase scope.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| RTC-01 | Deterministic adapter/runtime selection for native and dotnet analysis paths | Use a shared `AnalysisPlanBuilder` + `ToolAdapterRegistry` contract with explicit mode mapping (`static_only`/`hybrid`/`dynamic_only`) and no implicit branching [VERIFIED: .planning/research/ARCHITECTURE.md] |
| RTC-02 | Actionable failure diagnostics for missing/invalid x64dbg prerequisites | Use typed error taxonomy (`ConfigError`, `DependencyError`, `SessionStartError`, `ProbeTimeoutError`) with remediation text contract [VERIFIED: .planning/research/ARCHITECTURE.md] [VERIFIED: .planning/research/PITFALLS.md] |
| RTC-03 | Consistent state-aware startup/probe/timeout/fallback across native and dotnet flows | Reuse unified lifecycle (`preflight -> start -> collect -> stop`) and state normalization before tool calls [VERIFIED: .planning/research/ARCHITECTURE.md] |

## Summary

Phase 1 should define the shared runtime contract layer only, not full x64dbg feature depth. The immediate planning target is deterministic behavior across `native_agent` and `dotnet_agent`: one adapter interface, one lifecycle model, one normalized output schema, and one failure taxonomy [VERIFIED: .planning/phases/01-runtime-foundation-and-contracts/01-CONTEXT.md] [VERIFIED: .planning/ROADMAP.md].

Current code already contains reusable mechanics for this foundation: native path has startup/probe timeout logic and HTTP readiness polling, while dotnet path has deterministic executable resolution and structured failure returns [VERIFIED: agents/native_agent.py] [VERIFIED: agents/dotnet_agent.py]. Planning should convert these into shared abstractions instead of duplicating behavior per agent.

The highest-risk issues at planning time are state/precondition drift, inconsistent diagnostics wording, and hidden fallback differences between runtimes. Those are solved in Phase 1 by contract-level definitions and acceptance criteria; implementation of full runtime enrichment remains in later phases [VERIFIED: .planning/research/PITFALLS.md] [VERIFIED: .planning/ROADMAP.md].

**Primary recommendation:** Plan Phase 1 as a contract-and-state-machine phase that ships deterministic selection, typed diagnostics schema, and parity lifecycle semantics before any deep x64dbg command integration.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Runtime selection policy | API / Backend | Database / Storage | Selection must be deterministic per request/config and should not depend on client state [VERIFIED: .planning/ROADMAP.md] |
| Adapter contract definition | API / Backend | — | Shared interface and schema are core domain logic owned by agent runtime layer [VERIFIED: .planning/phases/01-runtime-foundation-and-contracts/01-CONTEXT.md] |
| Startup/probe/timeout state handling | API / Backend | OS process boundary | Process lifecycle and readiness checks happen in agent subprocess orchestration [VERIFIED: agents/native_agent.py] |
| Failure taxonomy + remediation payload | API / Backend | — | Actionable diagnostics must be emitted in structured server responses [VERIFIED: .planning/REQUIREMENTS.md] |
| Config defaults for runtime modes/timeouts | API / Backend | Database / Storage | Configuration drives deterministic behavior and fallback semantics [VERIFIED: agents/native_agent.py] [VERIFIED: .planning/research/ARCHITECTURE.md] |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python (CPython) | 3.12.x primary | Runtime for current HyperAgent code | Existing agents are Python-first and already rely on `asyncio` subprocess orchestration [VERIFIED: agents/native_agent.py] |
| `mcp` | 1.27.0 | Python MCP protocol integration | Stable MCP SDK baseline documented in project research for v1 alignment [VERIFIED: .planning/research/STACK.md] |
| x64dbg | 2026.04.20+ | Debugger backend for later phases | Version baseline already selected in stack research for deterministic compatibility policy [VERIFIED: .planning/research/STACK.md] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pyyaml` | existing project dependency | Read config for contract mode/timeouts | Keep additive config behavior and defaults |
| `psutil` | 7.2.2 | Process liveness/cleanup support | Add for richer diagnostics if Phase 1 includes process health checks [VERIFIED: .planning/research/STACK.md] |
| .NET + MCP C# SDK | .NET 10 LTS / MCP C# 1.2.0 | Dotnet-side parity contract reference | Use as target compatibility contract for cross-runtime semantics [VERIFIED: .planning/research/STACK.md] |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Shared strict contract | Separate native/dotnet contracts | Faster short-term coding but creates parity drift and inconsistent diagnostics |
| Typed error codes | Message-only errors | Simpler initially, worse for deterministic remediation and testability |
| Exec APIs (`create_subprocess_exec`) | Shell-based launches | Shell is easier to prototype but increases quoting/portability risk on Windows [VERIFIED: .planning/research/STACK.md] |

**Installation (planning baseline):**
```bash
pip install mcp pyyaml
```

## Architecture Patterns

### System Architecture Diagram
```text
Analysis Request
  -> Orchestrator (route native/dotnet)
    -> AnalysisPlanBuilder (deterministic mode decision)
      -> ToolAdapterRegistry (resolve adapters by capability)
        -> Adapter.preflight()
        -> Adapter.start()
        -> Adapter.collect()
        -> Adapter.stop()
      -> Normalizer (shared output keys/types)
    -> Result Envelope (typed errors + remediation or normalized success)
```

### Recommended Project Structure
```text
agents/
├── contracts/           # Shared adapter interfaces, states, error taxonomy
├── runtime/             # Plan builder, registry, lifecycle orchestration
├── native_agent.py      # Native orchestration using shared contracts
└── dotnet_agent.py      # Dotnet orchestration using shared contracts
```

### Pattern 1: Shared Adapter Lifecycle Contract
**What:** Define one strict interface for native and dotnet runtime adapters.  
**When to use:** For every tool path that participates in runtime selection and diagnostics.  
**Example:**
```python
class RuntimeAdapter(Protocol):
    async def preflight(self, ctx) -> PreflightResult: ...
    async def start(self, ctx) -> SessionHandle: ...
    async def collect(self, ctx, session) -> ArtifactBundle: ...
    async def stop(self, session) -> None: ...
```

### Pattern 2: Deterministic State Machine for Tooling
**What:** Encode lifecycle transitions explicitly (`UNAVAILABLE`, `STARTING`, `READY`, `DEGRADED`, `FAILED`).  
**When to use:** In both agents before any tool-specific analysis step.  
**Example:**
```python
if not preflight.ok:
    return fail(ErrorCode.DEPENDENCY_MISSING, remediation=preflight.fix)
session = await adapter.start(ctx)
if not session.ready:
    return degrade_or_fail(...)
```

### Anti-Patterns to Avoid
- **Runtime-specific branching in orchestrator:** keep complexity inside shared runtime layer, not top-level routing.
- **Message-only failure handling:** always emit stable error code + remediation contract.
- **Inconsistent fallback defaults:** `optional_dynamic` and `strict` semantics must match in both agent paths.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Per-agent bespoke lifecycle logic | Separate start/probe/timeout loops in each agent | Shared lifecycle contract + state machine | Avoids parity drift and duplicate bug fixes |
| Free-form error messaging | Ad hoc string messages | Typed error taxonomy enum + remediation field | Enables deterministic diagnostics and tests |
| Manual path probing scattered across code | Repeated executable/path checks | One preflight diagnostics contract | Consolidates prerequisite checks and user guidance |

**Key insight:** In this phase, reliability comes more from strict contracts and deterministic states than from additional feature depth.

## Common Pitfalls

### Pitfall 1: State Preconditions Drift
**What goes wrong:** Native and dotnet enforce different assumptions for when tool commands are valid.  
**Why it happens:** Lifecycle rules live in separate ad hoc code paths.  
**How to avoid:** Define one shared state model and transition guards in Phase 1 contract artifacts.  
**Warning signs:** Same failure category surfaces different behavior/message across agents [VERIFIED: .planning/research/PITFALLS.md].

### Pitfall 2: Non-actionable Prerequisite Failures
**What goes wrong:** User sees generic failures without remediation.  
**Why it happens:** Missing typed taxonomy and diagnostics payload contract.  
**How to avoid:** Map prerequisite failures to stable error codes and remediation templates.  
**Warning signs:** "works on second try" behavior and manual triage dependence [VERIFIED: .planning/research/PITFALLS.md].

### Pitfall 3: Timeout/Fallback Inconsistency
**What goes wrong:** One path degrades gracefully, the other hard-fails for equivalent conditions.  
**Why it happens:** Different default timeout and fallback logic in separate implementations.  
**How to avoid:** Make mode/fallback contract explicit and shared (`optional_dynamic`, `strict_tooling`).  
**Warning signs:** Regression tests pass on one path and fail on parity checks [VERIFIED: .planning/research/ARCHITECTURE.md].

## Code Examples

Verified existing implementation patterns:

### Native readiness probe loop (reusable for shared contract)
```python
# Source: agents/native_agent.py
async def _wait_for_http_ready(self, host: str, port: int, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if await self._probe_http(host, port, "/sse", expect_sse=True, timeout_s=2.0):
            return True
        if await self._probe_http(host, port, "/", expect_sse=False, timeout_s=2.0):
            return True
        await asyncio.sleep(self.ida_probe_interval_s)
    return False
```

### Dotnet deterministic executable resolution (reusable preflight contract)
```python
# Source: agents/dotnet_agent.py
def _resolve_executable(self, configured: str | None, fallbacks: list[str]) -> str | None:
    # config -> PATH -> repo-relative fallback search
    ...
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Agent-specific implicit behavior | Shared explicit contract and state machine | Current roadmap reinitialization | Deterministic parity, easier verification [VERIFIED: .planning/ROADMAP.md] |
| String-based ad hoc failures | Typed error taxonomy + remediation payload | Current architecture direction | Better diagnostics and testability [VERIFIED: .planning/research/ARCHITECTURE.md] |
| Feature-first integration attempts | Foundation-first phase sequencing | Current roadmap phase ordering | Reduces regressions in later x64dbg phases [VERIFIED: .planning/ROADMAP.md] |

**Deprecated/outdated:**
- Separate contract semantics per runtime path: replaced by locked shared contract decisions in Phase 1 [VERIFIED: .planning/phases/01-runtime-foundation-and-contracts/01-CONTEXT.md].

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `pip install mcp pyyaml` is sufficient in this repo environment without additional pinning | Standard Stack | Medium - planner may need lockfile/bootstrap task |
| A2 | .NET MCP SDK references are planning-level only and not required for immediate Phase 1 code changes | Standard Stack | Low - Phase 1 could still proceed in Python-first contracts |

## Open Questions

1. **Should Phase 1 include a standalone diagnostics CLI endpoint, or only internal contract + schema?**
   - What we know: RTC-02 requires actionable diagnostics semantics.
   - What's unclear: whether command surface delivery is required in this phase or Phase 4 only.
   - Recommendation: lock this in planning to avoid scope bleed.

2. **What is the canonical location for shared contract modules?**
   - What we know: current code keeps logic directly in `agents/`.
   - What's unclear: whether introducing `agents/contracts/` is acceptable now.
   - Recommendation: define file layout in PLAN.md before implementation tasks.

## Validation Architecture

Skipped: `workflow.nyquist_validation` is explicitly set to `false` in `.planning/config.json` [VERIFIED: .planning/config.json].

## Security Domain

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | N/A in this phase scope |
| V3 Session Management | no | N/A in this phase scope |
| V4 Access Control | no | N/A in this phase scope |
| V5 Input Validation | yes | Validate config values and runtime mode enums before execution |
| V6 Cryptography | no | N/A in this phase scope |

### Known Threat Patterns for this stack
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Command injection via process launch | Tampering | Use explicit exec APIs with argument arrays, not shell strings [VERIFIED: .planning/research/STACK.md] |
| Information leakage in diagnostics | Information Disclosure | Emit curated remediation payloads, avoid raw secret/path dumps |
| Denial of service via unbounded startup/probe waits | Denial of Service | Enforce timeout budget contract and deterministic fallback behavior [VERIFIED: agents/native_agent.py] |

## Sources

### Primary (HIGH confidence)
- [VERIFIED: `.planning/phases/01-runtime-foundation-and-contracts/01-CONTEXT.md`] - locked contract decisions and scope boundaries
- [VERIFIED: `.planning/REQUIREMENTS.md`] - RTC-01/02/03 definitions
- [VERIFIED: `.planning/ROADMAP.md`] - phase goal/success criteria
- [VERIFIED: `agents/native_agent.py`] - existing readiness/timeout orchestration behavior
- [VERIFIED: `agents/dotnet_agent.py`] - deterministic executable resolution and error handling patterns
- [VERIFIED: `.planning/research/ARCHITECTURE.md`] - adapter-first architecture and error taxonomy
- [VERIFIED: `.planning/research/PITFALLS.md`] - domain failure modes and mitigations
- [VERIFIED: `.planning/research/STACK.md`] - runtime and tooling baseline versions

### Secondary (MEDIUM confidence)
- [CITED: https://help.x64dbg.com/en/latest/index.html] - debugger capability context inherited in project research docs
- [CITED: https://docs.python.org/3/library/asyncio-subprocess.html] - subprocess supervision guidance reflected by current patterns

### Tertiary (LOW confidence)
- None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - stack versions and direction already documented in project research corpus.
- Architecture: HIGH - phase constraints and locked decisions are explicit.
- Pitfalls: HIGH - major failure modes documented and directly relevant to RTC-01..03.

**Research date:** 2026-05-06  
**Valid until:** 2026-06-05
