# Phase 1: Runtime Foundation and Contracts - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-06
**Phase:** 1-Runtime Foundation and Contracts
**Areas discussed:** Adapter contract shape

---

## Adapter contract shape

| Option | Description | Selected |
|--------|-------------|----------|
| One strict shared adapter interface | Identical method names and return schema for native and dotnet paths | ✓ |
| Shared core interface + runtime extension hooks | Common base plus optional runtime-specific hooks | |
| Runtime-specific wrappers normalized later | Separate wrappers with later orchestrator normalization | |

**User's choice:** One strict shared adapter interface.
**Notes:** Lock this at Phase 1 so later phases implement against a stable, deterministic contract.

---

## Result schema strictness

| Option | Description | Selected |
|--------|-------------|----------|
| Fully normalized schema at adapter boundary | Same keys and value types for both runtimes | ✓ |
| Core normalized fields + runtime metadata | Partial normalization with extra runtime payload | |
| Loose per-runtime schema normalized later | Deferred normalization | |

**User's choice:** Fully normalized schema at contract level.
**Notes:** Downstream planning should treat schema parity as mandatory, not aspirational.

---

## Error model

| Option | Description | Selected |
|--------|-------------|----------|
| Typed error codes/taxonomy | Stable, machine-usable error categories in contract | ✓ |
| Human-readable messages only | Free-form messages without typed codes | |
| Mixed code + remediation message | Typed code plus user-facing fix guidance | |

**User's choice:** Typed error codes/taxonomy.
**Notes:** Phase 1 should define the canonical taxonomy so diagnostics and health checks can align in later phases.

---

## Claude's Discretion

None.

## Deferred Ideas

None.
