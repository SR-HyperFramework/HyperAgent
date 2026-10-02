---
type: reference
title: Pipeline Controller (hyperagent-progress)
description: Operator-facing tool for discovering runs, classifying status, and resuming interrupted analyses.
tags: [orchestration, operator, pipeline-controller]
---

# Pipeline Controller (hyperagent-progress)

## Overview

`hyperagent-progress` is a Claude Code skill that serves as the **primary operator entry point** for managing ongoing analyses. It discovers STATE.json files, classifies runs, and provides a triage interface for resuming interrupted work.

## Invocation

```bash
# Discover and manage runs
claude -p '/hyperagent-progress'

# With directory override
HYPERAGENT_ANALYSIS_DIR=/path/to/reports claude -p '/hyperagent-progress'
```

## Workflow

### 1. Discovery

The skill recursively discovers all STATE.json files under the reports/ directory:

```
reports/
├── abcd1234.../
│   ├── STATE.json
│   ├── 01-prepare-env.json
│   ├── 02-static-pass1.json
│   └── ...
├── efgh5678.../
│   ├── STATE.json
│   └── ...
```

### 2. Classification

Each STATE.json is classified into one of three categories:

| Category | Condition | Action |
|----------|-----------|--------|
| **finished** | Final stage (09-summary) has status="completed" | Display as archived; no resumption needed |
| **resumable** | Any stage has status="running" OR recommend_next_stage="resume_current" | Candidate for automatic resumption |
| **drifted** | STATE.json format mismatch or schema validation fails | Requires manual investigation |

### 3. Ranking

Resumable runs are sorted by recency (most recent first) using created_at or updated_at timestamp.

### 4. Display

The skill displays a summary table:

```
Resumable Runs (sorted by recency):
┌─────────────────────────────────────────────────────────────────────┐
│ RUN_ID (SHA256)           │ FILE             │ STAGE        │ TIME  │
├─────────────────────────────────────────────────────────────────────┤
│ abcd1234...               │ sample.exe       │ 05-dynamic   │ 2 hrs │
│ efgh5678...               │ malware.dll      │ 02-static-p2 │ 5 hrs │
└─────────────────────────────────────────────────────────────────────┘

Finished Runs (archived):
┌─────────────────────────────────────────────────────────────────────┐
│ RUN_ID (SHA256)           │ FILE             │ VERDICT      │       │
├─────────────────────────────────────────────────────────────────────┤
│ ijkl9999...               │ sample_clean.exe │ benign       │ 1 day │
└─────────────────────────────────────────────────────────────────────┘

Drifted Runs (require investigation):
None
```

### 5. Auto-Resume

By default, hyperagent-progress auto-resumes the most-recent resumable run by delegating to claude_spawn.py launcher:

```bash
python claude_spawn.py --resume /path/to/reports/{sha256}/STATE.json
```

The skill:
1. Identifies the most-recent resumable run
2. Loads its STATE.json
3. Determines current stage and status
4. Invokes claude_spawn.py with --resume flag
5. Monitors resumption progress

### 6. Summary Display

Before resuming, the skill displays a summary of pending work:

```
Resuming: abcd1234... (sample.exe)
Current Stage: 05-dynamic
Artifacts Found: 3
Findings Extracted: 15
Next Recommended Actions:
  - Continue dynamic behavior capture
  - Extract network IOCs
  - Prepare for deepdive analysis
```

## STATE Classification Logic

### Finished

```python
def is_finished(state: dict) -> bool:
    """Classify run as finished if final stage completed."""
    stages = state.get("stages", [])
    if not stages:
        return False
    
    final_stage = stages[-1]  # 09-summary
    return final_stage.get("status") == "completed"
```

### Resumable

```python
def is_resumable(state: dict) -> bool:
    """Classify run as resumable if any stage is running or recommend_next_stage suggests resume."""
    stages = state.get("stages", [])
    for stage in stages:
        status = stage.get("status")
        recommend = stage.get("recommend_next_stage")
        
        if status == "running":
            return True
        if recommend == "resume_current":
            return True
    
    return False
```

### Drifted

```python
def is_drifted(state: dict) -> bool:
    """Classify run as drifted if schema validation fails or inconsistencies detected."""
    try:
        # Validate STATE.json schema version
        schema_version = state.get("schema_version")
        if schema_version != "1.0":
            return True
        
        # Validate stage sequencing
        stages = state.get("stages", [])
        if len(stages) == 0:
            return True
        
        # Check for orphaned artifacts
        expected_stage_ids = [s.stage_id for s in STAGES]
        actual_stage_ids = [s.get("stage_id") for s in stages]
        if actual_stage_ids != expected_stage_ids:
            return True
        
        return False
    except:
        return True
```

## Entrypoints & Use Cases

### Use Case 1: Check Run Status

Operator wants to know which runs are ongoing and which are complete.

```bash
claude -p '/hyperagent-progress'
```

Output shows:
- Resumable runs with current stage
- Finished runs with verdict
- Drifted runs requiring investigation

### Use Case 2: Resume Most-Recent Run

Operator was interrupted and wants to continue analysis on the most-recent run.

```bash
claude -p '/hyperagent-progress'
# Skill auto-resumes most-recent resumable run
```

The skill automatically invokes claude_spawn.py to continue from the checkpoint.

### Use Case 3: Manually Select Run to Resume

Operator wants to resume a specific (non-most-recent) run.

```bash
claude -p '/hyperagent-progress'
# Skill displays list of resumable runs
# Operator selects run from list
claude -p '/hyperagent-progress resume {sha256}'
```

### Use Case 4: Investigate Drifted Run

Operator notices a run is marked as drifted and wants to understand why.

```bash
claude -p '/hyperagent-progress'
# Skill displays drifted runs list
# Operator inspects STATE.json and artifacts manually
```

## Integration with claude_spawn.py

hyperagent-progress delegates resumption to the main launcher:

```python
def resume_run(state_path: str):
    """Delegate to claude_spawn.py for resumption."""
    import subprocess
    
    # Invoke launcher with --resume flag
    result = subprocess.run(
        ["python", "claude_spawn.py", "--resume", state_path],
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        print(f"✓ Run resumed successfully")
        print(f"Output:\n{result.stdout}")
    else:
        print(f"✗ Resumption failed")
        print(f"Error:\n{result.stderr}")
```

The launcher:
1. Loads STATE.json from the provided path
2. Identifies the "running" stage
3. Resumes from progress checkpoint (if present)
4. Continues with subsequent stages
5. Updates STATE.json as stages complete

## Configuration

### Analysis Directory

**Env Var**: `HYPERAGENT_ANALYSIS_DIR`  
**Default**: `./reports/`  
**Usage**: Root directory where STATE.json files are stored

### Recurse Depth

The skill recursively searches for STATE.json files up to a reasonable depth (typically 3-4 levels) to avoid searching unnecessary directories.

## Return Values

The skill returns a structured result:

```json
{
  "total_runs": 5,
  "resumable": [
    {
      "run_id": "abcd1234...",
      "file_path": "sample.exe",
      "current_stage": "05-dynamic",
      "status": "running",
      "last_updated": "2026-01-15T10:45:00Z",
      "time_elapsed": "2 hours"
    }
  ],
  "finished": [
    {
      "run_id": "ijkl9999...",
      "file_path": "sample_clean.exe",
      "final_verdict": "benign",
      "completed_at": "2026-01-14T16:30:00Z"
    }
  ],
  "drifted": [
    {
      "run_id": "mnop1111...",
      "issue": "schema_mismatch",
      "details": "Expected schema_version 1.0, found 0.9"
    }
  ],
  "resumed_run": "abcd1234..."  // Most-recent resumable run
}
```

## Reliability and Error Handling

### Missing STATE.json

If STATE.json is missing but artifacts exist, the skill logs a warning and skips the run.

### Corrupted STATE.json

If STATE.json fails JSON parsing, the skill marks the run as drifted and skips resumption.

### Permission Errors

If the skill cannot read STATE.json or access artifacts, it logs an error and continues with other runs.

### Resumption Failure

If claude_spawn.py fails to resume, the skill:
1. Displays error details
2. Does NOT modify STATE.json
3. Suggests manual intervention

## Integration Points

- **claude_spawn.py**: Receives --resume flag to continue from checkpoint
- **pipeline_state.py**: Relies on stage table and status semantics
- **STATE.json**: Reads and classifies run status
- **Artifacts**: Inspects artifact paths and timestamps
- **Progress files**: Checks for `_state/{STAGE_ID}.progress.md`

## Related Documentation

- [Launcher (claude_spawn.py)](./launcher.md) — Main orchestrator; receives --resume flag
- [State Management](./state-management.md) — STATE.json contract and semantics
- [Architecture Overview](../architecture/overview.md) — System design

