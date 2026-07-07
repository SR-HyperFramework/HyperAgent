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

If your change affects the public payload, start here first.

### Orchestrator and next-stage behavior

`/test/test_orchestrator_next_stage.py` is the best source for how the artifact-graph design is supposed to behave.

It covers:

- structured artifact and finding accumulation
- specialist-stage enrichment without payload breakage
- report synthesis and risk scoring
- next-stage artifact discovery, priority, and recursion behavior
- deduplication/provenance expectations around child artifacts

If you are editing `/core/orchestration.py` or `/agents/next_stage_hunter_agent.py`, read this test file before making changes.

### Specialist analyzers

`/test/test_phase4_specialist_agents.py` focuses on normalized finding generation by specialist agents. Use it when adjusting:

- behavior extraction
- obfuscation detection
- config extraction
- IOC extraction
- capability mapping
- synthesis/scoring assumptions

### Prep agents and tooling helpers

`/test/test_phase2_prep_agents.py` and `/test/test_claude_code_runner.py` protect the prep/invocation layers. These are relevant when changing external-tool invocation or Claude Code execution behavior.

### API/dashboard behavior

`/test/test_api_dashboard.py` protects:

- queued run lifecycle snapshots
- upload/path wrapper behavior
- pipeline log display-stage expectations
- dashboard HTML shell contents

### Result models

`/test/test_result_models.py` covers the structured dataclasses and related assumptions.

## How to run tests

The repository bootstrap script installs dependencies into `.venv` and verifies imports (`/bootstrap.ps1`). From there, the normal Python test workflow is expected.

A typical local command is:

```bash
python -m pytest test
```

The exact test runner is not documented elsewhere in source, but the repository structure is pytest-compatible and uses standard `unittest` test cases.

## Suggested test strategy by change type

### If you change route selection or tool discovery

Run at least:

- `test/test_phase0_contract.py`
- `test/test_phase2_prep_agents.py`
- `test/test_claude_code_runner.py`

### If you change orchestration or recursive artifact handling

Run at least:

- `test/test_phase0_contract.py`
- `test/test_orchestrator_next_stage.py`
- `test/test_result_models.py`

### If you change specialist finding logic

Run at least:

- `test/test_phase4_specialist_agents.py`
- `test/test_orchestrator_next_stage.py`

### If you change the API or dashboard

Run at least:

- `test/test_phase0_contract.py`
- `test/test_api_dashboard.py`

## Practical guidance for future agents

- Treat tests as contract documents, not just regression checks.
- Be careful when changing any field inside `result`; many tests assume it is compatibility-preserving.
- When adding structured outputs, prefer extending `artifacts`, `findings`, `iocs`, `verdict`, or `final_report_markdown` instead of mutating the coarse payload.
- When changing pipeline stages or labels, check both logger code and dashboard tests.
- When changing recursive next-stage behavior, pay close attention to path normalization, SHA-256 deduplication, and depth limits.
