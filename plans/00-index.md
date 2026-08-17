# HyperAgent v4 — Phase Plans Index

Split from `implementation_plan.md` so each phase can be picked up in a fresh,
low-context session without re-reading the whole roadmap. Read only the file
for the phase you're doing.

## Status (as of 2026-08-15)

| Phase | File | Status |
|-------|------|--------|
| 1 — Fix blockers | (done, see implementation_plan.md) | ✅ Complete — `pip install -e .` works, 70 tests pass, registry/analysis_tools/ida_tools/x64dbg_tools all wired |
| 2 — Anonymization | (done) | ✅ Complete — `tools/anonymizer.py` + `engine/injection_guard.py` integration, tested |
| 3a — pipeline_state + checkpoint | [`03a-pipeline-state-checkpoint.md`](03a-pipeline-state-checkpoint.md) | ✅ Complete — `pipeline_state.py` + `checkpoint.py::write_checkpoint()`, 83 tests pass |
| 3b — skills/ loader | [`03b-skills-loader.md`](03b-skills-loader.md) | ✅ Complete — `skills/loader.py` + `skills/registry.py` + `skills/config.py::SkillDoc`, 94 tests pass |
| 3c — engine/subagent.py | [`03c-subagent.md`](03c-subagent.md) | ✅ Complete — `engine/subagent.py::spawn_subagent`, `AgentLoop.run(initial_messages=...)`, 97 tests pass |
| 3d — launcher.py + cli.py | [`03d-launcher-cli.md`](03d-launcher-cli.md) | ✅ Complete — `engine/launcher.py` + `cli.py`, ablation/cache/guard hooks wired, 101 tests pass |
| 4 — VM rollback + rule verifier | [`04-vm-rollback-rule-verifier.md`](04-vm-rollback-rule-verifier.md) | ✅ Complete — `vmware_tools.py::vm_auto_revert_after_dynamic` (host-only, not LLM-callable) + `tools/rule_verifier.py::RuleVerifier` (JQ), 141 tests pass, 3 skipped |
| 5 — Batch eval pipeline | [`05-batch-eval.md`](05-batch-eval.md) | ✅ Complete — `experiments/batch_eval.py::BatchEvaluator` (CSV+JSONL out, `pipeline_fpr`, temporal split), fixture corpus at `hyperagent/tests/fixtures/corpus/`, 158 tests pass, 3 skipped |
| 6 — FastAPI server | [`06-fastapi-server.md`](06-fastapi-server.md) | ✅ Complete — `hyperagent/api/{models,jobs,server}.py`, `/analyze`, `/analyze/{job_id}`, `/analyze/batch`, `/verify-rule`, 167 tests pass, 3 skipped |
| 7 — Tests & verification | [`07-tests.md`](07-tests.md) | ✅ Test files complete — `test_agent_loop.py` added (was missing since 3c), 176 tests pass, 3 skipped. Baseline v3-vs-v4 manual comparison still open (needs real sample) |

## Fixed constraints (apply to every phase)

- **No Local LLM.** Cloud API only (Anthropic primary, OpenAI stub). Never add Ollama/vLLM/local model code.
- Existing modules already done, don't re-touch unless a phase file says so: `config.py`, `providers/`, `tools/base.py`, `tools/mcp_client.py`, `tools/vmware_tools.py`, `tools/filesystem_tools.py`, `tools/analysis_tools.py`, `tools/registry.py`, `tools/x64dbg_tools.py`, `tools/ida_tools.py`, `tools/anonymizer.py`, `engine/agent_loop.py`, `engine/injection_guard.py`, `experiments/ablation_runner.py`, `experiments/report_generator.py`, `telemetry/metrics.py`.
- Run `python -m pytest hyperagent/tests/ -q` before and after any change (baseline: 70 passed, 3 skipped). Use `python` (not bare `pip`) — the working venv is at `venv/Scripts/python`, a stray global Python 3.11 install exists without `anthropic` installed; always run `python -m pip install -e .` / `python -m pytest` explicitly with the same interpreter.

## Reference material already gathered (avoid re-discovering)

- v3 pipeline logic to port lives in `claude_spawn.py` (root of repo), functions around line 140-290 — stage loop, attempt/retry logic, `HYPERAGENT_ANALYSIS_DIR`/`HYPERAGENT_STATE_PATH`/`HYPERAGENT_STAGE_ID`/`HYPERAGENT_STAGE_OUTPUT_PATH` env vars.
- v3 `Stage` dataclass + `STAGES` list also in `claude_spawn.py` (~line 16-37):
  ```python
  Stage("01-prepare-env",  "hyperagent-prepare-env", reads_sample_content=False),
  Stage("02-static-pass1", "hyperagent-static",      reads_sample_content=True),
  Stage("03-unpack",       "hyperagent-unpack",      reads_sample_content=True),
  Stage("04-static-pass2", "hyperagent-static",      reads_sample_content=True),
  Stage("05-dynamic",      "hyperagent-dynamic",     reads_sample_content=True),
  Stage("06-intel",        "hyperagent-intel",       reads_sample_content=True),
  Stage("07-deepdive",     "hyperagent-deepdive",    reads_sample_content=True),
  Stage("08-report",       "hyperagent-report",      reads_sample_content=False),
  Stage("09-summary",      "hyperagent-summary",     reads_sample_content=False),
  ```
  These stage_ids match `hyperagent/tools/registry.py::STAGE_TOOLS` keys exactly — reuse the same list, don't invent a new one.
- v3 `pipeline_state.py` helper (STATE.json read/init/checkpoint/complete/fail) to port/adapt lives at `skill/backup/hyperagent-malware-analyze/v3/_hyperagent-common/scripts/pipeline_state.py`.
- Real SKILL.md files (for the skills loader to parse/strip) live at `~/.claude/skills/hyperagent-*/SKILL.md` (9 skill dirs: prepare-env, static, unpack, dynamic, intel, deepdive, report, summary, progress; plus shared `_hyperagent-common/`). Each has `# Runtime Path Contract` and `# State / Resume Contract` H1 sections and a `context usage` `>= 80%` checkpoint instruction inside the State/Resume section — these are the three things the loader must strip per `implementation_plan.md` line 187-190.
- `experiments/ablation_runner.py` already imports `from hyperagent.engine.launcher import run_pipeline_with_config` (line ~216) and expects a `run_fn` with that exact import path/name — Phase 3d must produce a function matching that signature (`AblationRunner` is otherwise complete, don't modify it).
- `experiments/ablation_runner.py::AblationConfig` fields (already implemented, read-only reference): `name`, `skip_stages: list[str]`, `isolated_subagents: bool`, `cache_enabled: bool`, `injection_guard: bool`, `checkpoint_enabled: bool`.

## Open items carried over from `implementation_plan.md`

- **O1** — confirm real IDA Pro MCP endpoint (config.py defaults to `http://localhost:13337/mcp`).
- **O2** — need ~100 benign sandbox JSON reports for Phase 4's rule verifier.
- **O3** — confirm internal domain suffix / IP range list for anonymizer (currently `tools/anonymizer.py::DEFAULT_INTERNAL_DOMAIN_SUFFIXES`).
- ~~**O4** — wire `ProviderConfig.stage_models` into per-stage model selection.~~ ✅ Done — `launcher.py:236` resolves `config.provider.stage_models.get(stage.stage_id, config.provider.model)` per stage, confirmed with a passing test in `test_launcher.py`.
- **O5** — Phase 5's corpus at `hyperagent/tests/fixtures/corpus/{malware,benign}/` holds 4 tiny non-executable placeholders, not real samples. Replace with a real labeled corpus (see O2) before treating batch-eval numbers as meaningful. Each corpus dir may carry an optional `first_seen.json` (`{"filename": "YYYY-MM-DD"}`) to drive the temporal-drift split.
