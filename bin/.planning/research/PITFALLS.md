# Domain Pitfalls

**Domain:** x64dbg-MCP integration for native and .NET HyperAgent workflows
**Researched:** 2026-05-06

## Critical Pitfalls

### Pitfall 1: Plugin Architecture Mismatch (`.dp64` vs `.dp32`)
**What goes wrong:** The MCP bridge appears "up" from CLI config, but x64dbg plugin never actually loads for the target debugger architecture.  
**Why it happens:** x64dbg plugin loading is architecture-specific; `.dp64` must load in `x64dbg`, `.dp32` in `x32dbg`.  
**Consequences:** Native agent and .NET agent cannot execute debugger-backed actions; MCP calls fail with connection/health errors and analysis degrades or stalls.  
**Early warning signs:**
- Missing x64dbg log line indicating MCP server startup on localhost.
- Health check endpoint fails repeatedly.
- "No active debug session"/connection refused despite MCP client configured.
**Prevention:**
- Add startup diagnostic that validates debugger architecture against expected plugin file.
- Assert plugin load status before any agent run (native and dotnet paths).
- Document exact plugin placement per architecture in setup docs and health-check output.
**Detection:** Preflight check that queries plugin health endpoint and emits targeted remediation (`install dp64 in x64/plugins` or `dp32 in x32/plugins`).
**Suggested roadmap phase mapping:** **Phase 2** (Claude path hardening), **Phase 3** (Codex parity), reinforced in **Phase 4** diagnostics.

### Pitfall 2: Debugger Threading Deadlocks from Synchronous Command Chaining
**What goes wrong:** Debug commands (`run`, `step`, etc.) issued in the wrong thread/callback context cause hangs or non-deterministic behavior.  
**Why it happens:** x64dbg uses separate command/debug/script thread coordination; naive direct command chaining can resume execution without waiting for next pause.  
**Consequences:** Agent workflows appear frozen, breakpoint automation fails mid-sequence, and long-running analysis times out.  
**Early warning signs:**
- Reproducible hang after a command sequence that mixes run/step/breakpoint toggles.
- Plugin returns partial command success followed by no further state transitions.
- Repeated timeouts in MCP calls that normally complete quickly.
**Prevention:**
- Use async/thread-safe execution model in plugin layer for multi-step debug actions.
- Enforce pause-state synchronization between run/step commands.
- Add retry-with-state-refresh only for transient faults, not for blocked state transitions.
**Detection:** Health check should include a tiny state-transition probe (`pause -> step -> paused`) with timeout and explicit deadlock classification.
**Suggested roadmap phase mapping:** **Phase 2/3** implementation quality gate, plus **Phase 4** deterministic verification scenarios.

### Pitfall 3: Debugger State Preconditions Ignored (Paused vs Running vs No Session)
**What goes wrong:** Agent asks for memory/disassembly/stack operations while target is running or not loaded.  
**Why it happens:** Many x64dbg operations require strict debugger states; generic agent prompts can violate preconditions.  
**Consequences:** False negatives ("tool broken"), flaky agent output, and inconsistent native vs .NET behavior.
**Early warning signs:**
- Frequent errors like "Debugger must be paused" or "No active debug session."
- Same command sometimes passes/fails depending on race timing.
- Increased support burden from "works on second try" reports.
**Prevention:**
- Add state-aware command router in both native and dotnet orchestration paths.
- Insert automatic state normalization step before inspection commands.
- Surface state machine hints in error text (what to do next).
**Detection:** Centralized telemetry counter of state-precondition failures with per-tool breakdown.
**Suggested roadmap phase mapping:** **Phase 1** (runtime/control abstraction), then enforced in **Phase 2/3**, documented in **Phase 4**.

### Pitfall 4: Plugin Dependency Resolution Breakage (DLL search/path changes)
**What goes wrong:** Plugin loads fail on some snapshots/environments when dependent libraries are not in allowed search locations.  
**Why it happens:** x64dbg hardening changed DLL loading behavior to reduce hijacking risk; PATH-based dependency assumptions can break plugin loading.  
**Consequences:** Environment-specific "works on my machine" failures, especially in maintainer handoffs and CI-like clean setups.
**Early warning signs:**
- Plugin present but not loading with dependency-related failures.
- Failures only on specific x64dbg snapshot/build variants.
- Plugin works after manual copying dependencies near debugger binary.
**Prevention:**
- Package plugin dependencies in deterministic local paths.
- Avoid relying on global PATH for critical plugin dependencies.
- Pin and test supported x64dbg snapshot range in docs.
**Detection:** Add dependency self-check command to diagnostics, including x64dbg build/snapshot fingerprint.
**Suggested roadmap phase mapping:** **Phase 2/3** setup reliability, plus **Phase 4** environment diagnostics matrix.

## Moderate Pitfalls

### Pitfall 5: Port and Process Lifecycle Conflicts (`127.0.0.1:27042`)
**What goes wrong:** MCP server starts but binds to a port already occupied or stale process state, causing intermittent connection refusal.  
**Prevention:**
- Add configurable host/port in integration config.
- Probe-and-report occupied port with process id hints.
- Ensure clean shutdown/restart behavior in native and dotnet orchestration wrappers.
**Early warning signs:**
- "Waiting for plugin..." hangs until timeout.
- Restarting x64dbg/client temporarily fixes issue.
**Suggested roadmap phase mapping:** **Phase 1** config model and **Phase 4** diagnostics.

### Pitfall 6: Timeout Underestimation on Large Binaries / Heavy Memory Operations
**What goes wrong:** Long inspections are incorrectly labeled as failures due to low timeout defaults.  
**Prevention:**
- Expose timeout/retry settings for x64dbg-MCP in config.
- Use operation-aware timeout tiers (quick inspect vs dump/scan).
**Early warning signs:**
- Timeouts cluster around memory scan/module dump tasks.
- Same command succeeds when rerun manually with higher timeout.
**Suggested roadmap phase mapping:** **Phase 1** runtime config contract, validated in **Phase 2/3** and benchmarked in **Phase 4**.

### Pitfall 7: .NET Single-File Bundle Blind Spots in `dnSpy` Pipeline
**What goes wrong:** DotNetAgent decompilation misses or misrepresents content in single-file publish bundles.  
**Why it happens:** dnSpyEx has acknowledged limited/on-hold support for single-file bundle workflows.  
**Prevention:**
- Detect likely single-file bundles before decompilation and warn/fallback.
- Add alternate extraction path for unsupported bundle types.
- Mark report confidence as degraded when bundle unpack not verified.
**Early warning signs:**
- DotNetAgent outputs unusually sparse C# tree for known complex binary.
- Decompile succeeds but produced source lacks expected entrypoint/library graph.
**Suggested roadmap phase mapping:** **Phase 3** (Codex parity for dotnet path) and **Phase 4** documentation of limitations.

## Minor Pitfalls

### Pitfall 8: Legacy Deobfuscation Tool Drift (`de4dot` maintenance gap)
**What goes wrong:** Deobfuscation assumptions silently fail on modern obfuscators, producing misleading downstream analysis confidence.  
**Prevention:**
- Treat deobfuscation as best-effort and annotate confidence.
- Add explicit "unsupported obfuscator" branch in .NET workflow.
- Keep de4dot optional, not hard dependency.
**Early warning signs:**
- Frequent unknown-obfuscator outcomes and unchanged output quality.
- Manual analyst review disagrees with automated deobfuscation claims.
**Suggested roadmap phase mapping:** **Phase 3** implementation caveat + **Phase 4** user-facing caveat docs.

### Pitfall 9: Native and .NET Agent Behavioral Divergence
**What goes wrong:** Native path benefits from debugger-first semantics while dotnet path remains decompile-first, causing inconsistent user expectations and response shape drift.  
**Prevention:**
- Define shared analysis contract and error taxonomy across agent types.
- Add parity checks for output structure and remediation guidance.
**Early warning signs:**
- Same failure category yields different error wording/actions per agent.
- Phase 4 parity tests pass one path but fail the other on diagnostics clarity.
**Suggested roadmap phase mapping:** **Phase 1** contract definition, verified in **Phase 4**.

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| Phase 1: Runtime Foundation | State/precondition model not unified across agents | Define shared runtime state machine, central error taxonomy, and config contract (timeouts/ports). |
| Phase 2: Claude Code Path | x64dbg plugin load mismatch and threading deadlocks surface first | Add Claude-path preflight (arch, health, state probe) and deterministic deadlock test script. |
| Phase 3: Codex CLI Path | DotNetAgent edge cases (single-file bundles, deobfuscation uncertainty) plus parity drift | Add explicit dotnet capability detection + fallback path; enforce response-shape parity tests. |
| Phase 4: Diagnostics and Verification | Generic errors obscure root cause and increase triage cost | Ship source-aware diagnostics mapping each failure to a fix step and validate in clean-room runs. |

## Sources

- x64dbg threading model (official): https://x64dbg.com/blog/2016/10/20/threading-model.html  
- x64dbg script DLL async behavior (official docs): https://help.x64dbg.com/en/latest/commands/script/scriptdll.html  
- x64dbg plugin loading command/docs (official docs): https://help.x64dbg.com/en/latest/commands/plugins/plugload.html  
- x64dbg issue on command chaining/wait semantics: https://github.com/x64dbg/x64dbg/issues/2307  
- x64dbg issue on DLL search path/dependency loading: https://github.com/x64dbg/x64dbg/issues/3047  
- x64dbg MCP implementation README (bromoket): https://github.com/bromoket/x64dbg_mcp  
- x64dbg MCP implementation README (Wasdubya): https://github.com/Wasdubya/x64dbgMCP  
- dnSpyEx single-file support issue: https://github.com/dnSpyEx/dnSpy/issues/16  
- de4dot README (limitations/support statement): https://github.com/de4dot/de4dot/blob/master/README.md
