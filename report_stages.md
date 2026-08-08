# HyperAgent v4 — Stage Progress Report

Status of the v3 → v4 migration described in `BUILD_PLAN.md`, which rebuilds
HyperAgent from Claude-Code-CLI subprocess orchestration onto a self-hosted
agent loop on the Anthropic SDK.

**Stages 1–3 are complete.** Stage 4 is the next unit of work.

Test suite as of this report: **43 passed, 3 skipped** (`python -m pytest
hyperagent/tests -q`). The 3 skips are Stage 2's live-API tests, which need an
`ANTHROPIC_API_KEY` — they are gaps in proof, not known failures.

---

## Stage 1 — Packaging — done

Made `hyperagent` an importable package instead of a loose script tree, and
removed credentials from tracked source.

- `hyperagent/` gained proper `__init__.py` files; `hyperagent.engine` and
  `hyperagent.telemetry` import cleanly.
- Hardcoded VM guest credentials were pulled out of tracked source and moved
  behind config/env. **This must not be reverted.**

---

## Stage 2 — Provider layer — done

Replaced the token-estimation guesswork with the real Anthropic
`count_tokens` API and tightened the provider interface.

- `providers/anthropic_provider.py` — real `count_tokens`, memoized per
  message so the loop does not re-count the whole history each turn; honours
  `max_tokens` / `temperature`.
- `providers/base.py` — `estimate_message_tokens` counts block text fields
  rather than `str(block)`, which had badly inflated tool-result blocks.
- `providers/__init__.py` — `create_provider` takes a `ProviderConfig`.

**Deferred — needs a live key.** 9 offline tests pass; 3 are marked `@live`
and skip while `ANTHROPIC_API_KEY` is unset:

| Test | Proves |
|---|---|
| `test_count_tokens_matches_api_within_10_percent` | real `count_tokens` vs API within 10% |
| `test_count_tokens_is_cached` | second count hits the memo, not the API |
| `test_single_turn_completion` | one-turn prompt returns `end_turn` + non-zero usage |

Close them out with:
`ANTHROPIC_API_KEY=... python -m pytest hyperagent/tests/test_providers.py -q`

---

## Stage 3 — Tool layer — done

Three real defects were found by reading the actual code against the actual
helper scripts, and all three are fixed.

### 1. Analysis tool handlers sent flags the scripts do not accept

`fetch_vt_report`, `normalize_vt_report`, and `validate_json_output` each
built command lines that the underlying scripts would reject outright — e.g.
passing `--schema X --json Y` to a script that reads bare `sys.argv[1]` and
`sys.argv[2]`. **Every call to any of the three would have failed with a usage
error.** All three were rewritten against the real CLI signatures in
`skill/backup/hyperagent-malware-analyze/v3/_hyperagent-common/scripts/`:

- `validate_json_output(schema_path, json_path)` — positional argv, no flags.
- `fetch_vt_report(file_id, output_path, endpoint=..., ...)` — the `sha256`
  parameter was renamed to `file_id` because the script accepts MD5/SHA1/SHA256,
  not SHA256 only. `output_path` is now **required by the tool schema**, so
  large VT JSON lands on disk rather than in the model's context window.
- `normalize_vt_report(...)` — requires at least one of `file_info_path` /
  `behaviour_summary_path`, mirroring the script's own check, and repeats
  `--upstream-input` once per list item.

`_get_scripts_dir()` also pointed at a path that does not exist and was
missing the `_hyperagent-common/scripts` segment even when it did. Resolution
order is now: explicit argument → `HYPERAGENT_SCRIPTS_DIR` →
`HYPERAGENT_SKILLS_ROOT` (or `~/.claude/skills`) + the missing segment.

### 2. No per-stage tool resolution

The 9-stage pipeline needs each stage restricted to its own tool subset — for
example `07-deepdive` should see filesystem tools only, never VM or debugger
control. Nothing in the tools package implemented that; the only glob-matching
code lived duplicated inside `AgentLoop._resolve_tools`.

`tools/registry.py` now owns a `STAGE_TOOLS` map and
`ToolRegistry.get_tools_for_stage(stage_id)`. Each pattern is matched as:

- `source:<name>` → tool's `source` tag equals `<name>`
- contains `* ? [` → `fnmatch` against the tool name
- otherwise → exact tool-name match

An unknown `stage_id` raises `KeyError` listing the known stages, because a
typo there is a programming error worth failing loudly on.

### 3. MCP clients connected eagerly and crashed registry construction

`create_x64dbg_tools` / `create_ida_tools` raised `ConnectionError` whenever
the debugger or IDA host was down, taking the whole registry build with them.
They now catch `ConnectionError`, log a warning, and return an empty tool list
— the stage simply has fewer tools available. `RuntimeError` (a real JSON-RPC
error from a *reachable* server) is still allowed to propagate, since that is a
genuine bug.

### Supporting design decision: `source` tags, not name prefixes

`ToolDefinition` gained an optional `source: str = ""` field
(`"filesystem"`, `"analysis"`, `"vm"`, `"x64dbg"`, `"ida"`). Stages that want
"everything this MCP server currently exposes" select `source:x64dbg` rather
than guessing a name glob — which matters because those names come from
runtime discovery and are whatever the server decides to call them. **No tools
were renamed.**

### Verification

17 offline tests in `hyperagent/tests/test_tools.py`, with self-contained
fixtures under `hyperagent/tests/fixtures/analysis_tools/`:

- argument guards reject before any subprocess is spawned
- real subprocess round-trips for schema validation and VT normalization
- `01-prepare-env` resolves to exactly the vm/filesystem/health-check set,
  with no analysis or IDA tool leaking in; `07-deepdive` is filesystem-only
- unreachable MCP endpoint degrades to `(client, [])` and `is_error` results
  rather than raising; `build_full_registry` survives it and still returns
  both clients for clean shutdown

**Deferred — needs fixtures/credentials not committed:**

| Test | Proves | Needs |
|---|---|---|
| `upx_unpack` real-binary exit-0 | UPX round-trip on an actual packed sample | a UPX-packed fixture binary |
| `fetch_vt_report` live exit-0 | real VT API round-trip for a known-good hash | a VirusTotal API key |

The offline suite already covers the bad-hash rejection path — the script's own
regex check fails before any network I/O — so these two are network/binary
gaps, not logic gaps.

---

## Security constraints held across all three stages

- Generic `run_command` and `run_python_script` tools remain **removed**.
  Giving the model arbitrary command execution on the host is an RCE / SSRF /
  API-key-exfiltration risk if analysed malware carries a prompt-injection
  payload. Do not reintroduce them.
- `_run_bounded` keeps `shell=False` with an explicit argv list. Only
  whitelisted binaries and scripts execute.
- `filesystem_tools.read_file` keeps its 2 MB read cap.
- Stage 1's credential removal stands.

---

## Next: Stage 4 — Skill system

Vendor the pipeline-state helper so v4 stops loading it by file path:
an import-clean `hyperagent/pipeline_state.py` (stage table, statuses,
checkpoint/complete/fail — public API only, no `argparse`) plus
`skills/config.py`. See `BUILD_PLAN.md` for the full scope.
