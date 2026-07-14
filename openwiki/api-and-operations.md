# API and operations

## FastAPI surface

The application is created in `/api.py`:

```python
app = FastAPI(title="HyperAgent API", version="0.1.0")
```

A module-level `HyperAgentOrchestrator()` instance is shared across requests.

## Supported workflows

The API supports two broad patterns:

1. **Synchronous analysis** — return the analysis payload directly.
2. **Queued/background analysis** — create a run record immediately, launch analysis via `asyncio.create_task`, and let clients poll the run snapshot.

This behavior is implemented entirely in `/api.py`.

## In-memory run and task tracking

Run and task state are stored in process memory:

```python
RUNS: dict[str, dict[str, Any]] = {}
TASK_SESSIONS: dict[str, dict[str, Any]] = {}
RUN_TASK_INDEX: dict[str, list[str]] = {}
```

That means:

- state is per-process only
- restarting the API loses run history and task history
- multiple worker processes will not share run/task data

This is adequate for local operator workflows and tests, but not durable job orchestration.

## Run snapshot vs task snapshot

The API now exposes two complementary projections:

- `GET /runs/{run_id}` — compatibility-preserving run snapshot
- `GET /runs/{run_id}/tasks` — task-session snapshot for live workflow inspection

Use them differently:

- choose the **run snapshot** when you need the stable public envelope (`result`, `artifacts`, `findings`, `iocs`, `verdict`, `final_report_markdown`, `pipeline_log`)
- choose the **task snapshot** when you need per-step lifecycle, parent/child task relationships, or executor identity

Typical task fields include:

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

## Path vs upload execution

### Path-based execution

Path-based requests pass the existing file path into the orchestrator and use `source="path"` in the run record (`/api.py`).

### Upload-based execution

Upload requests stream the body to disk before analysis (`/api.py`):

- if `keep_file=True`, the file is stored under `uploads/` using `<upload_id>_<safe_name>`
- otherwise a temporary file is created and removed after execution

`HYPERAGENT_UPLOAD_DIR` can override the upload directory root (`/api.py`).

## Pipeline log propagation

`api.py` subscribes a listener to `PipelineLogger` so that run snapshots and task projections get updated while background work is running. The listener syncs task lifecycle from emitted events and derives run status from task state.

This coupling is why changes to `/core/pipeline_logger.py`, `/core/task_runtime.py`, or task metadata can affect dashboard behavior.

## Dashboard

`_dashboard_html()` in `/api.py` returns a full HTML shell for the HyperAgent Workflow Dashboard.

The dashboard now combines two views of the same run:

1. a **task board** with three columns:
   - Pending
   - Processing
   - Completed
2. the existing **timeline/detail** view for event-level inspection

Important UI contract details:

- task cards are grouped by `status`, not by stage name
- terminal outcomes such as `failed`, `skipped`, and `cancelled` remain in the **Completed** column and are shown via terminal-state badges
- the page polls both the run snapshot and the task snapshot
- the dashboard is still rendered as a server-generated HTML string rather than a frontend bundle

Source: `/api.py`, `/test/test_api_dashboard.py`

## Executor model

The task projection also exposes whether a step ran locally or through a Claude-backed scope:

- `executor_kind="local"` for deterministic/in-process steps
- `executor_kind="claude"` for Claude-backed child scopes such as `native_agent.claude`, `script_agent.claude`, `dotnet_agent.claude`, and `claude_runner`

That executor distinction is important for debugging runtime behavior and for interpreting nested task trees.

## Operational setup

The supported setup path is the PowerShell bootstrap script (`/bootstrap.ps1`). It performs several operations that matter operationally:

- checks for Python, Node.js, npm, Claude CLI, and `uv`
- creates `.venv`
- installs Python dependencies from `/requirements.txt`
- generates `config.yaml` from `/config.yaml.template`
- installs the bundled Claude skill tree from `/skill/`
- installs a Claude plugin related to IDA workflows
- optionally activates idalib if an IDA installation is detected
- runs import/config verification unless `-SkipVerify` is passed

The script prints suggested next steps including:

- activating `.venv`
- starting `uvicorn api:app`
- running `python main.py <sample>`
- invoking `/hyperagent-malware-analyze @sample.exe`

## Skill compatibility notes

The runtime skill model is now split:

- `/hyperagent-malware-analyze` remains the stable user-facing entrypoint
- that top-level skill now dispatches to narrower specialist skills under `/skill/`
- bootstrap installs the full skill tree so the dispatcher and specialist skills are available together

This is a compatibility-preserving migration. Do not remove or rename the top-level `/hyperagent-malware-analyze` alias casually.

## Security and privacy notes for operators

The repository is a malware-analysis toolchain, so operational hygiene matters:

- do not run uploaded or analyzed samples directly
- be cautious about where samples are written when `keep_file=True`
- avoid documenting local secrets in `config.yaml`; use the template-driven config surface instead
- remember that dashboard/API run data may contain file paths and analysis outputs in memory

## Common change hotspots

- Endpoint behavior or payload shape: `/api.py`, `/test/test_phase0_contract.py`
- Dashboard HTML, task grouping, or polling behavior: `/api.py`, `/test/test_api_dashboard.py`
- Upload persistence/cleanup behavior: `/api.py`
- Environment bootstrap behavior: `/bootstrap.ps1`
- Task/session semantics: `/core/result_models.py`, `/core/task_runtime.py`, `/core/pipeline_logger.py`

## Operational caveats

- The API layer does not add authentication, authorization, or persistent storage.
- The upload directory is local filesystem storage, not object storage.
- Background runs use `asyncio.create_task`, which is simple but tied to the process lifetime.
- Importing `api.py` constructs the orchestrator immediately, so missing local config/tool assumptions may surface early depending on environment.
- The new task board improves observability, but it is not a durable job-control system.
