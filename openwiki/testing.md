# Testing and change guidance

## Test suite layout

The repository’s main automated coverage lives under `/test/`:

- `/test/test_phase0_contract.py`
- `/test/test_phase2_prep_agents.py`
- `/test/test_phase4_specialist_agents.py`
- `/test/test_orchestrator_next_stage.py`
- `/test/test_api_dashboard.py`
- `/test/test_claude_code_runner.py`
- `/test/test_agent_runner_integration.py`
- `/test/test_result_models.py`

This suite is the best guide to what maintainers consider stable behavior.

## What each test area protects

### Contract and compatibility

`/test/test_phase0_contract.py` is the highest-signal test file for public API stability.

It protects:

- root response keys for the orchestrator
- API wrapper fields for path and upload workflows
- the assumption that `result` remains the legacy payload
- presence and basic structure of `pipeline_log`
- stability of the run-level compatibility envelope even as task/session internals evolve

If your change affects the public payload, start here first.

### Result models and task/session semantics

`/test/test_result_models.py` is the highest-signal file for the new task/session model.

It protects:

- `TaskSession` defaults and fields
- `RunContext` task/session identity
- task-bound logger behavior
- child task scope creation
- executor-kind classification for stage keys
- compatibility behavior of public summaries layered on top of richer internals

If you are changing task lifecycle, task metadata, executor tagging, or task-bound logging, start here first.

### Orchestrator and next-stage behavior

`/test/test_orchestrator_next_stage.py` is the best source for how the artifact-graph design is supposed to behave.

It covers:

- structured artifact and finding accumulation
- specialist-stage enrichment without payload breakage
- report synthesis and risk scoring
- next-stage artifact discovery, priority, and recursion behavior
- deduplication/provenance expectations around child artifacts
- visibility of task lifecycle events for local/in-process steps

If you are editing `/core/orchestration.py` or `/agents/next_stage_hunter_agent.py`, read this test file before making changes.

### Specialist analyzers

`/test/test_phase4_specialist_agents.py` focuses on normalized finding generation by specialist agents. Use it when adjusting:

- behavior extraction
- obfuscation detection
- config extraction
- IOC extraction
- capability mapping
- synthesis/scoring assumptions

### Prep agents and Claude execution helpers

`/test/test_phase2_prep_agents.py` and `/test/test_claude_code_runner.py` protect the prep/invocation layers. These are relevant when changing external-tool invocation, Claude Code execution behavior, or compatibility handoff instructions.

Important compatibility examples locked by tests include:

- native prep still emitting `/hyperagent-malware-analyze @<ABSOLUTE_PATH>`
- Claude task scopes carrying `executor_kind="claude"`
- default Claude command construction through `run_claude_code()`

### Agent runner integration

`/test/test_agent_runner_integration.py` checks route-specific prompt/invocation behavior end to end at the agent boundary.

This is the file to read before changing:

- how native, script, or dotnet agents build Claude instructions
- how prep outputs are threaded into route-specific analysis
- compatibility between route agents and the stable `/hyperagent-malware-analyze` entrypoint

### API/dashboard behavior

`/test/test_api_dashboard.py` protects:

- queued run lifecycle snapshots
- upload/path wrapper behavior
- pipeline log display-stage expectations
- run-to-task projection behavior
- nested child task tracking
- executor-kind visibility in task snapshots
- dashboard HTML shell contents, including the task board

If you change task grouping, board columns, task polling, or task status projection, start here first.

## How to run tests

The repository bootstrap script installs dependencies into `.venv` and verifies imports (`/bootstrap.ps1`). From there, the normal Python test workflow is expected.

A common repository-friendly pattern here is unittest discovery from the repo root:

```bash
python -m unittest discover -s test -p "test_*.py"
```

For narrower validation, run just the affected suites. Examples:

```bash
python -m unittest discover -s test -p "test_api_dashboard.py"
python -m unittest discover -s test -p "test_result_models.py"
python -m unittest discover -s test -p "test_phase2_prep_agents.py"
python -m unittest discover -s test -p "test_agent_runner_integration.py"
```

## Suggested test strategy by change type

### If you change route selection or tool discovery

Run at least:

- `test_phase0_contract.py`
- `test_phase2_prep_agents.py`
- `test_claude_code_runner.py`

### If you change orchestration, task/session semantics, or recursive artifact handling

Run at least:

- `test_phase0_contract.py`
- `test_result_models.py`
- `test_orchestrator_next_stage.py`

### If you change specialist finding logic

Run at least:

- `test_phase4_specialist_agents.py`
- `test_orchestrator_next_stage.py`

### If you change the API or dashboard

Run at least:

- `test_phase0_contract.py`
- `test_api_dashboard.py`
- `test_result_models.py`

### If you change the Claude skill tree or compatibility routing

Run at least:

- `test_phase2_prep_agents.py`
- `test_agent_runner_integration.py`
- any targeted bootstrap/config validation available in your environment

## Practical guidance for future agents

- Treat tests as contract documents, not just regression checks.
- Be careful when changing any field inside `result`; many tests assume it is compatibility-preserving.
- When adding structured outputs, prefer extending `artifacts`, `findings`, `iocs`, `verdict`, or `final_report_markdown` instead of mutating the coarse payload.
- When changing pipeline stages or labels, check logger code, task projection behavior, and dashboard tests together.
- When changing recursive next-stage behavior, pay close attention to path normalization, SHA-256 deduplication, and depth limits.
- When changing the skill split, keep `/hyperagent-malware-analyze` working unless you are deliberately performing a breaking migration.
