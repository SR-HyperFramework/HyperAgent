# HyperAgent

HyperAgent is a malware-analysis pipeline. Point it at a sample, it runs the
sample through a fixed sequence of stages — environment prep, static analysis,
unpacking, dynamic analysis, threat-intel lookups, deep-dive reasoning,
reporting, summary — and writes a JSON/Markdown report per stage to
`reports/<sha256>/`.

Each stage is one LLM call loop (an `AgentLoop`) with a curated tool subset,
driven directly through the Anthropic (or OpenAI) SDK — no Claude Code CLI
subprocess involved. This is the **v4 SDK rewrite**; the old CLI-subprocess
architecture (v3) is kept for reference under `skill/backup/`.

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
  -> 08-report         (Markdown report)
  -> 09-summary         (structured verdict JSON, what the web UI reads)
```

Each stage:
- gets only the tools listed for it in `hyperagent/tools/registry.py::STAGE_TOOLS`
- reads/writes its status through `STATE.json` in the sample's report directory
  (`hyperagent/pipeline_state.py`), so a run can resume mid-pipeline
- checkpoints and resumes automatically if it runs long enough to approach the
  model's context limit (`hyperagent/engine/checkpoint.py`)
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
├─ skill/backup/            # archived v3 CLI-subprocess pipeline (reference only)
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

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -e .
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
| `HYPERAGENT_ANTHROPIC_BASE_URL` | Point the Anthropic client at a compatible proxy/gateway instead of `api.anthropic.com` |
| `HYPERAGENT_SKILLS_ROOT` | Where per-stage `SKILL.md` files live (default `~/.claude/skills`) |
| `HYPERAGENT_VMX_PATH`, `HYPERAGENT_VM_SNAPSHOT`, `HYPERAGENT_GUEST_USER`, `HYPERAGENT_GUEST_PASSWORD` | VMware guest for the dynamic stage — no defaults, must be set to run `05-dynamic` |
| `HYPERAGENT_IDA_MCP_URL`, `HYPERAGENT_X64DBG_MCP_URL` | MCP endpoints for static/unpack/dynamic stages |
| `VT_API_KEY` | VirusTotal lookups in `06-intel` |

Per-stage model overrides go under `provider.stage_models` in the YAML config
(stage_id → model name), for e.g. running cheaper models on prep/summary and
a stronger model on deepdive.

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

Baseline as of this rewrite: 176 passed, 3 skipped. Each file under
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
