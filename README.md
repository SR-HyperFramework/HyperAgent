# HyperAgent IDA MCP Orchestrator

HyperAgent is an automated malware analysis orchestrator that routes files to appropriate analysis agents (Native, .NET, Script) and uses MCP (Model Context Protocol) to control tools like IDA Pro.

## Features
- **Smart Routing**: Uses `diec` (Detect It Easy) to identify file types and route them to specific agents.
- **MCP Integration**: Controls IDA Pro via `ida` and `idalib-mcp` for deep static analysis.

## Setup

1. **Install Dependencies**: 
   - Install IDA MCP plugin from [idalib-mcp](https://github.com/mrexodia/ida-pro-mcp)

   - Install [Goose](https://github.com/block/goose) and configure provider

   - Navigate to `<IDA_PATH>\idalib\python` and run `pip install .` to install `idalib`
   
   *Note: If you face issues when install, try copying the `Python` folder to lower permission directories and run pip again.*

   - Add IDA and DIE to your system PATH with `IDA_PATH` variable name.

   - Prepare a virtual environment and install required packages
   ```bash
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Configuration**:
   - Edit `config.yaml` of `Goose MCPClient` to set your paths for `diec` or skip this step if `diec` is in your system PATH.

   Example
   ```yaml
   GOOSE_PROVIDER: github_copilot
   GOOSE_MODEL: gpt-4.1
   extensions:
   ida:
      enabled: true
      type: sse
      name: ida
      description: demo
      uri: http://localhost:8745/sse
      args:
      - mcp-cli
      - --host
      - 127.0.0.1
      - --port
      - '8745'
      timeout: 1800
      bundled: null
      available_tools: []
   GOOSE_MODE: auto
   ```

   *Note: 
   - `GOOSE_MODE` must be set at `auto` to prevent processing issues.

3. **Requirements**:
   - Python 3.10+
   - Installed tools: DIE, IDA Pro
   - `uv` package manager (optional, for running mcp server if configured).

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
