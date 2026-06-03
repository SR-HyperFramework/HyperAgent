# HyperAgent

HyperAgent is an automated malware analysis orchestrator that routes files to appropriate analysis agents (Native, .NET, Script) and uses MCP (Model Context Protocol) to control tools like IDA Pro.

## Features
- **Smart Routing**: Uses `diec` (Detect It Easy) to identify file types and route them to specific agents.
- **MCP Integration**:
  - Supports IDA Pro through the `idalib-mcp` server for deep static analysis.
  - Supports DnSpy via `dnspyc` for .NET binaries.
- **API + CLI**:
  - Run single-file analysis from the CLI.
  - Run upload- or path-based analysis through FastAPI.

## Windows setup

This repository is currently optimized for **Windows-only** setup.

### Requirements by feature

#### Required for core startup
- Python 3.10+
- Node.js LTS
- Claude Code CLI available as `claude` or installable via `npm`

Bootstrap will attempt to install Node.js LTS with `winget` and then install Claude Code CLI with `npm` if either is missing.

If automatic install is not possible, install them manually:

```powershell
winget install --id OpenJS.NodeJS.LTS -e
npm install -g @anthropic-ai/claude-code
```

Then verify:

```powershell
node --version
npm --version
claude --version
```

If `claude` is still not on PATH, rerun bootstrap with `HYPERAGENT_CLAUDE_CMD` set.

```powershell
$env:HYPERAGENT_CLAUDE_CMD = '["C:\\path\\to\\claude.exe"]'
powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1 -Force
```

```powershell
$env:HYPERAGENT_CLAUDE_HOME = 'C:\Users\ADMIN\.claude'
```
#### Required for native analysis
- Detect It Easy CLI (`diec`)
- IDA Pro if you want IDA-backed analysis
- `uv` for `uv run idalib-mcp`
- Claude plugin marketplace + `ida-pro-mcp` plugin

Bootstrap will attempt to:
- install `uv` if it is missing
- run `claude plugin marketplace add mrexodia/claude-marketplace`
- run `claude plugin install ida-pro-mcp@mrexodia`
- detect `C:\Program Files\IDA Professional*\idalib\python\py-activate-idalib.py`
- run the `py-activate-idalib.py` installer when found

#### Required for .NET analysis
- `dnspyc.exe` or `dnSpy.Console.exe` renamed to `dnspyc.exe`

#### Optional helpers for script analysis
- `pyinstxtractor.py`
- `pycdas`
- `de4dot.exe`

## Automated bootstrap

Run the bootstrap script from PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1
```

What it does:
- checks for Python
- installs Node.js LTS with `winget` if `node`/`npm` are missing
- installs Claude Code CLI with `npm` if `claude` is missing
- installs `uv` if it is missing
- creates `.venv` if needed
- installs Python dependencies from `requirements.txt`
- discovers external tools from PATH or environment-variable overrides
- generates a local `config.yaml` from `config.yaml.template`
- copies `skill/hyperagent-malware-analyze/` into the target machine's Claude skills directory
- installs the `mrexodia/claude-marketplace` marketplace source and the `ida-pro-mcp@mrexodia` plugin
- runs the `idalib` activation script automatically when IDA is detected
- verifies Python imports and app startup imports

Re-run it anytime after installing new tools. If you want to regenerate `config.yaml`, use:

```powershell
powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1 -Force
```

If you only want environment setup without final smoke checks:

```powershell
powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1 -SkipVerify
```

## Tool path overrides

If tools are not on PATH, set overrides before running the bootstrap.

```powershell
$env:HYPERAGENT_DIEC_PATH = 'C:\Tools\diec.exe'
$env:HYPERAGENT_DNSPYC_PATH = 'C:\Tools\dnspyc.exe'
$env:HYPERAGENT_DE4DOT_PATH = 'C:\Tools\de4dot.exe'
$env:HYPERAGENT_PYINSTXTRACTOR_PATH = 'C:\Tools\pyinstxtractor.py'
$env:HYPERAGENT_PYCDAS_PATH = 'C:\Tools\pycdas.exe'
$env:HYPERAGENT_CLAUDE_CMD = '["claude"]'
$env:HYPERAGENT_IDA_SERVER_COMMAND = '["uv","run","idalib-mcp"]'
$env:HYPERAGENT_CLAUDE_HOME = 'C:\Users\ADMIN\.claude'
$env:HYPERAGENT_IDA_ROOT = 'C:\Program Files\IDA Professional 9.0'
$env:HYPERAGENT_IDALIB_ACTIVATE = 'C:\Program Files\IDA Professional 9.0\idalib\python\py-activate-idalib.py'
```

Notes:
- `HYPERAGENT_CLAUDE_CMD` accepts either a JSON array string or a single command string.
- `HYPERAGENT_IDA_SERVER_COMMAND` accepts a JSON array string.
- `HYPERAGENT_CLAUDE_HOME` overrides the target Claude home directory; otherwise bootstrap installs into `$HOME/.claude/skills/hyperagent-malware-analyze`.
- `HYPERAGENT_IDA_ROOT` points bootstrap at a specific IDA installation root.
- `HYPERAGENT_IDALIB_ACTIVATE` points bootstrap at a specific `py-activate-idalib.py` script.
- The generated `config.yaml` is local to your machine and should not be committed.

## Configuration

`config.yaml.template` is the versioned template. `bootstrap.ps1` generates `config.yaml` from it.

Default template values are PATH-friendly:

```yaml
tools:
  diec: "diec.exe"
  de4dot: "de4dot.exe"
  dnspy: "dnspyc.exe"
  pyinstxtractor: "pyinstxtractor.py"
  pycdas: "pycdas"

mcp:
  ida_server_command: ["uv", "run", "idalib-mcp"]

llm:
  claude_code_command: ["claude"]
```

If `config.yaml` is missing, the app will now tell you to run `bootstrap.ps1` or copy the template first.

## Usage

### Claude skill

After bootstrap, the bundled skill is installed to:

```text
%USERPROFILE%\.claude\skills\hyperagent-malware-analyze
```

You can invoke it in Claude Code with a sample attachment, for example:

```text
/hyperagent-malware-analyze @sample.exe
```

### CLI

Activate the virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

Run analysis:

```powershell
python main.py C:\path\to\sample.exe
```

### FastAPI

Start the API server:

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn api:app --host 0.0.0.0 --port 8000
```

Analyze by file path:

```bash
curl -X POST http://127.0.0.1:8000/analyze/path \
  -H "Content-Type: application/json" \
  -d '{"file_path": "C:/path/to/sample.exe"}'
```

Analyze by upload:

```bash
curl -X POST http://127.0.0.1:8000/analyze/upload \
  -F "file=@C:/path/to/sample.exe"
```

## Structure
- `core/`: Core logic such as DIE handling, Claude runner, and pipeline logging.
- `agents/`: Specific analysis agents (Native, DotNet, Script).
- `uploads/`: Optional persisted API uploads.
- `dotnet_output/`, `script_output/`: Generated analysis artifacts.

## Development roadmap & status

### Phase 1: Create skeleton + FastAPI + basic schemas [COMPLETED]

### Phase 2: MCP adapters [IN PROGRESS]
- [ ] Implement Ghidra adapter
- [x] Implement IDA adapter
- [ ] Implement DnSpy adapter
- [ ] Implement Script adapter

### Phase 3: Static pipeline orchestrator [COMPLETED]
- [x] Orchestrate the flow: Ingest → DIE → Strategy → Tool → Output
- [x] Error handling and fallback mechanisms

### Phase 4: API integration [IN PROGRESS]
- [x] Finalize API endpoints for Hyperscope
- [ ] Ensure proper response format

### Phase 5: Optional [TODO]
- [ ] Caching mechanism
- [ ] Unpackers integration
- [ ] Extended heuristics
