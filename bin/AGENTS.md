# HyperAgent GSD Guide

## Project Context

This project extends HyperAgent to support `x64dbg-mcp` workflows inside both `native_agent` and `dotnet_agent` paths. Current v1 target is deterministic additive integration with shared contracts, health checks, and diagnostics.

## Source of Truth

- Project context: `.planning/PROJECT.md`
- Requirements: `.planning/REQUIREMENTS.md`
- Roadmap: `.planning/ROADMAP.md`
- State: `.planning/STATE.md`
- Workflow config: `.planning/config.json`

## Working Rules

1. Map every new v1 requirement to exactly one phase in `ROADMAP.md`.
2. Keep v1 scope constrained to native and dotnet x64dbg integration (no broad multi-CLI expansion).
3. Preserve existing HyperAgent analysis behavior; integration work must be additive.
4. Update `STATE.md` whenever phase status changes.
5. Keep docs and diagnostics in sync with actual runnable commands.

## Next Step

Run:

`/gsd-discuss-phase 1`

Goal: clarify shared runtime contracts and implementation boundaries for native and dotnet x64dbg integration before detailed plan creation.
