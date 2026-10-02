---
type: reference
title: State Management and STATE.json Contract
description: Canonical STATE.json document structure, stage table, status semantics, and atomic mutations.
tags: [state, orchestration, contract]
---

# State Management and STATE.json Contract

## STATE.json Overview

STATE.json is the single source of truth for pipeline run state. It is owned and managed by the `pipeline_state.py` module and is consulted by the orchestrator at every stage transition.

## STATE.json Structure

```json
{
  "schema_version": "1.0",
  "run_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "file_path": "/absolute/path/to/sample.exe",
  "sha256": "abcd1234ef5678...",
  "created_at": "2026-01-15T10:30:00Z",
  "updated_at": "2026-01-15T10:45:00Z",
  "stages": [
    {
      "stage_id": "01-prepare-env",
      "skill": "hyperagent-prepare-env",
      "status": "completed",
      "recommend_next_stage": "run_next",
      "artifact_path": "reports/abcd1234.../01-prepare-env.json",
      "started_at": "2026-01-15T10:30:05Z",
      "finished_at": "2026-01-15T10:31:00Z",
      "error": null
    },
    {
      "stage_id": "02-static-pass1",
      "skill": "hyperagent-static",
      "status": "running",
      "recommend_next_stage": "resume_current",
      "artifact_path": "reports/abcd1234.../02-static-pass1.json",
      "started_at": "2026-01-15T10:31:05Z",
      "finished_at": null,
      "error": null
    }
  ]
}
```

## Field Reference

### Top-Level Fields

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | string | VERSION of STATE.json schema (currently "1.0") |
| `run_id` | UUID | Unique identifier for this analysis run |
| `file_path` | string | Absolute path to analyzed sample |
| `sha256` | string | Sample SHA256 hash |
| `created_at` | ISO8601 | When run was created |
| `updated_at` | ISO8601 | When STATE.json was last updated |
| `stages` | array | Stage entry objects (see below) |

### Stage Entry Fields

| Field | Type | Values | Description |
|-------|------|--------|-------------|
| `stage_id` | string | 01-prepare-env through 09-summary | Stage identifier |
| `skill` | string | hyperagent-{name} | Associated skill |
| `status` | string | pending &#124; running &#124; completed | Current status |
| `recommend_next_stage` | string | run_next &#124; resume_current &#124; retry_stage &#124; pipeline_complete | Next action for orchestrator |
| `artifact_path` | string | reports/{sha256}/{stage_id}.json | Output artifact path |
| `started_at` | ISO8601 &#124; null | Timestamp | When stage execution began |
| `finished_at` | ISO8601 &#124; null | Timestamp | When stage execution ended |
| `error` | string &#124; null | Error message | Error description (if failed) |

## Status Semantics

### pending
- **Meaning**: Stage has not yet started
- **Set By**: Orchestrator during STATE.json initialization
- **Transitions To**: running (when orchestrator invokes stage)

### running
- **Meaning**: Stage is executing or was checkpointed at ≥80% context
- **Set By**: Stage entry (as it starts) OR stage checkpoint (as context limit approaches)
- **Transitions To**: completed (on success) OR pending (if checkpoint and resumption needed)
- **Progress File**: `_state/{STAGE_ID}.progress.md` exists during running status

### completed
- **Meaning**: Stage finished successfully; artifact is available and validated
- **Set By**: Orchestrator after successful execution and schema validation
- **Transitions To**: (terminal state; no transitions)
- **Artifact**: Guaranteed to exist and pass validation

## recommend_next_stage Values

### run_next
- **Meaning**: Current stage completed successfully; proceed to next logical stage
- **Set By**: Stage's output artifact
- **Orchestrator Action**: Find next stage in sequence and execute it

### resume_current
- **Meaning**: Current stage was checkpointed; resume from progress file
- **Set By**: Stage's checkpoint mechanism (when context limit reached)
- **Orchestrator Action**: Re-invoke same stage with progress file path; stage resumes from checkpoint

### retry_stage
- **Meaning**: Current stage failed; retry from beginning
- **Set By**: Stage's error handling (if recoverable error encountered)
- **Orchestrator Action**: Re-invoke same stage from beginning (no progress file)

### pipeline_complete
- **Meaning**: Analysis complete; terminate pipeline
- **Set By**: Final stage (09-summary)
- **Orchestrator Action**: Terminate; move result to archive

## Stage Table (canonical)

The orchestrator refers to a canonical stage table defined in `pipeline_state.py`:

```python
STAGES = [
    ("01-prepare-env", "hyperagent-prepare-env"),
    ("02-static-pass1", "hyperagent-static"),
    ("03-unpack", "hyperagent-unpack"),
    ("04-static-pass2", "hyperagent-static"),
    ("05-dynamic", "hyperagent-dynamic"),
    ("06-intel", "hyperagent-intel"),
    ("07-deepdive", "hyperagent-deepdive"),
    ("08-report", "hyperagent-report"),
    ("09-summary", "hyperagent-summary"),
]
```

This table defines the **canonical ordering** and **skill-to-stage mapping**. Any deviation in STATE.json is detected and flagged as a drift.

## Atomic State Mutations

To prevent consistency corruption, all updates to STATE.json follow a strict pattern:

```python
def update_stage_status(state_path: str, stage_id: str, new_status: str):
    """Atomically update stage status in STATE.json."""
    
    # 1. Read entire STATE
    with open(state_path, 'r') as f:
        state = json.load(f)
    
    # 2. Validate new state is valid
    stage_entry = find_stage(state, stage_id)
    if not is_valid_transition(stage_entry['status'], new_status):
        raise RuntimeError(f"Invalid transition: {stage_entry['status']} → {new_status}")
    
    # 3. Mutate
    stage_entry['status'] = new_status
    stage_entry['updated_at'] = datetime.now().isoformat()
    
    # 4. Write atomically (temp file + rename)
    temp_path = state_path + '.tmp'
    with open(temp_path, 'w') as f:
        json.dump(state, f, indent=2)
    os.rename(temp_path, state_path)  # Atomic rename
```

**Guarantees**:
- No partial writes (temp file + atomic rename)
- No race conditions (orchestrator holds lock)
- No lost updates (full state read-modify-write)

## Conditional Stage Skipping

Some stages may be skipped based on findings or environment:

```python
def get_next_stage(state: dict) -> tuple[str, str] | None:
    """Determine next stage to execute."""
    
    # Find last completed stage
    last_completed = None
    for stage in state['stages']:
        if stage['status'] == 'completed':
            last_completed = stage
    
    # Decide next stage based on findings
    if last_completed['stage_id'] == '02-static-pass1':
        pass1_findings = load_artifact(last_completed['artifact_path'])
        if should_unpack(pass1_findings):
            return ('03-unpack', 'hyperagent-unpack')
        else:
            # Skip unpack, go to static pass 2
            return ('04-static-pass2', 'hyperagent-static')
    
    # Default: next in sequence
    last_index = STAGES.index((last_completed['stage_id'], ...))
    return STAGES[last_index + 1]
```

## State Validation

The `validate_pipeline.py` script performs end-to-end validation:

```python
def validate_state(state_path: str):
    """Validate STATE.json consistency."""
    
    state = load_json(state_path)
    
    # 1. Schema compliance
    if not validate_json_schema(state, STATE_SCHEMA):
        raise ValueError("STATE.json schema mismatch")
    
    # 2. Stage sequencing
    actual_stage_ids = [s['stage_id'] for s in state['stages']]
    expected_stage_ids = [stage_id for stage_id, _ in STAGES]
    if actual_stage_ids != expected_stage_ids:
        raise ValueError(f"Stage sequencing mismatch: {actual_stage_ids} != {expected_stage_ids}")
    
    # 3. Status transitions
    for stage in state['stages']:
        if not is_valid_status(stage['status']):
            raise ValueError(f"Invalid status: {stage['status']}")
    
    # 4. Artifact existence
    for stage in state['stages']:
        if stage['status'] == 'completed':
            artifact_path = stage['artifact_path']
            if not os.path.exists(artifact_path):
                raise ValueError(f"Missing artifact: {artifact_path}")
    
    # 5. Artifact schema validation
    for stage in state['stages']:
        if stage['status'] == 'completed':
            artifact_path = stage['artifact_path']
            schema_path = f"~/.claude/skills/{stage['skill']}/schema.json"
            if not artifact_is_valid(artifact_path, schema_path):
                raise ValueError(f"Artifact fails schema validation: {artifact_path}")
    
    return True
```

## Progress File Integration

When a stage checkpoints (≥80% context usage):

1. Stage creates `_state/{STAGE_ID}.progress.md` with intermediate results
2. Stage updates STATE.json: `status: running`, `recommend_next_stage: resume_current`
3. Stage exits cleanly (no error)
4. Orchestrator detects `status: running` on next invocation
5. Orchestrator passes progress file path via `HYPERAGENT_PROGRESS_PATH` env var
6. Stage resumes from progress file instead of restarting

## Drift Detection

The orchestrator detects state drift and classifies runs:

```python
def classify_run(state: dict) -> str:
    """Classify run as finished, resumable, or drifted."""
    
    try:
        # Validate schema and sequencing
        validate_state(state)
    except ValueError as e:
        return "drifted"  # Schema or sequencing error
    
    # Check if final stage completed
    final_stage = state['stages'][-1]
    if final_stage['status'] == 'completed':
        return "finished"  # Analysis complete
    
    # Check if any stage is running or recommend_resume
    for stage in state['stages']:
        if stage['status'] == 'running' or stage['recommend_next_stage'] == 'resume_current':
            return "resumable"  # Can continue from checkpoint
    
    return "drifted"  # Inconsistent state
```

## Related Documentation

- [Launcher](./launcher.md) — Orchestrator that reads/writes STATE.json
- [Pipeline Controller](./pipeline-controller.md) — hyperagent-progress skill that classifies runs
- [Architecture Overview](../architecture/overview.md) — System design
- [Pipeline Details](../architecture/pipeline.md) — Stage-by-stage breakdown

