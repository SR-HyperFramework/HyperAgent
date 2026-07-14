# Architecture

## Core design

The current architecture is an **artifact-graph orchestrator** with an additive **task-session observability** layer.

The main internal models and stores are:

- `TaskSession` — a traceable unit of work with task/session identity, lifecycle state, parent linkage, executor kind, and timestamps (`/core/result_models.py`)
- `ArtifactNode` — a discovered file/directory artifact with parent/child lineage and optional SHA-256 (`/core/result_models.py`)
- `Finding` — a normalized finding attached to an artifact and optionally annotated with producing task metadata (`/core/result_models.py`)
- `AgentResult` — the internal representation returned by modernized agents, containing the legacy payload plus structured artifacts/findings (`/core/result_models.py`)
- `RunContext` — analysis-time context passed into agents, now including task/session identity (`/core/result_models.py`)
- `ArtifactRegistry` — indexes artifacts by id, path, SHA-256, and parent/child relationships (`/core/artifact_registry.py`)
- `FindingStore` — stores findings by artifact (`/core/finding_store.py`)
- `WorkQueue` / `WorkItem` — priority queue for next-stage analysis (`/core/work_queue.py`)

The orchestration entrypoint is `ArtifactGraphOrchestrator.analyze()` in `/core/orchestration.py`.

## Run projection vs task projection

A key current design choice is that HyperAgent exposes two layers at once:

- **run projection** — stable public compatibility view for callers
- **task projection** — finer-grained execution view for dashboarding and runtime traceability

That distinction matters:

- changing task/session internals should not casually break the run-level response contract
- adding task visibility is expected to improve observability without replacing the old envelope
- the dashboard consumes both layers together

## End-to-end flow

The orchestrator’s flow is now better understood as a task-producing pipeline:

1. Create or reuse the root request task.
2. Normalize the input path and enqueue root work.
3. Run `identify` task(s) using `DIEHandler.identify()` to get DIE metadata and route to an `AnalysisType` (`/core/die_handler.py`).
4. Run `route` task(s) to choose the correct coarse agent.
5. Run `agent` task(s) for coarse analysis.
6. Annotate structured outputs with producing task metadata.
7. Run ordered specialist analyzer task(s):
   - behavior
   - obfuscation
   - config
   - IOC extraction
   - capability mapping
8. Run `next_stage_hunter` to discover candidates.
9. Enqueue `next_stage` transition tasks and recursively analyze child artifacts up to `max_depth`.
10. Run root-level `report_synthesizer` and `risk_scoring` tasks.
11. Build the compatibility run response envelope and merge the public summary.

Primary source: `/core/orchestration.py`

## Hybrid execution model

The runtime is hybrid:

- many deterministic steps remain local/in-process
- Claude-heavy work can run as child task scopes with `executor_kind="claude"`
- both local and Claude-backed work are projected into the same task model

Examples visible in code/tests:

- local tasks: `request`, `identify`, `route`, `next_stage_hunter`, `next_stage`, `report_synthesizer`, `risk_scoring`
- Claude-backed child scopes: `native_agent.claude`, `script_agent.claude`, `dotnet_agent.claude`, `claude_runner`

This model lets HyperAgent expose a single live dashboard even when execution boundaries differ.

## Why the internal/result split exists

A central design constraint is visible in both code and tests: the repository is evolving toward structured artifact/finding output and task/session traceability without breaking existing consumers.

Two layers coexist:

- **Internal modern layer:** agents may return `AgentResult` with artifacts and findings, and those findings/artifacts may be annotated with producing task metadata.
- **Public compatibility layer:** `normalize_agent_result()` strips that down to the old payload for `result`, while `build_public_run_summary()` adds `artifacts`, `findings`, `iocs`, `verdict`, and `final_report_markdown` alongside it (`/core/output_normalizer.py`).

That is why many tests assert that specialist stages add new structured data **without changing** the coarse payload (`/test/test_orchestrator_next_stage.py`, `/test/test_phase0_contract.py`).

## Response contract

`build_orchestrator_response()` in `/core/output_normalizer.py` produces the base envelope:

```json
{
  "run_id": "...",
  "file_path": "...",
  "detected_type": "...",
  "die": {},
  "result": {},
  "next_stage_results": [],
  "pipeline_log": []
}
```

`build_public_run_summary()` then contributes:

- `artifacts`
- `findings`
- `iocs`
- `verdict`
- `final_report_markdown`

The contract is enforced by `/test/test_phase0_contract.py`.

Task projections are additive and include fields such as:

- `task_id`
- `run_id`
- `session_id`
- `parent_task_id`
- `stage_key`
- `title`
- `status`
- `terminal_state`
- `executor_kind`
- `artifact_id`
- `summary`
- timestamps

## Pipeline logging model

`PipelineLogger` is both an event store and a listener publisher (`/core/pipeline_logger.py`). Each event includes:

- `run_id`
- `sequence`
- `timestamp`
- `stage`
- `state`
- `status_label`
- `display_stage`
- `message`
- optional `data`

Task-scoped logging layers task identity onto those events. `TaskScopedPipelineLogger` wraps the root logger and injects:

- `task_id`
- `session_id`
- `parent_task_id` when present
- `executor_kind`

This is what allows the API layer to synthesize task projections from event flow.

## Specialist analysis pipeline

The specialist stage in `/core/orchestration.py` is intentionally ordered. Capability mapping runs after other finding-producing specialists so it can infer higher-level capabilities from previously collected findings:

1. `BehaviorAnalyzerAgent`
2. `ObfuscationAnalyzerAgent`
3. `ConfigExtractorAgent`
4. `IOCExtractorAgent`
5. `CapabilityMapperAgent`

After recursive next-stage analysis, two root-level synthesis steps run:

- `ReportSynthesizerAgent`
- `RiskScoringAgent`

These steps are visible in task/session projections and not just implied by the final report.

## Artifact graph and recursion

Artifacts are tracked by path and SHA-256, with parent/child lineage in `ArtifactRegistry` (`/core/artifact_registry.py`). Next-stage processing uses this graph plus structured fields from agent payloads.

Important behaviors visible in source:

- deduplication by canonical path and SHA-256 (`/agents/next_stage_hunter_agent.py`)
- provenance merging when multiple signals point to the same child artifact (`/agents/next_stage_hunter_agent.py`)
- priority ordering so structured candidates are analyzed before fallback directory-scan discoveries (`/agents/next_stage_hunter_agent.py`, `/core/work_queue.py`)
- recursion depth limiting in the orchestrator (`/core/orchestration.py`)
- separate task visibility for candidate hunting versus queued child-artifact analysis

This is a major reason the codebase moved away from ad hoc recursive scanning in `main.py`.

## Classification and routing

`DIEHandler.identify()` parses DIE text output and maps it to an `AnalysisType` using simple heuristics (`/core/die_handler.py`):

- `.NET` signals in library/compiler/language => `DOTNET`
- Python/PyInstaller signals => `PYTHON_SCRIPT`
- native/compiler-family signals => `NATIVE`
- some Go/JavaScript-compiled binaries also route as `NATIVE`
- otherwise => `UNKNOWN`

`HyperAgentOrchestrator._select_agent()` currently routes `UNKNOWN` to `ScriptAgent`, so unknown samples still go through a permissive fallback path (`/main.py`). That is operationally useful, but it is also a design caveat when changing routing behavior.

## Skill architecture

The operator-facing Claude skill layer is now split:

- `/hyperagent-malware-analyze` — stable dispatcher/compatibility alias
- specialist skills under `/skill/` — narrower prep, analysis, extraction, reporting, and risk roles

This is an architectural compatibility choice, not just a documentation preference.

Runtime and tooling now assume that bootstrap installs the full skill tree, while preserving the top-level entrypoint.

## Important architectural caveats

- The API run/task state is still in-memory only (`RUNS`, `TASK_SESSIONS`, `RUN_TASK_INDEX` in `/api.py`).
- The public response is richer than the internal compatibility payload, but the old payload still drives many assumptions in tests and downstream code.
- External tools and Claude Code are part of the runtime architecture, not optional documentation details.
- Specialist work is now observable as task-level execution, even when still orchestrated locally.
- The task board improves runtime observability, but it is not a durable workflow backend.

## Good starting points for code changes

- Changing the public response: `/core/output_normalizer.py`, `/test/test_phase0_contract.py`
- Changing orchestration behavior: `/core/orchestration.py`, `/test/test_orchestrator_next_stage.py`
- Changing task/session visibility: `/core/result_models.py`, `/core/task_runtime.py`, `/core/pipeline_logger.py`, `/api.py`
- Changing lineage/dedup logic: `/agents/next_stage_hunter_agent.py`, `/core/artifact_registry.py`
- Changing UI-visible task states or board grouping: `/api.py`, `/test/test_api_dashboard.py`
- Changing top-level operator workflow or skill dispatch: `/skill/`, `/bootstrap.ps1`
