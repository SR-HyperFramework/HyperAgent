# HyperAgent

HyperAgent is a malware-analysis pipeline. Point it at a sample, it runs the
sample through a fixed sequence of stages — environment prep, static analysis,
unpacking, dynamic analysis, threat-intel lookups, deep-dive reasoning,
reporting, summary — and writes a JSON/Markdown report per stage to
`reports/<sha256>/`.

Each stage is one LLM call loop (an `AgentLoop`) with a curated tool subset,
driven directly through the Anthropic (or OpenAI) SDK — no Claude Code CLI
subprocess involved. This is the **v4 SDK rewrite**. The checked-in `skill/` directory is the
runtime source of truth for stage skills; `skill/backup/` keeps the older CLI-subprocess
artifacts for reference only.

## 1. How a run works

```text
sample
  -> 01-prepare-env   (VM/tooling health checks)
  -> 02-static-pass1  (IDA-backed static analysis)
  -> 03-unpack        (x64dbg-backed unpacking)
  -> 04-static-pass2  (re-run static analysis on unpacked code)
  -> 05-dynamic       (VM execution + x64dbg)
  -> 06-intel         (VirusTotal / threat-intel correlation)
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
├─ webui/                   # read-only Flask viewer for finished reports
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

The script creates `venv/`, installs the package with `pip install -e .`, runs Python smoke checks, and reports whether host-side extras like `vmrun`, `idalib-mcp`, `upx`, and the checked-in stage skill directories under `skill/` are available. It does **not** install VMware, IDA Pro, or x64dbg MCP for you.

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

Then set your API key for the current shell:

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
```

Verify the install:

```bash
python -m pytest hyperagent/tests/ -q
```

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
| `HYPERAGENT_SKILLS_ROOT` | Directory containing `_hyperagent-common/` and the `hyperagent-*` stage skills; defaults to the repo `skill/` directory |
| `HYPERAGENT_ANTHROPIC_BASE_URL` | Point the Anthropic client at a compatible proxy/gateway instead of `api.anthropic.com` |
| `HYPERAGENT_VMX_PATH`, `HYPERAGENT_VM_SNAPSHOT`, `HYPERAGENT_GUEST_USER`, `HYPERAGENT_GUEST_PASSWORD` | VMware guest for the dynamic stage — no defaults, must be set to run `05-dynamic` |
| `HYPERAGENT_IDA_MCP_URL`, `HYPERAGENT_X64DBG_MCP_URL` | MCP endpoints for static/unpack/dynamic stages |
| `VT_API_KEY` | VirusTotal lookups in `06-intel` |
| `HYPERAGENT_PIPELINE_PROFILE` | Runtime profile: `full` (default), `fast`, or `static-only` |
| `HYPERAGENT_SKIP_DYNAMIC` | Set truthy to skip the VM-backed `05-dynamic` stage |
| `HYPERAGENT_SKIP_INTEL` | Set truthy to skip external intelligence enrichment in `06-intel` |
| `HYPERAGENT_REUSE_COMPLETED_STAGES` | Reuse completed valid stage artifacts from `reports/<sha256>/`; defaults to true |
| `HYPERAGENT_START_IDA_MCP` | Local idalib MCP startup policy: `auto` (default), `always`, or `never` |
| `HYPERAGENT_FAST_MAX_STAGE_ATTEMPTS` | Attempt cap for `fast` / `static-only` profiles; defaults to 2 |
| `HYPERAGENT_CHECKPOINT_THRESHOLD` | Context usage ratio that triggers safety handling; defaults to `0.75` |
| `HYPERAGENT_COMPACT_ENABLED` | Set falsey to disable semantic context compaction before checkpoint fallback; defaults to true |
| `HYPERAGENT_COMPACT_THRESHOLD` | Optional context usage ratio for compaction; unset means use `HYPERAGENT_CHECKPOINT_THRESHOLD` |
| `HYPERAGENT_COMPACT_TARGET_RATIO` | Target context ratio after compaction; defaults to `0.45` |
| `HYPERAGENT_MAX_COMPACTIONS` | Maximum semantic compactions per stage attempt; defaults to 3 |
| `HYPERAGENT_MAX_COMPACTION_TOKENS` | Maximum output tokens for the internal compaction call; defaults to 2048 |

Per-stage model overrides go under `provider.stage_models` in the YAML config
(stage_id → model name), for e.g. running cheaper models on prep/summary and
a stronger model on deepdive.

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
# Skip the slowest dynamic/intel work and reuse valid existing artifacts.
hyperagent analyze C:\path\to\sample.exe --profile fast

# Static-focused pass: prepare, static/unpack/static, deepdive, report, summary.
hyperagent analyze C:\path\to\sample.exe --static-only

# Keep the full profile but explicitly skip expensive optional stages.
hyperagent analyze C:\path\to\sample.exe --skip-dynamic --skip-intel

# Do not reuse completed stage artifacts from reports/<sha256>/.
hyperagent analyze C:\path\to\sample.exe --no-cache

# Control local idalib-mcp startup for this run.
hyperagent analyze C:\path\to\sample.exe --ida-mcp never
```

`full` remains the default for maximum evidence. `fast` and `static-only` are designed to reduce turnaround time while developing or triaging: they skip `05-dynamic` and `06-intel`, limit retries with `HYPERAGENT_FAST_MAX_STAGE_ATTEMPTS`, and still validate any reused stage artifact before skipping work. With `--ida-mcp auto` (the default), HyperAgent starts local idalib MCP only when the selected stages need IDA tools.

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

Read-only browser for finished reports (`09-summary.json`) — see
`webui/README.md` for the full route list.

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
