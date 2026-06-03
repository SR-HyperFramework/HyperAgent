# Phase 1: Runtime Foundation and Contracts - Context

**Gathered:** 2026-05-06
**Status:** Ready for planning

<domain>
## Phase Boundary

Define the shared runtime contract foundation for x64dbg-mcp integration so both `native_agent` and `dotnet_agent` can implement deterministic adapter behavior, error semantics, and readiness/failure handling.

</domain>

<decisions>
## Implementation Decisions

### Adapter Contract Shape
- **D-01:** Use one strict shared adapter interface with identical method names and return schema for both native and dotnet paths.
- **D-02:** Require fully normalized outputs at contract level (same keys and value types across runtimes).
- **D-03:** Represent adapter failures with typed error codes/taxonomy as contract primitives (stable identifiers, not message-only).

### Claude's Discretion
- No additional discretion granted in this session; the above contract decisions are explicitly locked.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase and requirement contracts
- `.planning/ROADMAP.md` — Phase 1 goal, requirements mapping, and success criteria.
- `.planning/REQUIREMENTS.md` — `RTC-01`, `RTC-02`, `RTC-03` definitions for deterministic runtime behavior.
- `.planning/PROJECT.md` — Core value, constraints, and additive integration boundaries.

### Research constraints and implementation guidance
- `.planning/research/SUMMARY.md` — v1 architecture direction, top risks, and roadmap implications.
- `.planning/research/ARCHITECTURE.md` — adapter-first structure and integration sequencing.
- `.planning/research/FEATURES.md` — table-stakes for deterministic behavior and parity.
- `.planning/research/PITFALLS.md` — failure modes that influence runtime/error contract design.
- `.planning/research/STACK.md` — runtime/tooling baselines that affect contract assumptions.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `agents/native_agent.py`: `_wait_for_http_ready`, `_probe_http` — existing readiness/polling logic that can be adapted into shared contract semantics.
- `agents/native_agent.py`: `filter_goose_report` — existing output post-processing that informs normalized result schema boundaries.
- `agents/dotnet_agent.py`: `_resolve_executable` — robust tool resolution pattern reusable for runtime prerequisite checks.
- `agents/dotnet_agent.py`: `_pick_interesting_cs_files` and `run_dnspy_decompile` — examples of deterministic preprocessing and failure return behavior.

### Established Patterns
- External tools are invoked via subprocess with explicit return-code/error handling (not hidden framework magic).
- Agents expose a common `analyze(file_path)` flow that returns structured dictionaries.
- Configuration is read from `config.yaml` and used to tune tool behavior/timeouts.

### Integration Points
- `main.py` orchestrator dispatch to `NativeAgent` / `DotNetAgent` is the primary insertion point for shared runtime-contract enforcement.
- `agents/native_agent.py` and `agents/dotnet_agent.py` are the two direct implementation targets for Phase 1 contract scaffolding.
- `.planning/codebase/ARCHITECTURE.md` documents current routing and should remain stable while adapters are introduced.

</code_context>

<specifics>
## Specific Ideas

- Keep Phase 1 focused on shared runtime contract and deterministic behavior; implementation of full x64dbg feature depth remains in later phases.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 1-Runtime Foundation and Contracts*
*Context gathered: 2026-05-06*
