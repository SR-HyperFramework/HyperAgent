# Phase 3a — pipeline_state.py + checkpoint.py

Read `00-index.md` first for shared constraints and reference paths.

## Goal

Give the pipeline a real `STATE.json` read/write helper and make
`engine/checkpoint.py` actually persist progress instead of being a
pure in-memory threshold check. This unblocks 3d (launcher), which needs
both to resume stages across process restarts.

## Current state

- `hyperagent/engine/checkpoint.py` exists today with only `CheckpointReached`
  (exception carrying `tokens`/`ratio`) and `ContextTracker` (estimates tokens,
  raises when over threshold). It does **not** write any file or call any
  state helper — that's what's missing.
- No `hyperagent/pipeline_state.py` exists yet.
- A v3 reference implementation of the state helper (STATE.json init/read/
  checkpoint/complete/fail, keyed by `stage_id`) lives at:
  `skill/backup/hyperagent-malware-analyze/v3/_hyperagent-common/scripts/pipeline_state.py`
  — read it first, adapt (don't blindly copy — v3 was a standalone script
  invoked via `python pipeline_state.py ...` CLI args; v4 needs it as an
  importable module with a clean function API).

## Files to create/modify

### `hyperagent/pipeline_state.py` [NEW]

Public API (per `implementation_plan.md` Phase 3):
```python
def ensure_state(report_dir: Path, sample_sha256: str, input_path: str) -> None: ...
def load_state(report_dir: Path) -> dict: ...
def checkpoint(report_dir: Path, stage_id: str, progress_path: str, recommend_reason: str = "") -> None: ...
def complete(report_dir: Path, stage_id: str, output_path: str, recommend_reason: str = "") -> None: ...
def fail(report_dir: Path, stage_id: str, reason: str) -> None: ...
def state_path_for(report_dir: Path) -> Path: ...
def default_output_path(report_dir: Path, stage_id: str) -> str | None: ...
def resolve_recorded_path(report_dir: Path, output_path: str) -> str: ...
```
STATE.json shape (mirror v3, keyed by the 9 stage_ids from `00-index.md`):
```json
{
  "sample_sha256": "...",
  "input_path": "...",
  "stages": {
    "01-prepare-env": {"status": "pending|running|completed|failed", "output_path": null, "progress_path": null, "error": null}
  }
}
```
Use `json.dump`/`json.load` directly — no new dependency needed. Write
atomically (write to `.tmp` then `os.replace`) since the launcher (3d) reads
this file right after subprocess/agent completion and a torn write would
corrupt resume state.

### `hyperagent/engine/checkpoint.py` [MODIFY]

Keep `CheckpointReached` and `ContextTracker` as-is (they're used correctly
by `agent_loop.py` already — don't break that contract). Add:
```python
def write_checkpoint(
    report_dir: Path,
    stage_id: str,
    progress_summary: str,
    recommend_reason: str = "",
) -> Path:
    """Write `_state/<stage_id>.progress.md` and call pipeline_state.checkpoint().
    Returns the progress file path written."""
```
This should be called from `engine/agent_loop.py::_checkpoint_response` (or
by the launcher after catching `CheckpointReached` — pick whichever keeps
`agent_loop.py`'s existing signature stable; prefer calling it from the
launcher in 3d since `agent_loop.py` currently has no `report_dir`/`stage_id`
path context, only a bare `stage_id: str = "unknown"` label). Document your
choice in a one-line comment only if the reasoning is non-obvious.

## Exit criteria

```bash
python -m pytest hyperagent/tests/test_tools.py hyperagent/tests/test_providers.py -v  # still pass
python -c "
from pathlib import Path
from hyperagent import pipeline_state
import tempfile
d = Path(tempfile.mkdtemp())
pipeline_state.ensure_state(d, 'abc123', 'sample.exe')
pipeline_state.checkpoint(d, '01-prepare-env', str(d / '_state/01-prepare-env.progress.md'), 'test')
state = pipeline_state.load_state(d)
assert state['stages']['01-prepare-env']['status'] == 'running'
pipeline_state.complete(d, '01-prepare-env', str(d / '01-prepare-env.json'))
state = pipeline_state.load_state(d)
assert state['stages']['01-prepare-env']['status'] == 'completed'
print('OK')
"
```

Add `hyperagent/tests/test_pipeline_state.py` and
`hyperagent/tests/test_checkpoint.py` covering: `ensure_state` is idempotent
(second call doesn't wipe existing stage statuses), `checkpoint` sets status
to `running` and records `progress_path`, `complete` sets status to
`completed` and records `output_path`, `fail` sets status to `failed` and
records `error`.
