# Phase 3d — engine/launcher.py + hyperagent/cli.py

Read `00-index.md` first for shared constraints and reference paths.
**Status:** ✅ Complete on 2026-08-15.
**Depends on 3a (pipeline_state/checkpoint), 3b (skills loader), 3c (subagent)
being done first** — this phase wires all three together.

## Progress update

Implemented:
- `hyperagent/engine/launcher.py` with SDK stage orchestration, state/resume handling,
  state-drift detection, fail-on-no-checkpoint handling, per-stage model selection,
  ablation hooks (`skip_stages`, `cache_enabled`, `injection_guard`,
  `checkpoint_enabled`), and the Phase 4-ready dynamic-stage VM auto-revert hook.
- `hyperagent/cli.py` with `analyze` and Phase 5-stubbed `batch` subcommands.
- `hyperagent/tests/test_launcher.py` covering skip, resume, state drift, and
  missing state-transition failure cases.
- Provider/injection-loop plumbing needed by 3d:
  - provider-level cache toggle support
  - launcher-owned checkpoint persistence via raised `CheckpointReached`
  - optional injection-guard suppression for ablation mode

Validation completed:
- `python -m pytest hyperagent/tests/ -q` → `101 passed, 3 skipped`
- `python -m hyperagent.cli --help` ✅
- `python -m hyperagent.cli analyze --help` ✅

Notes:
- `run_pipeline_with_config(...)` is async to match `experiments/ablation_runner.py`.
- `batch` intentionally remains `NotImplementedError("Phase 5")` until Phase 5 lands.
- Full end-to-end sample execution against live MCP/VM tooling is still a follow-up
  runtime validation step, not part of the unit-test-only completion evidence here.

---


## Goal

Port the 9-stage pipeline driver from `claude_spawn.py` (which shells out to
the Claude Code CLI per stage) into a pure-SDK driver that calls
`AgentLoop.run()` directly, in-process, per stage — using the tool subset
from `tools/registry.py::get_tools_for_stage()` and the skill instructions
from `skills/registry.py::load_stage_skill()`.

## Files to create

### `hyperagent/engine/launcher.py` [NEW]

Core loop, adapted from `claude_spawn.py` lines ~140-283 (read that file's
`run_pipeline`-equivalent function directly — don't guess at its shape from
this doc alone, the exact retry/state-drift branches matter):

```python
STAGES = [
    Stage("01-prepare-env",  "hyperagent-prepare-env", reads_sample_content=False),
    Stage("02-static-pass1", "hyperagent-static",      reads_sample_content=True),
    Stage("03-unpack",       "hyperagent-unpack",      reads_sample_content=True),
    Stage("04-static-pass2", "hyperagent-static",      reads_sample_content=True),
    Stage("05-dynamic",      "hyperagent-dynamic",     reads_sample_content=True),
    Stage("06-intel",        "hyperagent-intel",       reads_sample_content=True),
    Stage("07-deepdive",     "hyperagent-deepdive",    reads_sample_content=True),
    Stage("08-report",       "hyperagent-report",      reads_sample_content=False),
    Stage("09-summary",      "hyperagent-summary",     reads_sample_content=False),
]

def run_pipeline_with_config(
    sample_path: Path,
    config: HyperAgentConfig,
    ablation_config: AblationConfig | None = None,
    run_id: str | None = None,
) -> RunMetrics:
    """Signature matches what experiments/ablation_runner.py imports as run_fn
    (see 00-index.md — AblationRunner already calls this exact import path)."""
```

Behavior to port from `claude_spawn.py`:
- Per stage: `pipeline_state.load_state()` → check `entry["status"]`.
  - `completed` + artifact still valid at recorded/default output path →
    skip (log `[i/9] Skipping ...`).
  - `completed` but artifact missing/invalid → state drift, stop, return
    failure `RunMetrics`.
  - otherwise → attempt loop bounded by `config.max_stage_attempts` (default
    20, from `HyperAgentConfig.max_stage_attempts` in `config.py`), calling
    `AgentLoop.run(...)` each attempt instead of subprocess.
- After each attempt: re-read STATE.json.
  - `running` (checkpointed) → loop again (resume), up to the attempt cap.
  - `completed` + valid artifact → break out, move to next stage.
  - `completed` but invalid artifact → `pipeline_state.fail(...)`, stop.
  - neither → the stage didn't honor the checkpoint/complete contract →
    `pipeline_state.fail(...)`, stop (mirrors `claude_spawn.py`'s "exited 0
    without checkpointing or completing" branch).
- **Ablation hooks** (this is new vs. `claude_spawn.py`, which has none):
  - `ablation_config.skip_stages` → skip listed stage_ids entirely (mark
    `pipeline_state` state as skipped/completed-stub or just literally
    `continue` past them — pick whichever `AblationRunner`'s metrics
    consumer expects; check `experiments/ablation_runner.py` for how it
    reads `RunMetrics` before deciding).
  - `ablation_config.isolated_subagents` → passed through to any
    `spawn_subagent()` calls a stage makes (only relevant once stages
    actually use subagents — for now just thread the flag through).
  - `ablation_config.cache_enabled` → thread through to whatever prompt
    caching the provider layer does (check `providers/anthropic_provider.py`
    for an existing cache_control toggle before adding a new one).
  - `ablation_config.injection_guard` → maps directly to
    `reads_sample_content and anonymize` params already on
    `engine/injection_guard.py::build_system_prompt()` — when
    `injection_guard=False`, force `reads_sample_content=False` for the
    guard-prompt append (see `injection_guard.py` lines 96-98) even though
    the stage's own `reads_sample_content` may be `True`; don't disable
    anonymization at the same time unless `AblationConfig` says so explicitly.
  - `ablation_config.checkpoint_enabled` → when `False`, construct the
    stage's `AgentLoop`/`ContextTracker` with a `checkpoint_threshold` of
    `1.0` (or otherwise bypass `CheckpointReached`) so the stage never
    self-interrupts.
- **VM auto-revert hook**: after the `05-dynamic` stage's attempt loop exits
  (success or failure — safety hook must run either way per Phase 4's
  Gap #3), call the hook Phase 4 will add at
  `tools/vmware_tools.py::vm_auto_revert_after_dynamic(config.vmware)`. If
  Phase 4 hasn't landed yet when you write this, stub the call behind
  `if hasattr(vmware_tools, "vm_auto_revert_after_dynamic")` or leave a
  `# TODO(phase-4)` — don't block 3d on 4.
- **Per-stage model selection (Open Item O4)**: read
  `config.provider.stage_models.get(stage.stage_id, config.provider.model)`
  when constructing the provider/`AgentLoop` for each stage.

### `hyperagent/cli.py` [NEW]

```bash
hyperagent analyze <sample.exe>
hyperagent analyze <sample.exe> --stage 01-prepare-env
hyperagent analyze <sample.exe> --provider anthropic --model claude-opus-4-5
hyperagent batch <samples_dir> --output-dir experiments/results
```
Use `argparse` (already used in `claude_spawn.py`, matches project style —
`click`/`typer` are not current dependencies, don't add one for this).
`analyze` calls `run_pipeline_with_config` for a single stage (via a
`--stage` filter on the `STAGES` list) or the full pipeline.
`batch` is a thin wrapper deferred to Phase 5's `BatchEvaluator` — a stub
that raises `NotImplementedError("Phase 5")` is acceptable here if Phase 5
hasn't landed yet.
Register as a console script in `pyproject.toml`:
```toml
[project.scripts]
hyperagent = "hyperagent.cli:main"
```

## Exit criteria

```bash
python -m hyperagent.cli analyze --stage 01-prepare-env <sample.exe>  # single stage completes via SDK
# Force a low checkpoint_threshold (e.g. HYPERAGENT_CHECKPOINT_THRESHOLD=0.01) and confirm:
#   - _state/<stage_id>.progress.md gets written
#   - STATE.json shows status=running with progress_path set
#   - re-running the same command resumes instead of restarting from scratch
python -m hyperagent.cli analyze <sample.exe>  # full 9-stage pipeline on a known sample -> STATE.json all 'completed'
python -m pytest hyperagent/tests/ -q  # 70+ still pass
```
Add `hyperagent/tests/test_launcher.py` — mock `AgentLoop.run` and
`pipeline_state` calls, assert the state-machine transitions above (skip,
resume, state-drift-stop, fail-on-no-checkpoint) without needing a live
LLM/VM.
