# HyperAgent

HyperAgent is an automated malware analysis orchestrator that routes files to appropriate analysis agents (Native, .NET, Script) and uses MCP (Model Context Protocol) to control tools like IDA Pro.

## Features
- **Smart Routing**: Uses `diec` (Detect It Easy) to identify file types and route them to specific agents.
- **MCP Integration**:
   + Supports IDA Pro through the `idalib-mcp` server for deep static analysis.
   + Supports DnSpy via `dnspyc` for .NET binaries.

## Setup

### IDA MCP Integration

1. **Install Dependencies**: 
   - Install IDA MCP plugin from [idalib-mcp](https://github.com/mrexodia/ida-pro-mcp)

   - Install [Claude Code](https://www.anthropic.com/claude-code) and ensure the `claude` command is available in your system PATH

   - Navigate to `<IDA_PATH>\idalib\python` and run `pip install .` to install `idalib`
   
   *Note: If you face issues when install, try copying the `Python` folder to lower permission directories and run pip again.*

   - Add the DIE CLI to your system PATH, or configure an explicit `tools.diec` path in `config.yaml`.
   - Configure the IDA MCP server command under `mcp.ida_server_command`. IDA itself is required for the MCP workflow, but this repository does not expose a `tools.ida` config key.

   - Prepare a virtual environment and install required packages
   ```bash
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Configuration**:
   - Edit `config.yaml` to set supported tool entries either to executable names that resolve via your system PATH, or to explicit executable paths.
   - `mcp.ida_server_command` controls how the IDA MCP server is launched.
   - `llm.claude_code_command` is a command-plus-arguments list, not just `['claude']`.

   Example
   ```yaml
   tools:
     diec: "diec.exe"                       # or "C:/Tools/diec.exe"
     de4dot: "de4dot.exe"                   # or an explicit path
     dnspy: "dnspyc.exe"                    # or "C:/Tools/dnspyc.exe"

   mcp:
     ida_server_command: ["uv", "run", "idalib-mcp"]

   llm:
     claude_code_command: ["claude"]        # e.g. ["claude", "--model", "sonnet"]
   ```

3. **Requirements**:
   - Python 3.10+
   - Installed tools: DIE and Claude Code
   - IDA Pro with `idalib` installed if you want native/IDA-backed analysis
   - `uv` package manager (optional, for running mcp server if configured).

### DnSpy MCP Integration
1. **Install Dependencies**:
   - Get a build of [dnspyc](https://github.com/dnSpyEx/dnSpy/releases/tag/v6.5.1)
   - Rename `dnSpy.Console.exe` to `dnspyc.exe`, then either add it to your system PATH or point `tools.dnspy` at its full path in `config.yaml`.
   - Ensure Claude Code is installed and the configured runner command is available, as above.

2. **Configuration**:
   - For .NET analysis, the relevant `config.yaml` fields are `tools.dnspy` for DnSpy Console and `llm.claude_code_command` for the Claude Code runner.
   - If you also use IDA-based analysis in the same setup, keep `mcp.ida_server_command` configured as shown above.
   
## Usage

```bash
python main.py path/to/malware.exe
```

## FastAPI (Input/Output)

Run the API server:

```bash
pip install -r requirements.txt
uvicorn api:app --host 0.0.0.0 --port 8000
```

Analyze by file path (JSON input → JSON output):

```bash
curl -X POST http://127.0.0.1:8000/analyze/path \
   -H "Content-Type: application/json" \
   -d "{\"file_path\": \"C:/path/to/sample.exe\"}"
```

Analyze by upload (multipart input → JSON output):

```bash
curl -X POST http://127.0.0.1:8000/analyze/upload \
   -F "file=@C:/path/to/sample.exe"
```

## Structure
- `core/`: Core logic (DIE handling, MCP client, Context Logger).
- `agents/`: Specific analysis agents (Native, DotNet, etc).
- `output/`: Generated reports.


## Development Roadmap & Status

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
