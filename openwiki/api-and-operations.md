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

## In-memory run tracking

Run state is stored in:

```python
RUNS: dict[str, dict[str, Any]] = {}
```

That means:

- state is per-process only
- restarting the API loses run history
- multiple worker processes will not share run data

This is adequate for local operator workflows and tests, but not durable job orchestration.

## Path vs upload execution

### Path-based execution

Path-based requests pass the existing file path into the orchestrator and use `source="path"` in the run record (`/api.py`).

### Upload-based execution

Upload requests stream the body to disk before analysis (`/api.py`):

- if `keep_file=True`, the file is stored under `uploads/` using `<upload_id>_<safe_name>`
- otherwise a temporary file is created and removed after execution

`HYPERAGENT_UPLOAD_DIR` can override the upload directory root (`/api.py`).

## Pipeline log propagation

`api.py` subscribes a listener to `PipelineLogger` so that run snapshots get live-ish pipeline updates while background work is running. The listener updates run status based on event states such as `started` and `failed`.

This coupling is why changes to `/core/pipeline_logger.py` can affect dashboard behavior.

## Dashboard

`_dashboard_html()` in `/api.py` returns a full HTML shell for the HyperAgent Workflow Dashboard. The tests verify that the UI includes:

- run lookup controls
- upload controls
- file picker affordances
- routes for upload and run polling

Source: `/api.py`, `/test/test_api_dashboard.py`

The dashboard is server-rendered as a string literal rather than built from templates or a frontend app bundle.

## Operational setup

The supported setup path is the PowerShell bootstrap script (`/bootstrap.ps1`). It performs several operations that matter operationally:

- checks for Python, Node.js, npm, Claude CLI, and `uv`
- creates `.venv`
- installs Python dependencies from `/requirements.txt`
- generates `config.yaml` from `/config.yaml.template`
- installs bundled Claude skill content
- installs a Claude plugin related to IDA workflows
- optionally activates idalib if an IDA installation is detected
- runs import/config verification unless `-SkipVerify` is passed

The script prints suggested next steps including:

- activating `.venv`
- starting `uvicorn api:app`
- running `python main.py <sample>`

## Security and privacy notes for operators

The repository is a malware-analysis toolchain, so operational hygiene matters:

- do not run uploaded or analyzed samples directly
- be cautious about where samples are written when `keep_file=True`
- avoid documenting local secrets in `config.yaml`; use the template-driven config surface instead
- remember that dashboard/API run data may contain file paths and analysis outputs in memory

## Common change hotspots

- Endpoint behavior or payload shape: `/api.py`, `/test/test_phase0_contract.py`
- Dashboard HTML or run polling behavior: `/api.py`, `/test/test_api_dashboard.py`
- Upload persistence/cleanup behavior: `/api.py`
- Environment bootstrap behavior: `/bootstrap.ps1`

## Operational caveats

- The API layer does not add authentication, authorization, or persistent storage.
- The upload directory is local filesystem storage, not object storage.
- Background runs use `asyncio.create_task`, which is simple but tied to the process lifetime.
- Importing `api.py` constructs the orchestrator immediately, so missing local config/tool assumptions may surface early depending on environment.
