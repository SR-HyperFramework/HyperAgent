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

- the current implementation logs that legacy IDA MCP startup/cleanup is skipped, even though config still retains legacy IDA-related settings for compatibility (`/agents/native_agent.py`, `/config.yaml.template`)
- native results only add the input artifact by default; there is no extra extracted directory model here unless a downstream workflow adds one

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
- missing dnSpy or failed decompilation is surfaced through pipeline logging

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

## Specialist agents

The orchestrator directly constructs and runs these specialist analyzers (`/core/orchestration.py`):

- `/agents/behavior_analyzer_agent.py`
- `/agents/obfuscation_analyzer_agent.py`
- `/agents/config_extractor_agent.py`
- `/agents/ioc_extractor_agent.py`
- `/agents/capability_mapper_agent.py`
- `/agents/report_synthesizer_agent.py`
- `/agents/risk_scoring_agent.py`

These agents do not replace the coarse report. They mine and normalize information from it into structured findings, then synthesize a final report and verdict.

Tests make that design explicit by asserting that `result` remains the original compatibility payload while `findings`, `verdict`, and `final_report_markdown` grow richer (`/test/test_orchestrator_next_stage.py`, `/test/test_phase4_specialist_agents.py`).

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
- logs pipeline start/failure/completion events
- raises a runtime error on non-zero exit

Route-specific agents are responsible for assembling the instruction text, deciding what extracted material should be highlighted first, and post-processing the returned report.

## Source-backed operator guidance already in the repo

The bundled skill directory `/skill/hyperagent-malware-analyze/` contains repository-adjacent guidance pages such as:

- `environment-preparation.md`
- `payload-extraction.md`
- `static-analysis.md`
- `dynamic-analysis.md`
- `failure-recovery.md`
- `report-template.md`
- `SKILL.md`

These are useful as operator playbooks, but the source code in `/agents/` and `/core/` is the stronger authority for actual runtime behavior.

## If you need to modify analysis behavior

Start with the narrowest layer that owns the behavior:

- route heuristics: `/core/die_handler.py`
- prompt construction / tool invocation: the specific route agent file
- artifact registration and recursive expansion: `/core/orchestration.py`, `/agents/next_stage_hunter_agent.py`
- normalized findings or verdict logic: specialist agent files plus `/core/output_normalizer.py`
