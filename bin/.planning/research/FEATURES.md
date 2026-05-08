# Feature Landscape

**Domain:** x64dbg-mcp integration for HyperAgent native and .NET agent paths
**Researched:** 2026-05-06

## Table Stakes

Features maintainers will expect for a reliable dual-path MCP integration. Missing any of these makes the integration feel brittle or incomplete.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Runtime detection for active CLI path (Claude Code vs Codex CLI) | Multi-CLI support is the core v1 promise; wrong runtime routing breaks workflows | Med | Must produce deterministic routing, explicit "unknown runtime" handling, and next-step guidance |
| Deterministic health checks per runtime path | Maintainers need a yes/no signal before running long analysis | Med | Health checks should validate MCP reachability and expected endpoint readiness using stable probes and timeout policy |
| Adapter boundary between core analysis and CLI-specific integration | Additive integration requires preserving existing analysis behavior | High | Core analysis APIs should remain runtime-agnostic; CLI adapters own process orchestration and protocol details |
| Unified diagnostics command with actionable remediations | Setup friction is highest risk in MCP workflows with external tools | Med | Diagnostics should map each failed prerequisite to a single fix step (missing binary, env var, blocked port, bad config) |
| Parity contract across native and .NET agent paths | v1 value is consistent behavior regardless of agent type | High | Output structure, error taxonomy, and verification UX must match even if internal tooling differs |
| Structured error surfaces for startup/probe failures | MCP startup can fail in many ways; opaque failures waste debugging time | Low | Standardize error codes/messages for timeout, process spawn failure, path resolution failure, and protocol mismatch |

## Differentiators

Features that are not strictly required for MVP correctness, but materially improve maintainability, trust, and long-term extensibility.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Cross-path parity report ("native vs .NET", "Claude vs Codex") | Makes regressions visible early and enforces behavior symmetry as a first-class quality gate | Med | Compare response shape, key diagnostics, and error categories, not brittle full-text output |
| Deterministic readiness state machine (boot -> probe -> ready/fail) | Converts flaky startup behavior into observable transitions with reliable retries/timeouts | Med | Use consistent phase markers and timing metrics so logs are debuggable and tests are stable |
| Adapter conformance tests for runtime plugins | Prevents hidden divergence when one adapter evolves faster than another | Med | Define required adapter interface and run the same contract tests for each adapter |
| Diagnostics fingerprint bundles | Speeds incident triage by capturing minimal but sufficient context | Low | Include runtime detected, tool versions, command paths, probe timings, and failing step identifier |
| Capability matrix for runtime x agent combinations | Clarifies what is supported now versus deferred | Low | Publish explicit support status for native/ .NET x Claude/Codex to avoid implicit expectations |

## Anti-Features

Capabilities that should explicitly NOT be built in this integration phase because they increase risk, blur boundaries, or conflict with v1 scope.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Runtime-specific logic leaking into core analysis agents | Violates additive integration principle and creates coupled regressions | Keep runtime details in adapters; keep core agent analyze flows runtime-agnostic |
| Heuristic-only runtime detection without explicit fallback | Creates nondeterministic behavior and hard-to-reproduce bugs | Require deterministic detection rules plus explicit "unknown runtime" error path |
| Health checks that execute full analysis workloads | Slow checks increase friction and create false negatives under load | Keep checks lightweight and protocol-focused (spawn, probe, minimal handshake) |
| Divergent output schema per runtime/agent path | Breaks parity validation and downstream automation | Define one canonical output contract and adapt internals to fit it |
| Auto-installing/debugging external dependencies in v1 | Expands scope and operational risk beyond integration goals | Provide precise diagnostics and manual remediation commands in docs |
| Silent fallbacks between adapters (e.g., Codex path silently using Claude adapter) | Hides misconfiguration and creates confusing behavior | Fail fast with explicit adapter mismatch error and correction guidance |

## Feature Dependencies

```text
Runtime detection -> Adapter selection -> Deterministic health check -> Analysis execution
Adapter boundary definition -> Adapter conformance tests -> Parity behavior validation
Structured diagnostics -> Actionable setup docs -> Faster operator recovery
Canonical output/error contract -> Native path parity + .NET path parity -> End-to-end trust
```

## MVP Recommendation

Prioritize:
1. Runtime detection with explicit unknown-runtime failure path
2. Deterministic health checks for both supported CLI paths
3. Strict adapter boundaries with canonical diagnostics/error contract

Then add:
4. Parity validation across native and .NET agent paths using shared contract tests

Defer:
- Diagnostics fingerprint bundles and richer parity reports: valuable, but secondary to getting deterministic correctness and boundary discipline first.

## Sources

- Internal project requirements and roadmap (`.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`) — HIGH confidence for scope/priorities
- Current agent implementations (`agents/native_agent.py`, `agents/dotnet_agent.py`) — HIGH confidence for existing behavior and integration constraints
