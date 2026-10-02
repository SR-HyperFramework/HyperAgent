# Phase 7 — Tests & Verification (ongoing)

Read `00-index.md` first for shared constraints and reference paths.

This phase isn't a single sitting — each earlier phase file already lists
its own test file(s) to add under its own Exit Criteria section. Treat this
file as the checklist of what should exist once everything above is done,
plus the cross-cutting verification pass that only makes sense after
multiple phases have landed.

## Test files to have by the end (cross-reference to the phase that adds them)

- `hyperagent/tests/test_pipeline_state.py` — Phase 3a
- `hyperagent/tests/test_checkpoint.py` — Phase 3a
- `hyperagent/tests/test_skills_loader.py` — Phase 3b
- `hyperagent/tests/test_subagent.py` — Phase 3c
- `hyperagent/tests/test_agent_loop.py` — ✅ added in Phase 7 (was missing
  since 3c) — covers `run()` end-turn/tool-call/tool-error paths,
  `initial_messages` seeding, checkpoint-threshold raise, max-turns
  exhaustion, and `MetricsCollector` turn/checkpoint recording
- `hyperagent/tests/test_launcher.py` — Phase 3d
- `hyperagent/tests/test_vm_safety.py` — Phase 4 Part A
- `hyperagent/tests/test_rule_verifier.py` — Phase 4 Part B
- `hyperagent/tests/test_batch_eval.py` — Phase 5
- `hyperagent/tests/test_api_server.py` — Phase 6

Already existing (don't duplicate): `test_anonymizer.py`, `test_metrics.py`,
`test_providers.py`, `test_tools.py`.

## Cross-cutting checks (do once Phases 3-6 are all in)

```bash
python -m pytest hyperagent/ -v   # full suite, no skips beyond intentional ones
```

### Baseline comparison (v3 vs v4), from `implementation_plan.md`

Run the same sample through v3 (`claude_spawn.py`, CLI-based) and v4
(`python -m hyperagent.cli analyze`, SDK-based), compare:
1. All `schema.json` validations pass for both.
2. Final `STATE.json` shape is equivalent (stage statuses, not necessarily
   byte-identical timestamps).
3. IOC set overlap > 90% between the two runs' `09-summary` output.
4. Final verdict + risk score within ±10 points of each other.
5. **New in v4**: FPR of any JQ rules generated during the run = 0% against
   Phase 4's benign corpus (v3 has no equivalent check — this is a v4-only
   addition, not a v3/v4 parity requirement).

This comparison needs a real sample and a working v3 setup — treat it as a
manual verification pass to run once before considering the v4 migration
"done," not something to automate into CI in this phase.
