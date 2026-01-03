# HyperAgent MCP Orchestrator

HyperAgent is an automated malware analysis orchestrator that routes files to appropriate analysis agents (Native, .NET, Script) and uses MCP (Model Context Protocol) to control tools like IDA Pro. It aggregates findings using Google Gemini to provide a comprehensive analysis report.

## Features
- **Smart Routing**: Uses `diec` (Detect It Easy) to identify file types and route them to specific agents.
- **MCP Integration**: Controls IDA Pro via `idat` and `idalib-mcp` for deep static analysis.
- **Static Analysis**: Automates CAPA (Capabilities) and FLOSS (Strings) execution.
- **AI Reporting**: Generates human-readable reports using Gemini 1.5 Pro.

## Setup

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configuration**:
   - Edit `config.yaml` to set your paths for `diec`, `capa`, `floss`, and `ida`.
   - Set your `GEMINI_API_KEY` in `.env` or `config.yaml`.

3. **Requirements**:
   - Python 3.10+
   - Installed tools: DIE, IDA Pro, CAPA, FLOSS.
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