---
type: reference
title: Error Recovery and Failure Handling
description: Failure states, error classification, MAX_STAGE_ATTEMPTS safety cap, and manual recovery procedures.
tags: [orchestration, error-recovery, reliability]
---

# Error Recovery and Failure Handling

## Failure States

A stage can transition to the following terminal states:

| State | Meaning | Recovery Action | Example |
|-------|---------|-----------------|---------|
| **success** | Stage completed normally | Proceed to next stage | Stage 02 finished static analysis |
| **failed** | Stage encountered unrecoverable error | Mark pipeline as failed | IDA Pro crashed |
| **skipped** | Stage was intentionally bypassed | Proceed to next stage | Dynamic skipped (no VM available) |
| **running** | Stage checkpointed due to context ≥80% | Retry stage with progress file | Static pass 1 ran out of context |
| **cancelled** | Stage was manually terminated | Manual operator intervention | Operator killed stage |

## MAX_STAGE_ATTEMPTS Safety Cap

The orchestrator prevents infinite loops via `MAX_STAGE_ATTEMPTS = 20`:

```python
MAX_STAGE_ATTEMPTS = 20

def run_pipeline(file_path: str):
    """Run pipeline with safety cap on retries."""
    
    stage_attempts = {}  # stage_id → attempt_count
    
    while True:
        # Get next stage from STATE.json
        next_stage = get_next_stage()
        if next_stage is None:
            break  # Pipeline complete
        
        stage_id = next_stage.stage_id
        
        # Check attempt count
        if stage_attempts.get(stage_id, 0) >= MAX_STAGE_ATTEMPTS:
            raise RuntimeError(
                f"Stage {stage_id} exceeded MAX_STAGE_ATTEMPTS ({MAX_STAGE_ATTEMPTS}). "
                f"Possible infinite loop detected. Aborting pipeline."
            )
        
        # Increment attempt counter
        stage_attempts[stage_id] = stage_attempts.get(stage_id, 0) + 1
        
        # Execute stage
        result = execute_stage(stage_id, file_path)
        
        # Handle result
        if result.success:
            update_state(stage_id, status="completed")
        elif result.recommend_resume:
            # Checkpointing scenario; will retry with progress file
            update_state(stage_id, status="running")
        else:
            # Failure
            update_state(stage_id, status="failed")
            break
```

**Scenario**: A stage that keeps checkpointing without making progress:
1. First attempt: Runs to 80% context, checkpoints, exits
2. Resume attempt 1: Runs from checkpoint, reaches 85% context, checkpoints again
3. Resume attempt 2-19: Same pattern repeats
4. Resume attempt 20: Would trigger MAX_STAGE_ATTEMPTS error

This safety cap prevents:
- Infinite retry loops
- Runaway resource consumption
- Operator confusion (why hasn't pipeline finished?)

## Error Classification

Errors are classified by source and recovery strategy:

### Environment Errors ([ENV-ERR])

**Cause**: Missing or misconfigured external tools

```python
def classify_environment_error(error: Exception) -> tuple[str, str]:
    """Classify environment error and suggest recovery."""
    error_msg = str(error)
    
    if "IDA Pro not found" in error_msg:
        return ("[STATIC-ENV-ERR]", "skip_to_pass2_or_dynamic")
    
    if "x64dbg server not running" in error_msg:
        return ("[DYN-ENV-ERR]", "skip_to_intel")
    
    if "VMware not accessible" in error_msg:
        return ("[DYN-ENV-ERR]", "skip_dynamic_continue_to_intel")
    
    if "VirusTotal API key invalid" in error_msg:
        return ("[INTEL-ENV-ERR]", "skip_intel_continue_to_deepdive")
    
    return (None, None)
```

**Examples**:
- `[STATIC-ENV-ERR]`: IDA Pro not installed → skip static pass 1, try pass 2
- `[DYN-ENV-ERR]`: VMware snapshot unavailable → skip dynamic, continue to intel
- `[INTEL-ENV-ERR]`: VirusTotal API key missing → skip intel, continue to deepdive

### Parsing Errors ([PARSE-ERR])

**Cause**: Input data doesn't match expected format

```python
def classify_parsing_error(error: Exception) -> tuple[str, str]:
    """Classify parsing error and suggest recovery."""
    error_msg = str(error)
    
    if "Invalid PE header" in error_msg:
        return ("[PARSE-ERR]", "retry_stage_or_fail")
    
    if "JSON schema validation failed" in error_msg:
        return ("[PARSE-ERR]", "retry_stage_or_fail")
    
    if "Malformed disassembly output" in error_msg:
        return ("[PARSE-ERR]", "retry_stage_or_fail")
    
    return (None, None)
```

**Examples**:
- Invalid PE header → Try to analyze anyway, or fail if unrecoverable
- Corrupted unpacked artifact → Retry unpacking, or mark artifact as partially invalid

### Timeout Errors ([TIMEOUT-ERR])

**Cause**: Operation exceeded time limit

```python
def classify_timeout_error(error: Exception) -> tuple[str, str]:
    """Classify timeout and suggest recovery."""
    error_msg = str(error)
    
    if "context limit exceeded" in error_msg:
        return ("[TIMEOUT-ERR]", "checkpoint_and_resume")
    
    if "execution timeout (60s)" in error_msg:
        return ("[TIMEOUT-ERR]", "kill_process_continue")
    
    if "MCP server startup timeout" in error_msg:
        return ("[TIMEOUT-ENV-ERR]", "retry_mcp_or_skip")
    
    return (None, None)
```

**Examples**:
- Context ≥80% during analysis → Checkpoint and resume
- Process hangs for 60s during dynamic → Kill process, continue
- MCP server takes >180s to start → Retry startup, or skip stage

## Recovery Strategies

### 1. Retry Stage (retry_stage)

Restart the stage from beginning without progress file:

```python
def retry_stage(stage_id: str, file_path: str, attempt_number: int = 1):
    """Retry stage from scratch."""
    
    if attempt_number > 3:
        raise RuntimeError(f"Stage {stage_id} failed after 3 retries")
    
    print(f"[*] Retrying stage {stage_id} (attempt {attempt_number}/3)")
    
    # Clear progress file
    progress_path = f"_state/{stage_id}.progress.md"
    if os.path.exists(progress_path):
        os.remove(progress_path)
    
    # Re-invoke stage without HYPERAGENT_PROGRESS_PATH
    result = execute_stage(stage_id, file_path)
    
    return result
```

### 2. Checkpoint and Resume (checkpoint_and_resume)

Exit cleanly at ≥80% context; resume on next invocation:

```python
def checkpoint_stage(stage_id: str, partial_results: dict):
    """Checkpoint intermediate results and exit."""
    
    # Write progress file
    progress_path = f"_state/{stage_id}.progress.md"
    with open(progress_path, 'w') as f:
        json.dump({
            "stage_id": stage_id,
            "checkpoint_time": datetime.now().isoformat(),
            "partial_results": partial_results,
            "resume_context": {...}
        }, f)
    
    # Update STATE.json
    state = load_state()
    state["stages"][stage_id]["status"] = "running"
    state["stages"][stage_id]["recommend_next_stage"] = "resume_current"
    save_state(state)
    
    # Exit cleanly (orchestrator will detect resume)
    sys.exit(0)
```

### 3. Skip Stage (skip_stage)

Skip stage and proceed to next:

```python
def skip_stage(stage_id: str, reason: str):
    """Skip stage and continue pipeline."""
    
    print(f"[!] Skipping stage {stage_id}: {reason}")
    
    # Mark as skipped
    state = load_state()
    state["stages"][stage_id]["status"] = "completed"
    state["stages"][stage_id]["terminal_state"] = "skipped"
    state["stages"][stage_id]["skip_reason"] = reason
    
    # Recommend next stage
    state["stages"][stage_id]["recommend_next_stage"] = "run_next"
    
    save_state(state)
```

### 4. Fail Pipeline (fail_pipeline)

Terminate pipeline due to unrecoverable error:

```python
def fail_pipeline(stage_id: str, error: Exception):
    """Fail pipeline and report error."""
    
    print(f"[ERROR] Pipeline failed at stage {stage_id}: {error}")
    
    # Mark as failed
    state = load_state()
    state["stages"][stage_id]["status"] = "completed"
    state["stages"][stage_id]["terminal_state"] = "failed"
    state["stages"][stage_id]["error"] = str(error)
    state["stages"][stage_id]["error_type"] = type(error).__name__
    
    state["pipeline_state"]["terminal_state"] = "failed"
    state["pipeline_state"]["failure_reason"] = str(error)
    
    save_state(state)
    
    # Exit with error code
    sys.exit(1)
```

## Error Tagging Conventions

Stages report errors using standardized tags in log output:

| Tag | Meaning | Recovery | Example |
|-----|---------|----------|---------|
| `[STATIC-ENV-ERR]` | Static analysis environment missing | Skip or retry | IDA Pro not found |
| `[DYN-ENV-ERR]` | Dynamic analysis environment missing | Skip dynamic | VMware unavailable |
| `[INTEL-ENV-ERR]` | Intel stage environment missing | Skip intel | VirusTotal API invalid |
| `[PARSE-ERR]` | Input parsing failed | Retry or fail | Invalid PE header |
| `[TIMEOUT-ERR]` | Operation timed out | Checkpoint or kill | Context limit exceeded |
| `[SCHEMA-ERR]` | Output schema validation failed | Retry or fail | Missing required field |
| `[UNKNOWN-ERR]` | Unclassified error | Fail pipeline | Unexpected exception |

## Manual Operator Recovery

### 1. Inspect STATE.json

```json
{
  "stages": {
    "02-static-pass1": {
      "status": "completed",
      "terminal_state": "failed",
      "error": "IDA Pro initialization timeout",
      "error_type": "TimeoutError"
    }
  },
  "pipeline_state": {
    "terminal_state": "failed",
    "failure_reason": "IDA Pro initialization timeout"
  }
}
```

### 2. Determine Recovery Action

- **Environment error**: Fix tool or skip stage
- **Parsing error**: Inspect artifact, retry or fail
- **Timeout**: Increase timeout or checkpoint

### 3. Manually Update STATE.json

```bash
# Option 1: Skip failed stage and continue
# Edit STATE.json: terminal_state="skipped", recommend_next_stage="run_next"

# Option 2: Retry stage
# Delete progress file: rm _state/02-static-pass1.progress.md
# Reset state: terminal_state="pending"

# Option 3: Manually fix and resume
# E.g., install missing tool, then invoke claude_spawn.py again
```

### 4. Resume Pipeline

```bash
python claude_spawn.py <file_path>
```

The launcher will:
1. Load STATE.json
2. Detect current status
3. Resume from next pending or running stage
4. Continue to completion

## Partial Completion Scenarios

### Scenario: Dynamic stage hung and was killed

```
Status: Dynamic (05) timeout after 60s
Action: Kill process, move to intel
Recovery: Findings collected so far are preserved
Result: Continue to intel enrichment
```

### Scenario: Context limit reached in static-pass2

```
Status: Static-pass2 (04) at 85% context
Action: Checkpoint to progress file
Recovery: Resume on next invocation, continue from checkpoint
Result: Static pass 2 completes, findings merged
```

### Scenario: Unpacking failed, artifact corrupted

```
Status: Unpack (03) failed to extract payload
Action: Mark artifact as "extraction_failed"
Recovery: Skip pass 2, continue to dynamic with original
Result: Dynamic tests original; findings show packing
```

## Logging and Observability

Error logs are written to `pipeline_log.txt`:

```
[2026-01-15 10:35:00] Stage 02-static-pass1 starting...
[2026-01-15 10:35:15] Identified: NATIVE (PE64)
[2026-01-15 10:36:00] NativeAgent executing...
[2026-01-15 10:36:45] WARNING: Context usage at 82% (exceeded 80%)
[2026-01-15 10:36:46] CHECKPOINT: Writing progress file
[2026-01-15 10:36:47] Stage 02-static-pass1 paused (running)
[2026-01-15 10:37:00] resume: Stage 02-static-pass1 resuming from checkpoint...
[2026-01-15 10:37:30] Stage 02-static-pass1 completed
```

## Related Documentation

- [Launcher](./launcher.md) — Orchestrator that handles recovery
- [Execution Model](./execution-model.md) — Stage invocation and context management
- [State Management](./state-management.md) — STATE.json structure and mutations

