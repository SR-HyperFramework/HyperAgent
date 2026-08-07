# HyperAgent v4 — Staged Build Plan

Companion to [implementation_plan.md](implementation_plan.md). That document is the
**design**; this one is the **build order**: what gets written, in what sequence, and
what proves each stage is done.

**Total: 8 stages.** Stages 1–5 are required for a working pipeline. Stages 6–8 are
the research/serving surface.

---

## 0. Audit Baseline — what already exists

`hyperagent/` is partially scaffolded (1,644 LOC). Verified state:

| Module | LOC | State |
|---|---|---|
| `config.py` | 165 | Works; secrets hardcoded as defaults |
| `providers/base.py` | 123 | Interface complete |
| `providers/anthropic_provider.py` | 143 | Works; token counting is a `len//4` heuristic |
| `providers/openai_provider.py` | 40 | Stub, as designed |
| `tools/base.py` | 45 | Complete |
| `tools/mcp_client.py` | 160 | Complete |
| `tools/filesystem_tools.py` | 145 | Complete |
| `tools/vmware_tools.py` | 144 | Complete |
| `tools/analysis_tools.py` | 170 | **All 3 script invocations use wrong CLI flags** |
| `tools/x64dbg_tools.py` / `ida_tools.py` | 103 | Build clients, but never wired into the registry |
| `tools/registry.py` | 69 | Core only; no `get_tools_for_stage` |
| `tools/shell_tools.py` | 5 | Dead deprecation comment |
| `engine/agent_loop.py` | 156 | Loop works; checkpoint path is a no-op |
| `engine/checkpoint.py` | 55 | Threshold check only |
| `engine/injection_guard.py` | 45 | Complete |

**Missing entirely:** `cli.py`, `skills/*`, `engine/subagent.py`, `engine/launcher.py`,
`telemetry/*`, `api/server.py|models.py|jobs.py`, `tests/*`.

### Confirmed blockers

1. **`pyproject.toml` build backend does not exist.**
   `setuptools.backends._legacy:_Backend` → `ModuleNotFoundError` on this
   interpreter (setuptools 65.5.0). Must be `setuptools.build_meta`.
2. **`hyperagent/engine/` and `hyperagent/telemetry/` lack `__init__.py`.**
   `find_packages(include=["hyperagent*"])` returns
   `['hyperagent', 'hyperagent.api', 'hyperagent.providers', 'hyperagent.skills', 'hyperagent.tools']`
   — `engine` is silently dropped from any built wheel.
3. **`analysis_tools.py` calls every helper script with flags they do not accept:**

   | Script | Real signature | What `analysis_tools.py` sends |
   |---|---|---|
   | `validate_output.py` | positional `<schema> <json>` | `--schema X --json Y` |
   | `fetch_vt_file_report.py` | positional `file_id`, `--endpoint`, `-o` | `--sha256 X --endpoint Y --output Z` |
   | `normalize_vt_to_intel.py` | `--file-info`, `--behaviour-summary`, `-o` | `--input X --output Y` |

   Also `_get_scripts_dir()` defaults to `~/.claude/skills/scripts`; the real
   location is `~/.claude/skills/_hyperagent-common/scripts`.
4. **Checkpoint threshold disagrees three ways:** `config.py` 0.80, `AgentLoop`
   0.75, design doc §7 says 0.75. One source of truth required.
5. **`AgentLoop` never passes `max_tokens`/`temperature`**, so `ProviderConfig`
   values are ignored and provider defaults always win.

---

## Stage 1 — Foundation repair

Make the package installable and importable before adding anything to it.

**Files**
- `pyproject.toml` — backend → `setuptools.build_meta`; add explicit
  `[tool.setuptools.packages.find]` coverage
- `hyperagent/engine/__init__.py` — new
- `hyperagent/telemetry/__init__.py` — new
- `hyperagent/tests/__init__.py` — new
- delete `hyperagent/tools/shell_tools.py`
- `hyperagent/config.py` — move VM credentials to env-only with empty defaults;
  single `checkpoint_threshold = 0.75`

**Exit criteria**
- `pip install -e .` succeeds
- `find_packages` lists all 7 subpackages including `engine` and `telemetry`
- `python -c "import hyperagent.engine, hyperagent.telemetry"` succeeds
- no credential literal remains in tracked source

---

## Stage 2 — Provider layer

**Files**
- `providers/anthropic_provider.py` — replace `len//4` with the Anthropic
  `count_tokens` API; cache per-message counts so the loop does not re-count
  history each turn; honour `max_tokens`/`temperature` arguments
- `providers/base.py` — `estimate_message_tokens` currently counts
  `str(block)` on structured content, which inflates tool-result blocks; count
  block text fields instead
- `providers/__init__.py` — `create_provider` reads `ProviderConfig` directly
  rather than loose kwargs

**Exit criteria**
- `tests/test_providers.py`: Anthropic provider completes a one-turn prompt;
  OpenAI stub raises `NotImplementedError`; token count for a known string is
  within 10% of the API's own count

**Deferred — needs a live key.** 9 offline tests pass. 3 tests are marked
`@live` and skip while `ANTHROPIC_API_KEY` is unset, so these exit criteria are
written but **not yet proven**:

| Test | Proves |
|---|---|
| `test_count_tokens_matches_api_within_10_percent` | real `count_tokens` vs API within 10% |
| `test_count_tokens_is_cached` | second count hits the memo, not the API |
| `test_single_turn_completion` | one-turn prompt returns `end_turn` + non-zero usage |

Run with the key set to close them out:
`ANTHROPIC_API_KEY=... python -m pytest hyperagent/tests/test_providers.py -q`

---

## Stage 3 — Tool layer

**Files**
- `tools/analysis_tools.py` — **rewrite all four handlers against the real CLI
  signatures** in the table above; resolve `_hyperagent-common/scripts` correctly
- `tools/registry.py` — add `STAGE_TOOLS` map and `get_tools_for_stage(stage_id)`
  with glob resolution (move the `fnmatch` logic out of `AgentLoop`); add
  `build_full_registry(config)` that wires MCP tools when endpoints are reachable
  and degrades cleanly when they are not
- `tools/x64dbg_tools.py`, `tools/ida_tools.py` — lazy connect; surface a clear
  tool-level error instead of raising at registry-build time

**Exit criteria**
- `tests/test_tools.py`: each analysis tool invokes its script and gets exit 0
  on a fixture; registry resolves `01-prepare-env` to exactly the vm/filesystem/
  health-check tools; unreachable MCP endpoint yields an `is_error` ToolResult,
  not an exception

---

## Stage 4 — Skill system

Vendor the state helper so v4 stops loading it by file path.

**Files**
- `hyperagent/pipeline_state.py` — import-clean copy of the v3 helper (stage
  table, statuses, checkpoint/complete/fail). Public API only, no `argparse`
- `skills/config.py` — `SkillConfig` dataclass per design §4.3
- `skills/loader.py` — parse `SKILL.md`: YAML frontmatter + body; strip the
  `Runtime Path Contract` and `State / Resume Contract` sections and the
  `context usage >= 80%` instructions (design §5.1); leave all domain content
  intact
- `skills/registry.py` — `stage_id → SkillConfig` for all 9 stages

**Exit criteria**
- Loader parses all 9 `SKILL.md` files without error
- No loaded prompt contains `HYPERAGENT_SKILLS_ROOT`, `pipeline_state.py`, or
  `context usage`
- Domain sections (Role, Output Contract, Strict JSON Rules) survive verbatim

---

## Stage 5 — Engine

**Files**
- `engine/checkpoint.py` — on threshold, write
  `_state/<stage_id>.progress.md` and call `pipeline_state.checkpoint()`.
  Today the loop returns a string and nothing is persisted, so the launcher's
  resume path can never trigger
- `engine/agent_loop.py` — take tools from the registry rather than
  re-implementing glob matching; thread `max_tokens`/`temperature`; emit a
  structured `StageResult` instead of a bare string
- `engine/subagent.py` — new; fresh message history, tool subset, structured
  return (design §4.4)
- `engine/launcher.py` — new; port the resume/skip/validate state machine from
  `claude_spawn.py:151-283` verbatim in behaviour
- `cli.py` — new; `hyperagent analyze <sample>`, `--stage`, `--batch`,
  `--provider`, `--model`

**Exit criteria**
- Single stage `01-prepare-env` runs end to end and its artifact validates
- A forced low threshold produces a real progress file and `STATE.json`
  status `running`; re-invoking resumes instead of restarting
- Full 9-stage run on a known sample reaches `pipeline_complete`

---

## Stage 6 — Telemetry

**Files**
- `telemetry/logger.py` — JSONL trace writer to `reports/<sha256>/_telemetry/`
- `telemetry/metrics.py` — per-stage token/latency/tool-call counters
- hook points in `agent_loop.py` and `launcher.py`

**Exit criteria**
- A completed run emits one JSONL record per LLM turn and per tool call
- Aggregate token totals match the sum of `CompletionResult.usage`

---

## Stage 7 — FastAPI server

**Files**
- `api/models.py`, `api/jobs.py`, `api/server.py` per design §4.5
- mount the existing Flask `webui` at `/ui`

**Exit criteria**
- `POST /analyze/path` → job id; `GET /jobs/{id}` transitions to completed;
  `GET /jobs/{id}/result` returns the summary JSON; `/ui` renders

---

## Stage 8 — Verification & baseline comparison

**Files**
- `tests/test_agent_loop.py`, `tests/test_launcher.py`
- `tests/fixtures/` — recorded provider responses so the loop is testable
  without live API calls

**Exit criteria** (design §9)
- All schema validations pass
- Final `STATE.json` matches the v3 baseline
- IOC set overlap > 90%; verdict and risk score within ±10 points

---

## Dependency order

```
Stage 1 ──▶ Stage 2 ──┐
        └──▶ Stage 3 ──┴──▶ Stage 4 ──▶ Stage 5 ──▶ Stage 6
                                            │
                                            └──────▶ Stage 7 ──▶ Stage 8
```

Stages 2 and 3 are independent of each other and can be built in either order.

---

## Open items still blocking

Carried from design §8, unchanged:

- **O1 — IDA Pro MCP endpoint.** `config.py` currently guesses
  `http://localhost:13337/mcp`. Stage 3 needs the real value, or `ida_tools`
  ships unverified.
- **O2 — VirusTotal key source.** Env `VT_API_KEY` is wired; confirm no config
  file is expected.
- **O3 — Per-stage model selection.** `ProviderConfig.stage_models` exists but
  nothing reads it. Stage 5 wires it once the policy is decided.
