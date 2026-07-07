# Architecture

## Core design

The current architecture is an **artifact-graph orchestrator** built around a small set of core models and stores:

- `ArtifactNode` — a discovered file/directory artifact with parent/child lineage and optional SHA-256 (`/core/result_models.py`)
- `Finding` — a normalized finding attached to an artifact (`/core/result_models.py`)
- `AgentResult` — the internal representation returned by modernized agents, containing the legacy payload plus structured artifacts/findings (`/core/result_models.py`)
- `ArtifactRegistry` — indexes artifacts by id, path, SHA-256, and parent/child relationships (`/core/artifact_registry.py`)
- `FindingStore` — stores findings by artifact (`/core/finding_store.py`)
- `WorkQueue` / `WorkItem` — priority queue for next-stage analysis (`/core/work_queue.py`)

The orchestration entrypoint is `ArtifactGraphOrchestrator.analyze()` in `/core/orchestration.py`.

## End-to-end flow

The orchestrator’s flow is:

1. Log the request and normalize the input path.
2. Use `DIEHandler.identify()` to get DIE metadata and route to an `AnalysisType` (`/core/die_handler.py`).
3. Instantiate the coarse agent via the injected `agent_factory` from `/main.py`.
4. Run the coarse agent and normalize its output.
5. If the agent returned `AgentResult`, link the root artifact into the registry.
6. Run specialist analyzers in a fixed order:
   - behavior
   - obfuscation
   - config
   - IOC extraction
   - capability mapping
7. Discover next-stage candidates with `NextStageHunterAgent` and enqueue them.
8. Recursively analyze next-stage artifacts up to `max_depth` (default `2`).
9. Run report synthesis and risk scoring for the root artifact.
10. Build the public response envelope, keeping the coarse-agent payload in `result`.

Primary source: `/core/orchestration.py`

## Why the internal/result split exists

A central design constraint is visible in both code and tests: the repository is evolving toward structured artifact/finding output without breaking existing consumers.

Two layers coexist:

- **Internal modern layer:** agents may return `AgentResult` with artifacts and findings.
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

The logger also derives human-friendly stage labels such as `Request`, `Analyze`, `Decompile`, `Synthesize`, and `Score`. The API subscribes to the logger so it can update in-memory run status in near real time (`/api.py`, `/core/pipeline_logger.py`).

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

Tests show the expected effect: the root artifact often accumulates `analysis_report`, specialist findings, `report_synthesis`, and `risk_assessment` categories in that order (`/test/test_orchestrator_next_stage.py`, `/test/test_phase4_specialist_agents.py`).

## Artifact graph and recursion

Artifacts are tracked by path and SHA-256, with parent/child lineage in `ArtifactRegistry` (`/core/artifact_registry.py`). Next-stage processing uses this graph plus structured fields from agent payloads.

Important behaviors visible in source:

- deduplication by canonical path and SHA-256 (`/agents/next_stage_hunter_agent.py`)
- provenance merging when multiple signals point to the same child artifact (`/agents/next_stage_hunter_agent.py`)
- priority ordering so structured candidates are analyzed before fallback directory-scan discoveries (`/agents/next_stage_hunter_agent.py`, `/core/work_queue.py`)
- recursion depth limiting in the orchestrator (`/core/orchestration.py`)

This is a major reason the codebase moved away from ad hoc recursive scanning in `main.py`.

## Classification and routing

`DIEHandler.identify()` parses DIE text output and maps it to an `AnalysisType` using simple heuristics (`/core/die_handler.py`):

- `.NET` signals in library/compiler/language => `DOTNET`
- Python/PyInstaller signals => `PYTHON_SCRIPT`
- native/compiler-family signals => `NATIVE`
- some Go/JavaScript-compiled binaries also route as `NATIVE`
- otherwise => `UNKNOWN`

`HyperAgentOrchestrator._select_agent()` currently routes `UNKNOWN` to `ScriptAgent`, so unknown samples still go through a permissive fallback path (`/main.py`). That is operationally useful, but it is also a design caveat when changing routing behavior.

## Important architectural caveats

- The system is **not** a generic plugin framework yet; route and specialist sets are hard-coded in orchestrator construction (`/core/orchestration.py`).
- API run storage is in-memory only (`RUNS` in `/api.py`).
- The public response is richer than the internal compatibility payload, but the old payload still drives many assumptions in tests and downstream code.
- External tools and Claude Code are part of the runtime architecture, not optional documentation details.

## Good starting points for code changes

- Changing the public response: `/core/output_normalizer.py`, `/test/test_phase0_contract.py`
- Changing orchestration behavior: `/core/orchestration.py`, `/test/test_orchestrator_next_stage.py`
- Changing lineage/dedup logic: `/agents/next_stage_hunter_agent.py`, `/core/artifact_registry.py`
- Changing UI-visible pipeline states: `/core/pipeline_logger.py`, `/api.py`, `/test/test_api_dashboard.py`
