# Architecture Patterns: x64dbg-mcp Integration for HyperAgent

**Domain:** Malware analysis orchestration (native + .NET)
**Researched:** 2026-05-06
**Scope:** Additive integration of `x64dbg-mcp` into current HyperAgent pipeline without breaking existing static analysis behavior

## Recommended Architecture

Introduce a **debug-tool adapter layer** under existing agents, not a new top-level orchestrator. Keep `HyperAgentOrchestrator -> AnalysisType routing` unchanged; only extend `NativeAgent` and `DotNetAgent` internals to optionally call `x64dbg-mcp` when enabled by policy/config.

This preserves current execution contracts:
- Entry points (`main.py`, `api.py`) unchanged
- Response envelope unchanged (`file_path`, `detected_type`, `die`, `result`)
- Existing IDA and dnSpy paths remain default-safe

### Integration Diagram (Logical)

```text
CLI/API
  -> HyperAgentOrchestrator
      -> DIEHandler.identify()
      -> AnalysisType router
          -> NativeAgent
              -> AnalysisPlanBuilder
              -> ToolAdapterRegistry
                  -> IDAAdapter (existing path, default)
                  -> X64DbgAdapter (new optional path)
              -> GooseSummarizer
          -> DotNetAgent
              -> AnalysisPlanBuilder
              -> ToolAdapterRegistry
                  -> DnSpyAdapter (existing path, default)
                  -> X64DbgAdapter (new optional path for runtime behavior)
              -> GooseSummarizer
```

## Component Boundaries

| Component | Responsibility | Communicates With |
|-----------|----------------|-------------------|
| `HyperAgentOrchestrator` | Keep current file-type routing and output envelope | `DIEHandler`, analysis agents |
| `NativeAgent` | Native workflow coordinator, now policy-driven tool selection | `AnalysisPlanBuilder`, tool adapters, Goose |
| `DotNetAgent` | .NET workflow coordinator, now policy-driven tool selection | `AnalysisPlanBuilder`, tool adapters, Goose |
| `AnalysisPlanBuilder` (new) | Convert detection + config into a deterministic execution plan (`static_only`, `hybrid`, `dynamic_first`) | Agent, tool registry |
| `ToolAdapterRegistry` (new) | Resolve and instantiate adapters by capability (`static_disasm`, `dynamic_debug`, `.net_runtime`) | Agents, adapters |
| `IDAAdapter` (existing behavior behind interface) | Start/probe/stop `idalib-mcp`, expose SSE endpoint and static artifacts | NativeAgent |
| `DnSpyAdapter` (existing behavior behind interface) | Decompile assembly and return source artifact set | DotNetAgent |
| `X64DbgAdapter` (new) | Start/probe/stop `x64dbg-mcp`; execute bounded dynamic probes and emit normalized runtime artifacts | NativeAgent, DotNetAgent |
| `GooseSummarizer` | Build final prompt from normalized artifacts and return analysis report | Agents |
| `DiagnosticsService` (new shared) | Preflight dependency checks, port conflicts, architecture mismatch, unsupported runtime context | CLI/API optional health command, agents |

### Adapter Contract (Interface)

All adapters should expose a small async contract to minimize coupling:

- `preflight(ctx) -> PreflightResult`
- `start(ctx) -> SessionHandle`
- `collect(ctx, session) -> ArtifactBundle`
- `stop(session) -> None`
- `capabilities() -> set[str]`

This allows Native and DotNet flows to compose adapters without branching logic explosion.

## Data and Control Flow

### 1) Native path (default-safe + optional dynamic)

1. Orchestrator routes `AnalysisType.NATIVE` to `NativeAgent`.
2. `AnalysisPlanBuilder` evaluates config/policy:
   - Default: `IDAAdapter` only (today's behavior)
   - Optional: `IDAAdapter + X64DbgAdapter` (hybrid)
   - Optional: `X64DbgAdapter` only (explicit opt-in)
3. Agent runs adapter preflight checks in deterministic order.
4. Agent executes adapters sequentially (v1) to avoid port/session contention.
5. Artifacts are normalized into one bundle (imports, strings, control flow hints, runtime API traces, anti-debug observations).
6. `GooseSummarizer` receives normalized bundle and produces final report.
7. Agent returns current schema-compatible result object.

### 2) .NET path (decompile-first + optional runtime enrichment)

1. Orchestrator routes `AnalysisType.DOTNET` to `DotNetAgent`.
2. Baseline remains `DnSpyAdapter` decompile flow.
3. Optional `X64DbgAdapter` runs after decompilation for runtime behaviors that static IL does not expose (loader staging, runtime decrypt, process injection timing).
4. Agent merges source-level and runtime artifacts into normalized bundle.
5. `GooseSummarizer` generates single report, preserving existing output shape.

### 3) Flow constraints

- One adapter session active per analysis request in v1.
- Adapter time budgets must be explicit (startup timeout, probe timeout, collection timeout).
- Failure in optional adapter degrades gracefully to baseline static path unless strict mode is enabled.

## Error Paths and Recovery Strategy

### Error taxonomy

| Error Class | Example | Handling | User Surface |
|-------------|---------|----------|--------------|
| `ConfigError` | Invalid adapter mode, missing command | Fail fast before analysis | Actionable config fix |
| `DependencyError` | `x64dbg-mcp` not found, missing debugger backend | Degrade to baseline when optional | Warning + remediation |
| `SessionStartError` | Port bind conflict, process spawn failure | Retry with fallback port range (bounded) then degrade/fail by policy | Clear "tool unavailable" reason |
| `ProbeTimeoutError` | SSE endpoint never ready | Stop process, collect stderr snippet, continue baseline if optional | Timeout guidance |
| `ArtifactError` | Empty or malformed runtime artifact | Mark source as partial, continue summarization | "partial evidence" note |
| `SummarizationError` | Goose fails/hangs | Return machine-readable failure envelope | Include raw adapter status |

### Control-flow decision rules

- **Default mode:** `optional_dynamic=true`
  - If `X64DbgAdapter` fails, continue with IDA/dnSpy path.
- **Strict mode:** `optional_dynamic=false`
  - Any required adapter failure returns explicit error and no silent fallback.
- **Unknown runtime state:** never guess; return diagnostics with required next steps.

## Build Order (Implementation Sequence)

1. **Introduce adapter interfaces and normalized artifact schema**
   - No behavior change yet; wrap existing IDA/dnSpy operations.
2. **Refactor NativeAgent/DotNetAgent to `AnalysisPlanBuilder + ToolAdapterRegistry`**
   - Keep default plan equivalent to current execution.
3. **Add DiagnosticsService and preflight command**
   - Verify `goose`, `idalib-mcp`, `dnspyc`, `x64dbg-mcp`, ports, and runtime context.
4. **Implement `X64DbgAdapter` with bounded probe set**
   - Startup, readiness checks, minimal deterministic commands, artifact emission.
5. **Integrate optional hybrid modes**
   - Native: static + dynamic
   - DotNet: decompile + dynamic
6. **Add parity tests + regression gates**
   - Assert old output envelope and baseline path are unchanged when `x64dbg` disabled.

## Compatibility Constraints (Non-Breaking Additive Integration)

### Must-preserve contracts

1. Existing orchestrator routing by `AnalysisType` remains the entry contract.
2. Existing API response envelope must not change for baseline mode.
3. Existing config keys continue to work with no migration requirement.
4. Existing IDA and dnSpy flows remain available even if `x64dbg-mcp` is absent.

### New config must be additive

Use additive keys under `mcp` / `analysis` (example):

```yaml
analysis:
  native_mode: "static_only"      # static_only | hybrid | dynamic_only
  dotnet_mode: "decompile_first"  # decompile_first | hybrid
  optional_dynamic: true
  strict_tooling: false

mcp:
  x64dbg_server_command: ["uv", "run", "x64dbg-mcp"]
  x64dbg_startup_timeout_s: 45
  x64dbg_probe_interval_s: 0.5
  x64dbg_port_range: [8750, 8765]
```

If these keys are absent, behavior must be equivalent to current implementation.

### OS/runtime constraints

- Windows-first support for `x64dbg` integration (aligns with current project constraints).
- Architecture compatibility checks are mandatory:
  - x64 sample -> x64 debugger path
  - x86 sample -> x32 debugger path
- DotNetAgent dynamic mode must not replace decompilation baseline; it only enriches it.

### Concurrency constraints

- Current hardcoded single-port risk must be removed for new adapter (`port range allocator`).
- Limit simultaneous debugger sessions to avoid resource contention (configurable semaphore).

## Recommended Internal Data Model

Create a shared `ArtifactBundle` so static and dynamic evidence are composable:

```text
ArtifactBundle
  static:
    imports, strings, functions, decompiled_snippets
  dynamic:
    breakpoints_hit, api_trace, memory_write_events, child_process_events
  metadata:
    adapter_status[], timestamps, confidence_notes
```

Goose prompt generation should consume this model, not raw adapter logs.

## Anti-Patterns to Avoid

### Anti-pattern 1: Branching directly inside orchestrator
**Why bad:** Spreads runtime/debugger complexity into top-level routing and risks regressions.
**Instead:** Keep orchestrator unchanged; encapsulate inside agent adapter planning.

### Anti-pattern 2: Making x64dbg required for all native/.NET analyses
**Why bad:** Breaks current installs and increases operational failure rate.
**Instead:** Optional dynamic enrichment with strict mode opt-in.

### Anti-pattern 3: Returning adapter-specific raw output in API contract
**Why bad:** Locks API to tool internals and breaks downstream consumers.
**Instead:** Normalize artifacts and preserve response envelope.

## Verification Targets

1. **Regression:** With dynamic disabled, outputs remain schema-compatible and behaviorally equivalent to current runs.
2. **Fallback:** With dynamic enabled but unavailable, analysis completes via baseline path with warning metadata.
3. **Strict mode:** Required adapter failure returns deterministic error object.
4. **Parity:** Native and DotNet both support the same adapter lifecycle states (`preflight`, `running`, `collected`, `degraded`, `failed`).

## Architecture Decision Summary

- Use **agent-local adapter composition** instead of orchestrator rewrite.
- Keep **static analysis baseline as default**; add dynamic debugging as optional enrichment.
- Standardize **artifact normalization + error taxonomy** so native and .NET integrations behave consistently.
- Sequence implementation so each step is reversible and regression-safe.
