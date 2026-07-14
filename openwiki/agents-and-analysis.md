# Agents and analysis flow

## Route selection

The route-selection path is compact:

- `main.HyperAgentOrchestrator` creates a `DIEHandler` and `FileClassifierAgent` (`/main.py`)
- `DIEHandler.identify()` runs `diec` and chooses `AnalysisType` (`/core/die_handler.py`)
- `_select_agent()` maps that analysis type to a route-specific agent (`/main.py`)

`FileClassifierAgent` is thin in the current codebase; the real classification logic lives in `DIEHandler`.

## Coarse agents

### NativeAgent

Source: `/agents/native_agent.py`

What it does:

- hashes the input sample
- prepares a native-analysis instruction through `NativeDisassemblyPrepAgent`
- invokes Claude Code via `run_claude_code()`
- filters the returned report to the `**Start of Analysis**` ... `**End of Analysis**` block
- returns either the legacy payload or an `AgentResult`

Important details:

- the current implementation still preserves the compatibility handoff `/hyperagent-malware-analyze @<ABSOLUTE_PATH>` through native prep
- Claude-backed native analysis appears as child task scope(s) with `executor_kind="claude"`
- native results only add the input artifact by default unless a downstream workflow adds more

### DotNetAgent

Source: `/agents/dotnet_agent.py`

What it does:

- optionally runs `de4dot` cleanup first
- decompiles the target into `dotnet_output/` using dnSpy CLI
- asks Claude Code to analyze the decompiled source tree
- returns both the input artifact and the decompiled source directory as structured artifacts

Important details:

- output directories are constrained to stay under `dotnet_output/`
- the source directory becomes a first-class artifact, which is later useful for next-stage hunting
- Claude-backed analysis may appear as nested task scope(s), while prep stays local

### ScriptAgent

Source: `/agents/script_agent.py`

What it does:

- computes a stable sample hash and uses it as the extraction directory name under `script_output/`
- delegates extraction/disassembly preparation to `PythonBytecodePrepAgent`
- can unpack PyInstaller content and disassemble bytecode via `pycdas`
- asks Claude Code to analyze generated `.pyasm` files plus extracted source/bytecode content
- returns the input artifact, extraction directory artifact, and `.pyasm` artifacts when available

Important details:

- prompt construction explicitly tells Claude to start with `.pyasm` files when present
- the result payload exposes `extract_dir` and `pyasm_files`, which the next-stage hunter can reuse
- path handling normalizes to workspace-relative POSIX paths for prompt readability while preserving absolute paths in structured artifacts

## Specialist analysis tasks

The orchestrator creates explicit task sessions for specialist analyzers in `/core/orchestration.py`.

Current ordered specialist steps are:

- `BehaviorAnalyzerAgent`
- `ObfuscationAnalyzerAgent`
- `ConfigExtractorAgent`
- `IOCExtractorAgent`
- `CapabilityMapperAgent`

These specialists no longer matter only as conceptual stages. They are represented in task/session projections and emit their own lifecycle through the pipeline logger.

Important consequence:

- do not assume specialist work is an invisible inline side effect anymore
- it is still orchestrated in-process today, but it is visible as task-level execution in API/dashboard views
- findings produced by these steps carry task and origin-stage metadata

Tests make the compatibility design explicit by asserting that `result` remains the original payload while `findings`, `verdict`, and `final_report_markdown` grow richer (`/test/test_orchestrator_next_stage.py`, `/test/test_phase4_specialist_agents.py`).

## Report and risk stages

After artifact expansion, root-level synthesis continues with:

- `ReportSynthesizerAgent`
- `RiskScoringAgent`

These are also represented as task sessions with their own stage keys:

- `report_synthesizer`
- `risk_scoring`

In the dashboard, they land in the same Pending / Processing / Completed board as the other tasks.

## Next-stage hunting

`NextStageHunterAgent` is the bridge from a single-sample analysis to recursive artifact-graph expansion (`/agents/next_stage_hunter_agent.py`).

Signals it uses:

- descendants already present in `ArtifactRegistry`
- structured payload fields such as `extracted_candidates` and `priority_pyasm_files`
- fallback scans of `extract_dir` and `source_directory`

Selection rules worth knowing:

- supports only a limited set of extensions by default: `.exe`, `.dll`, `.scr`, `.sys`, `.py`, `.pyc`, `.pyo`
- prunes noise directories such as `.git`, `.venv`, `__pycache__`, and package metadata directories
- suppresses low-value `.pyc`/`.pyo` files when a sibling `.py` exists
- deduplicates by both canonical path and SHA-256
- merges provenance and preserves the highest priority signal

This logic is heavily exercised in `/test/test_orchestrator_next_stage.py`.

Operationally, next-stage work is visible through two kinds of task sessions:

- `next_stage_hunter` — finding candidates
- `next_stage` — transitioning queued child artifacts into their own analysis path

That split is important when reading the dashboard timeline or task board.

## Task/session execution model

The current runtime mixes local and Claude-backed work under one task model.

Typical task stages visible in the API include:

- `request`
- `identify`
- `route`
- `agent`
- `next_stage_hunter`
- `next_stage`
- `report_synthesizer`
- `risk_scoring`

Some child stages are explicitly Claude-backed and are marked with `executor_kind="claude"`, such as:

- `native_agent.claude`
- `script_agent.claude`
- `dotnet_agent.claude`
- `claude_runner`

That means the same run can contain both local and Claude-backed task sessions while still projecting one compatibility run summary.

## External tool and command configuration

The non-secret configuration surface is defined in `/config.yaml.template` and populated by `/bootstrap.ps1`.

Main tool keys visible in source:

- `tools.diec`
- `tools.de4dot`
- `tools.dnspy`
- `tools.pyinstxtractor`
- `tools.pycdas`
- `mcp.ida_server_command`
- `llm.claude_code_command`

Route-specific code retrieves these settings through helpers in `/core/tool_policy.py` and then shells out to the resolved executables.

## Claude Code integration

Claude Code is not just a development helper here; it is part of runtime analysis.

`/core/claude_code_runner.py`:

- builds the command from config/tool-policy helpers
- launches the command asynchronously when possible
- logs task-scoped start/failure/completion events
- raises a runtime error on non-zero exit

Route-specific agents are responsible for assembling the instruction text, deciding what extracted material should be highlighted first, and post-processing the returned report.

## Skill tree and operator guidance

The runtime skill model is now split into a dispatcher plus specialist skills.

Stable alias:

- `/hyperagent-malware-analyze`

Specialist skill directories under `/skill/` include:

- `hyperagent-triage`
- `hyperagent-native-prep`
- `hyperagent-native-analysis`
- `hyperagent-dotnet-prep`
- `hyperagent-dotnet-analysis`
- `hyperagent-script-prep`
- `hyperagent-script-analysis`
- `hyperagent-behavior`
- `hyperagent-obfuscation`
- `hyperagent-config`
- `hyperagent-ioc`
- `hyperagent-capability`
- `hyperagent-next-stage`
- `hyperagent-report`
- `hyperagent-risk`

The dispatcher skill keeps the existing top-level command stable while routing work to narrower specialist boundaries.

The existing playbooks under `/skill/hyperagent-malware-analyze/` remain the detailed compatibility references for environment preparation, static analysis, dynamic analysis, payload extraction, failure recovery, and report structure.

## If you need to modify analysis behavior

Start with the narrowest layer that owns the behavior:

- route heuristics: `/core/die_handler.py`
- prompt construction / tool invocation: the specific route agent file
- task/session visibility and executor tagging: `/core/task_runtime.py`, `/core/pipeline_logger.py`, `/api.py`
- artifact registration and recursive expansion: `/core/orchestration.py`, `/agents/next_stage_hunter_agent.py`
- normalized findings or verdict logic: specialist agent files plus `/core/output_normalizer.py`
- top-level operator workflow or skill dispatch: `/skill/`
