# HyperAgent

<div align="center">
  <img src="https://cdn.h26v.io.vn/1790958328577-f3519f0ae12a26ce.png" alt="HyperAgent Dashboard" width="800"/>
</div>

HyperAgent is a malware-analysis pipeline. Point it at a sample, it runs the
sample through a fixed sequence of stages — environment prep, static analysis,
unpacking, dynamic analysis, threat-intel lookups, deep-dive reasoning,
reporting, summary — and writes a JSON/Markdown report per stage to
`reports/<sha256>/`.

Each stage is one LLM call loop (an `AgentLoop`) with a curated tool subset,
driven directly through the Anthropic (or OpenAI) SDK — no Claude Code CLI
subprocess involved. This is the **v4 SDK rewrite**. The checked-in `skill/` directory is the
runtime source of truth for stage skills.

## 1. How a run works

```text
sample
  -> 01-prepare-env   (VM/tooling health checks)
  -> 02-static-pass1  (IDA-backed static analysis)
  -> 03-unpack        (x64dbg-backed unpacking)
  -> 04-static-pass2  (re-run static analysis on unpacked code)
  -> 05-dynamic       (VM execution + x64dbg)
  -> 06-intel         (VirusTotal / threat-intel correlation; opt-in, `--profile intel`)
  -> 07-deepdive       (cross-stage reasoning)
  -> 08-report         (Markdown report from compact validated context)
  -> 09-summary         (structured verdict JSON, what the web UI reads)
```

Each stage:
- gets only the tools listed for it in `hyperagent/tools/registry.py::STAGE_TOOLS`
- reads/writes its status through `STATE.json` in the sample's report directory
  (`hyperagent/pipeline_state.py`), so a run can resume mid-pipeline
- compacts long stage conversations semantically before falling back to checkpoint/resume, then checkpoints and resumes automatically if the compacted context still approaches the model's context limit (`hyperagent/engine/checkpoint.py`)
- uses stage-specific bounded inputs when raw upstream artifacts would otherwise bloat the conversation; notably `08-report` builds a compact validated `08-report.context.md` briefing instead of reading large JSON artifacts like `06-intel.json` directly into the model context (`skill/_hyperagent-common/scripts/build_report_context.py`)
- runs untrusted sample content through an injection guard + anonymizer before
  it reaches the model (`hyperagent/engine/injection_guard.py`,
  `hyperagent/tools/anonymizer.py`) — the anonymizer replaces internal
  IPs/paths/credentials with stable placeholder tokens before anything leaves
  the machine

After `05-dynamic`, the VM is automatically reverted to its clean snapshot.

## 2. Repository map

```text
HyperAgent/
├─ hyperagent/              # the v4 SDK package (pip install -e .)
│  ├─ cli.py                # `hyperagent analyze` / `hyperagent batch`
│  ├─ config.py             # env-var + YAML config loading
│  ├─ pipeline_state.py     # per-run STATE.json read/write
│  ├─ console.py            # run console: event log, line renderer, live-feed hooks
│  ├─ tui.py                # full-screen --mdebug console with the run sidebar
│  ├─ tui_input.py          # keyboard/mouse-wheel scrolling for the full-screen console
│  ├─ console_log.py        # console.jsonl transcript writer/reader (console + web)
│  ├─ console_actions.py    # collapses tool-call bursts into summary lines (console + web)
│  ├─ run_registry.py       # ~/.hyperagent/runs.json: where every run's report folder lives
│  ├─ run_snapshot.py       # stages/IoCs/evidence read from a report dir (sidebar + web)
│  ├─ dashboard.py          # serves webui/ in-process for the running analysis
│  ├─ engine/
│  │  ├─ agent_loop.py      # the tool-calling loop for one stage
│  │  ├─ launcher.py        # STAGES list + run_pipeline_with_config()
│  │  ├─ checkpoint.py      # context-limit checkpoint/resume
│  │  ├─ injection_guard.py # prompt-injection defenses
│  │  └─ subagent.py        # spawns scoped sub-conversations
│  ├─ providers/            # Anthropic/OpenAI SDK wrappers
│  ├─ tools/                # everything a stage can call: filesystem, IDA,
│  │                        # x64dbg, VMware, VirusTotal, anonymizer, rule
│  │                        # verifier, plus the STAGE_TOOLS registry
│  ├─ skills/                # loads/parses the SKILL.md instructions per stage
│  ├─ telemetry/            # per-run token/cost metrics
│  ├─ api/                  # FastAPI server (jobs, models, server)
│  └─ tests/                # pytest suite, one file per module above
├─ experiments/             # batch_eval (corpus precision/recall/F1), ablation runner
├─ webui/                   # read-only Flask viewer for finished reports and live runs
├─ skill/                   # checked-in v4 stage skills + shared helper assets
│  └─ backup/               # archived v3 CLI-subprocess pipeline (reference only)
├─ plans/                   # phase-by-phase implementation notes for this rewrite
└─ openwiki/                # generated deep-dive docs (optional reading)
```

If you're orienting for the first time, read in this order:
1. This file
2. `hyperagent/engine/launcher.py` — the actual stage loop
3. `hyperagent/tools/registry.py` — what each stage can touch
4. `plans/00-index.md` — what's been built and what's still open

## 3. Requirements

- Python 3.11+
- An Anthropic API key (`ANTHROPIC_API_KEY`) — OpenAI is a partial stub, not
  the primary path
- For the full pipeline (static/dynamic stages): IDA Pro (idalib MCP server),
  x64dbg MCP server, and a VMware Workstation guest VM. The prep/report/
  summary stages and the test suite run fine without any of this.

## 4. Install

Quick bootstrap on a new Windows machine:

```powershell
powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1
```

The script creates `venv/`, installs the package with `pip install -e .`, runs Python smoke checks, and reports whether host-side extras like `vmrun`, `idalib-mcp`, `upx`, and the checked-in stage skill directories under `skill/` are available. It also looks for `vmrun` in the default VMware install locations and writes a commented `~/.hyperagent/config.yaml` template if none exists. It does **not** install VMware, IDA Pro, or x64dbg MCP for you.

Manual install remains:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -e .
```

Optional script flags:

```powershell
powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1 -InstallDev -RunTests
```

- `-InstallTools` installs `upx` through `winget` and saves a discovered VMware directory to the user `PATH`.
- `-Strict` exits with code 1 if `vmrun`, `idalib-mcp`, `upx`, or any stage skill directory is missing.

Then set your API key for the current shell:

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
```

Verify the install:

```bash
python -m pytest hyperagent/tests/ -q
```

### Moving to a new machine

To transfer this repo (source + the gitignored `resource/` tool binaries) to
another Windows machine without dragging along `venv/`, `.git` history, or
secrets:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\package_for_transfer.ps1
```

This builds `HyperAgent-transfer.zip` next to the repo. Copy it to the target
machine, extract it, and follow [`SETUP_NEW_MACHINE.md`](SETUP_NEW_MACHINE.md)
— it has a ready-to-paste prompt for the agent on that machine (runs
`bootstrap.ps1`, reports what's missing) plus a manual-install checklist for
IDA Pro/x64dbg/VMware and a list of secrets/env vars to bring over yourself.

## 5. Configuration

Config resolves in this order (highest priority first): environment
variables → `~/.hyperagent/config.yaml` → dataclass defaults
(`hyperagent/config.py`). There's no config file shipped in this repo — create
`~/.hyperagent/config.yaml` only if you need to override MCP URLs, VM
credentials, or per-stage model choices; everything else works from env vars
alone.

Commonly used environment variables:

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Required for any real run |
| `HYPERAGENT_MODEL` | Override the default model for every stage |
| `HYPERAGENT_THINKING_LEVEL` | Extended-thinking depth: `off`, `low`, `medium`, `high`, or `max`; unset defers to `HYPERAGENT_EXTENDED_THINKING` |
| `HYPERAGENT_SKILLS_ROOT` | Directory containing `_hyperagent-common/` and the `hyperagent-*` stage skills; defaults to the repo `skill/` directory |
| `HYPERAGENT_ANTHROPIC_BASE_URL` | Point the Anthropic client at a compatible proxy/gateway instead of `api.anthropic.com` |
| `HYPERAGENT_VMX_PATH`, `HYPERAGENT_VM_SNAPSHOT`, `HYPERAGENT_GUEST_USER`, `HYPERAGENT_GUEST_PASSWORD` | VMware guest for the dynamic stage — no defaults, must be set to run `05-dynamic` |
| `HYPERAGENT_IDA_MCP_URL`, `HYPERAGENT_X64DBG_MCP_URL` | MCP endpoints for static/unpack/dynamic stages |
| `VT_API_KEY` | VirusTotal lookups in `06-intel` |
| `HYPERAGENT_PIPELINE_PROFILE` | Runtime profile: `full` (default), `intel`, `fast`, `static-only`, or `dynamic-only` |
| `HYPERAGENT_SKIP_DYNAMIC` | Set truthy to skip the VM-backed `05-dynamic` stage |
| `HYPERAGENT_SKIP_INTEL` | Set truthy to skip `06-intel` even under the `intel` profile; no effect elsewhere, since no other profile selects it |
| `HYPERAGENT_REUSE_COMPLETED_STAGES` | Reuse completed valid stage artifacts from `reports/<sha256>/`; defaults to true |
| `HYPERAGENT_START_IDA_MCP` | Local idalib MCP startup policy: `auto` (default), `always`, or `never` |
| `HYPERAGENT_FAST_MAX_STAGE_ATTEMPTS` | Attempt cap for the targeted `fast` / `static-only` / `dynamic-only` profiles; defaults to 2 |
| `HYPERAGENT_CHECKPOINT_THRESHOLD` | Context usage ratio that triggers safety handling; defaults to `0.75` |
| `HYPERAGENT_COMPACT_ENABLED` | Set falsey to disable semantic context compaction before checkpoint fallback; defaults to true |
| `HYPERAGENT_COMPACT_THRESHOLD` | Optional context usage ratio for compaction; unset means use `HYPERAGENT_CHECKPOINT_THRESHOLD` |
| `HYPERAGENT_COMPACT_TARGET_RATIO` | Target context ratio after compaction; defaults to `0.45` |
| `HYPERAGENT_MAX_COMPACTIONS` | Maximum semantic compactions per stage attempt; defaults to 3 |
| `HYPERAGENT_MAX_COMPACTION_TOKENS` | Maximum output tokens for the internal compaction call; defaults to 2048 |

Per-stage model overrides go under `provider.stage_models` in the YAML config
(stage_id → model name), for e.g. running cheaper models on prep/summary and
a stronger model on deepdive.

### Thinking level

`provider.thinking_level` picks how deeply Claude reasons before answering, as
a name rather than a raw token budget:

| Level | Thinking budget | Typical use |
|---|---|---|
| `off` | disabled | Mechanical stages; fastest and cheapest |
| `low` | 4096 | Default depth when thinking is switched on |
| `medium` | 8192 | Stages that weigh several pieces of evidence |
| `high` | 16384 | Reconciliation and verdict work |
| `max` | 32768 | Hard samples where reasoning depth is the bottleneck |

Set it globally, per run, or per stage:

```powershell
# One run, every stage.
hyperagent analyze C:\path\to\sample.exe --thinking high
```

```yaml
# ~/.hyperagent/config.yaml — cheap by default, deep where it pays off.
provider:
  thinking_level: low
  stage_thinking_levels:
    07-deepdive: max
    09-summary: off
```

Resolution order is stage level → global level → the raw
`extended_thinking` / `thinking_budget_tokens` pair. That last fallback is why
configs written before thinking levels existed still behave identically, and
why `--debug` (which just flips `extended_thinking`) keeps working. An explicit
level always wins, including `--thinking off`. The budget is a ceiling, not a
quota: the model spends what it needs up to that limit. Anthropic requires
`max_tokens` above the thinking budget, so the provider raises it automatically
when a level exceeds `HYPERAGENT_MAX_OUTPUT_TOKENS`.

Context safety has two layers. First, `AgentLoop` tries a tool-free semantic
compaction call that condenses the current conversation into a marked
"Compacted conversation state" message, preserving stage goals, evidence, tool
results, errors, and remaining work. If compaction fails, is disabled, exceeds
its target size, or the stage still approaches the context limit, the launcher
falls back to the existing durable checkpoint path: write
`reports/<sha256>/_state/<stage_id>.progress.md`, mark the stage `running` in
`STATE.json`, and resume the stage on the next attempt.

`08-report` adds an earlier guardrail at the input layer. Instead of letting the
model read large upstream JSON artifacts directly (for example `05-dynamic.json`
or `06-intel.json`), the stage first calls `build_report_context`, which
validates the available upstream artifacts and writes a compact
`reports/<sha256>/08-report.context.md` briefing. The report skill renders the
final Markdown report from that compact context plus `07-deepdive.json`'s final
claim policy, which keeps report generation usable on smaller-context models and
avoids repeated compaction loops caused by large tool results.

As a result, `08-report` now has a deliberately narrow tool surface: it can
write the final Markdown artifact and invoke the compact-context builder, but it
does not read raw upstream stage JSON files directly by default.

The current focused verification for this report-context change is:

```bash
python -m pytest hyperagent/tests/test_tools.py hyperagent/tests/test_launcher.py -q
```

At the time of this update, that focused suite passes: `65 passed`.

If you are iterating specifically on report-stage context behavior, a good
single-stage command is:

```powershell
hyperagent analyze C:\path\to\sample.exe --stage 08-report
```

That stage expects the validated upstream artifacts to already exist in
`reports/<sha256>/`.



## 6. Usage

### CLI

```powershell
.\venv\Scripts\Activate.ps1
hyperagent analyze C:\path\to\sample.exe
```

Run a single stage (useful while iterating):

```powershell
hyperagent analyze C:\path\to\sample.exe --stage 02-static-pass1
```

Output lands in `<sample_parent>/reports/<sha256>/`.

Runtime profiles for faster iteration:

```powershell
# Add external enrichment (06-intel) on top of the default local pipeline.
hyperagent analyze C:\path\to\sample.exe --profile intel

# Skip the slowest dynamic/intel work and reuse valid existing artifacts.
hyperagent analyze C:\path\to\sample.exe --profile fast

# Single-pass static triage: prepare, static pass 1, deepdive, report, summary.
hyperagent analyze C:\path\to\sample.exe --static-only

# Runtime-focused pass: prepare, dynamic, deepdive, report, summary.
hyperagent analyze C:\path\to\sample.exe --profile dynamic-only

# Keep the full profile but explicitly skip expensive optional stages.
hyperagent analyze C:\path\to\sample.exe --skip-dynamic --skip-intel

# Do not reuse completed stage artifacts from reports/<sha256>/.
hyperagent analyze C:\path\to\sample.exe --no-cache

# Control local idalib-mcp startup for this run.
hyperagent analyze C:\path\to\sample.exe --ida-mcp never
```

`full` is the default and runs every stage that reasons from the sample itself. External enrichment is opt-in: `06-intel` sends sample hashes to a third party and needs `VT_API_KEY` plus network reachability, so it runs only under the `intel` profile. The targeted profiles reduce turnaround time while developing or triaging by running a subset of the nine stages:

| Profile | Stages |
| --- | --- |
| `full` (default) | `01` – `09` except `06-intel` |
| `intel` | `01` – `09`, i.e. `full` plus external enrichment |
| `fast` | `01-prepare-env`, `02-static-pass1`, `03-unpack`, `04-static-pass2`, `07-deepdive`, `08-report`, `09-summary` |
| `static-only` | `01-prepare-env`, `02-static-pass1`, `07-deepdive`, `08-report`, `09-summary` |
| `dynamic-only` | `01-prepare-env`, `05-dynamic`, `07-deepdive`, `08-report`, `09-summary` |

All targeted profiles limit retries with `HYPERAGENT_FAST_MAX_STAGE_ATTEMPTS` and still validate any reused stage artifact before skipping work. With `--ida-mcp auto` (the default), HyperAgent starts local idalib MCP only when the selected stages need IDA tools.

`static-only` runs a single static pass: it drops `03-unpack`, and `04-static-pass2` with it, because static pass 2 exists to analyze a recovered artifact and `skill/hyperagent-static/SKILL.md` requires it to emit a blocked report — never a silent fallback to pass 1 — when `03-unpack.json` is absent. Use `--profile fast` when you do want unpacking and the second static pass but still no dynamic or intel work.

`dynamic-only` keeps the reporting chain, so it still emits `07-deepdive.json`, `08-report.md`, and `09-summary.json` — with static, unpack, and intel coverage recorded as limitations rather than fabricated. For a bare runtime run without those artifacts, use `--stage 05-dynamic` instead. Stages a profile does not select stay `pending` in `STATE.json`, so `validate_pipeline.py --require-all` is not the right success check for a targeted run; validate the artifacts that exist instead. A later default `full` run reuses the completed artifacts and fills in the pending stages, so pass `--profile dynamic-only` again to stay scoped (and `--no-cache` to force a fresh dynamic run).

### Live console and dashboard

```powershell
hyperagent analyze C:\path\to\sample.exe --mdebug
```

On a capable terminal (Windows Terminal, any ANSI TTY) `--mdebug` opens a
full-screen console modelled on Strix's: the agent trace (assistant text, tool
calls and results, stage transitions) fills the left pane with a status row
under it, and a sidebar on the right stacks

| Panel | Shows |
|---|---|
| Watch live in browser | Link to this run's live page on the in-process dashboard |
| Stages | Every selected stage: passed, running (with retry attempt), resumable checkpoint, failed, pending |
| IoCs | Indicators from `05-dynamic.json`, then `09-summary.json` once it exists |
| Evidence | Findings from stages `02`–`05`, newest stage first, with confidence |
| Stats | Verdict (deepdive, then summary), model, sample hash, last error |

The sidebar re-reads `STATE.json` and the stage artifacts about once a second;
the dashboard serves the same view at `http://127.0.0.1:5000/live/<sha256>`
(next free port if 5000 is taken), plus the trace. Leaving the full-screen
view erases it, so the console prints a recap of stages, IoCs and the verdict
when the run ends. Sample-derived text is shown with terminal control
characters escaped, so an indicator cannot inject escape sequences.

The full-screen view has no terminal scrollback, so the trace pane scrolls
itself: ↑/↓ by a line, PgUp/PgDn by a page, the mouse wheel by three lines,
Home to the oldest line still held (the newest 2,000 events), End to follow
the output again. While scrolled back the view holds still as new output
arrives and the pane border shows how many lines are below. Where the
terminal passes the mouse to the app, select text with Shift+drag.

Each burst of tool calls collapses into one line such as
`◆ Read 3 files, ran 1 command, called 1 tool · 1 failed`, followed by the
failed calls and, while it runs, the call still waiting for its result.
Ctrl+O expands every burst into its raw calls and result previews and
collapses them again. The dashboard shows the same summaries as expandable
rows.

Everything the console shows is also appended to
`reports/<sha256>/console.jsonl`, one JSON object per event (a `session`
record opens each attach, so a resumed run adds a session rather than
overwriting). The dashboard renders that file on the run's live page once the
CLI has exited, and serves it as text at `/console/<sha256>.txt`.

| Flag | Effect |
|---|---|
| `--no-tui` | Plain condensed lines with a one-line status footer (also the fallback when output is piped or the console is a legacy Windows console) |
| `--no-dashboard` | Do not serve the browser dashboard |
| `--dashboard-port N` | First port to try for the dashboard (default 5000) |

### Finding reports in other folders

Reports are written next to each sample (`<sample_dir>/reports/<sha256>`)
unless `reports_root` is configured, so runs over different datasets land in
different trees. Every pipeline run records its report folder in
`~/.hyperagent/runs.json` (override with `HYPERAGENT_RUN_INDEX`), and the
dashboard lists those runs next to its own reports root, whichever folder they
are in. Runs made before this index existed can be linked once:

```powershell
hyperagent link-reports H:\Dataset\files\m\reports experiments\results\llm_compare
eports experiments
esults\llm_compare
```

It walks the given folders for `<sha256>` directories holding `STATE.json`,
`09-summary.json` or `console.jsonl`. When a sample has reports in several
folders, the dashboard shows the most recently written one; folders that no
longer exist drop out of the index.

### API server

```powershell
.\venv\Scripts\Activate.ps1
uvicorn hyperagent.api.server:app --host 0.0.0.0 --port 8000
```

```bash
curl -X POST http://127.0.0.1:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"sample_path": "C:/path/to/sample.exe"}'

curl http://127.0.0.1:8000/analyze/<job_id>
```

Batch a labeled corpus (precision/recall/F1/FPR):

```bash
curl -X POST http://127.0.0.1:8000/analyze/batch \
  -H "Content-Type: application/json" \
  -d '{"malware_dir": "C:/corpus/malware", "benign_dir": "C:/corpus/benign"}'
```

### Report viewer

Read-only browser for finished reports (`09-summary.json`) and live runs — see
`webui/README.md` for the full route list. `--mdebug` runs it in-process for the
current run (see above); start it standalone to browse the corpus.

```powershell
.\venv\Scripts\Activate.ps1
python webui\app.py
```

Then open <http://127.0.0.1:5000>.

## 7. Testing

```bash
python -m pytest hyperagent/tests/ -q
```

Baseline as of the runtime-profile update: 247 passed, 3 skipped. Each file under
`hyperagent/tests/` maps 1:1 to a module — e.g. `test_launcher.py` tests
`engine/launcher.py`, `test_anonymizer.py` tests `tools/anonymizer.py`. Add
new tests next to the module they cover.

## 8. Known open items

Tracked in detail in `plans/00-index.md`; the short version:

- No local LLM support by design — cloud API only (Anthropic primary, OpenAI
  stub). Don't add Ollama/vLLM/local-model code.
- The fixture corpus at `hyperagent/tests/fixtures/corpus/` is placeholder
  data, not real malware/benign samples — batch-eval numbers aren't
  meaningful until it's replaced with a real labeled corpus.
- IDA MCP endpoint, internal-domain suffix list for the anonymizer, and
  VMware credentials all need environment-specific values before a full run
  will work end-to-end.
