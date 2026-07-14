# HyperAgent OpenWiki quickstart

HyperAgent is a malware-analysis orchestrator that routes an input sample through a type classifier, runs a coarse analyzer for the detected family, expands discovered child artifacts, applies specialist analyzers, and returns a structured public result. The current codebase is centered on an **artifact graph** pipeline with first-class **run** and **task session** projections rather than a single monolithic scan path (`/core/orchestration.py`, `/main.py`, `/api.py`).

## The current mental model

Use these terms consistently while reading the repo:

- **run** — the compatibility-preserving top-level analysis record exposed by `GET /runs/{run_id}`
- **task session** — a traceable unit of work inside that run, exposed by `GET /runs/{run_id}/tasks`
- **dashboard** — shows task sessions grouped into **Pending**, **Processing**, and **Completed**, while still keeping the run timeline for detailed event history
- **`/hyperagent-malware-analyze`** — the stable user-facing Claude skill entrypoint, now implemented as a dispatcher over narrower specialist skills under `skill/`

That split improves runtime traceability without breaking older callers that still consume the run-level response envelope.

A minimal end-to-end picture now looks like this:

```text
sample
  -> run created
  -> task sessions emitted
  -> coarse + specialist analysis
  -> next-stage expansion
  -> report synthesis + risk scoring
  -> compatibility run snapshot + task snapshot
```

The API still keeps this state in memory, so the new observability model improves traceability inside a process, not durability across restarts.

## What this repository does

At a high level, HyperAgent:

1. Accepts a file path or uploaded sample.
2. Uses Detect It Easy (DIE) metadata to choose an analysis route (`NATIVE`, `DOTNET`, `PYTHON_SCRIPT`, or fallback handling) via `/core/die_handler.py`.
3. Runs a coarse agent for that route:
   - native binaries: `/agents/native_agent.py`
   - .NET binaries: `/agents/dotnet_agent.py`
   - Python/script-like samples: `/agents/script_agent.py`
4. Registers artifacts and findings, runs specialist analyzers, discovers next-stage artifacts, and synthesizes a final report and risk verdict (`/core/orchestration.py`).
5. Converts internal output into a stable public response envelope while preserving legacy payloads for compatibility (`/core/output_normalizer.py`, `/test/test_phase0_contract.py`).
6. Exposes the workflow through both a CLI (`/main.py`) and a FastAPI service/dashboard (`/api.py`).

## Start here based on what you need

- Architecture and response model: [architecture](architecture.md)
- Routing, agents, external analysis tools, and skills: [agents and analysis](agents-and-analysis.md)
- FastAPI endpoints, dashboard behavior, and operational notes: [API and operations](api-and-operations.md)
- Tests and change guidance: [testing](testing.md)

## Repository map

Primary source areas:

- `/main.py` — CLI entrypoint and top-level `HyperAgentOrchestrator`
- `/api.py` — FastAPI app, upload/path workflows, in-memory run tracking, task tracking, and HTML dashboard
- `/core/` — orchestration, result models, normalization, tool policy, pipeline logging, task runtime
- `/agents/` — coarse analyzers, prep/decompiler helpers, specialist analyzers, next-stage hunter
- `/skill/` — dispatcher and specialist Claude skill directories
- `/test/` — contract, orchestration, API, and helper/integration tests
- `/bootstrap.ps1` — Windows-first environment bootstrap and config generation
- `/config.yaml.template` — non-secret tool/command template

## Typical developer workflows

### Run the CLI

The CLI entrypoint creates `HyperAgentOrchestrator` and analyzes a single file path:

```bash
python main.py <path-to-sample>
```

Source: `/main.py`

### Run the API/dashboard

The repository’s setup script points users to `uvicorn api:app --host 0.0.0.0 --port 8000`, which serves both JSON endpoints and the dashboard HTML (`/bootstrap.ps1`, `/api.py`).

```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```

Useful read endpoints:

```bash
curl http://127.0.0.1:8000/runs/<run_id>
curl http://127.0.0.1:8000/runs/<run_id>/tasks
```

### Bootstrap the environment

The repo is Windows-oriented. `bootstrap.ps1` creates `.venv`, installs Python requirements, discovers external tools, writes `config.yaml` from the template, installs the full bundled Claude skill tree, installs the Claude IDA plugin, and optionally verifies imports (`/bootstrap.ps1`).

```powershell
powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1
```

Use `-Force` to regenerate `config.yaml`, or `-SkipVerify` to skip the final verification step.

## Environment and dependency model

HyperAgent depends on more than Python packages. The main external dependencies visible in source are:

- `diec` for file identification (`/core/die_handler.py`)
- Claude Code CLI, invoked through `/core/claude_code_runner.py`
- `dnspyc.exe` / `dnSpy.Console.exe` for .NET decompilation (`/agents/dotnet_agent.py`)
- `de4dot` for optional .NET cleanup before decompilation (`/agents/dotnet_agent.py`)
- `pyinstxtractor.py` and `pycdas` for Python/PyInstaller extraction and disassembly (`/agents/script_agent.py`)
- IDA/idalib-related preparation for native workflows (`/bootstrap.ps1`, `/config.yaml.template`)

Do not document or rely on local `config.yaml` values from a machine checkout. Use `/config.yaml.template` and bootstrap behavior as the portable source of truth.

## Public result contract

The public response is intentionally stable even as the internal architecture evolves. Tests lock the envelope to these root fields:

- `run_id`
- `file_path`
- `detected_type`
- `die`
- `result`
- `next_stage_results`
- `pipeline_log`
- `artifacts`
- `findings`
- `iocs`
- `verdict`
- `final_report_markdown`

Source: `/test/test_phase0_contract.py`, `/core/output_normalizer.py`, `/core/orchestration.py`

Important nuance: `result` is still the **legacy/coarse-agent payload**, while the richer fields are layered on top by the artifact-graph orchestrator.

The newer task/session model is additive:

- `GET /runs/{run_id}` remains the stable run-level projection
- `GET /runs/{run_id}/tasks` exposes per-task lifecycle and executor identity
- the dashboard consumes both projections together

## Things to watch out for before changing code

- **Compatibility matters.** The tests explicitly protect the public envelope and the legacy `result` payload shape (`/test/test_phase0_contract.py`).
- **This is Windows-first.** Many defaults assume `.exe` tools and PowerShell bootstrap flows (`/README.md`, `/bootstrap.ps1`, `/config.yaml.template`).
- **The API keeps state in memory.** `RUNS`, `TASK_SESSIONS`, and `RUN_TASK_INDEX` in `/api.py` are process-local dictionaries, not durable storage.
- **Classification is heuristic.** Routing depends on DIE text parsing and keyword checks rather than a richer type system (`/core/die_handler.py`).
- **Claude Code is part of the runtime.** Several analyzers assemble prompts and shell out to the Claude CLI (`/core/claude_code_runner.py`, agent files in `/agents/`).
- **One run can create many tasks.** Do not assume the current runtime is “one run, one agent, one report.”
- **The top-level skill name is stable on purpose.** Keep `/hyperagent-malware-analyze` working even when changing the specialist skill tree.

## Suggested reading order for future agents

1. `/openwiki/quickstart.md`
2. `/openwiki/architecture.md`
3. `/openwiki/agents-and-analysis.md`
4. `/openwiki/api-and-operations.md`
5. `/openwiki/testing.md`

If you need implementation detail quickly, read `/core/orchestration.py` first, then the relevant route-specific agent file.
