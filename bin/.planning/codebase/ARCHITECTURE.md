# Architecture

## Overview

HyperAgent is an automated malware analysis orchestrator designed for static binary analysis. It accepts an executable file (PE, .NET, PyInstaller-packed Python, or unknown), identifies its type using the Detect It Easy (DIE/diec) tool, routes it to the appropriate specialized analysis agent, and returns a structured JSON report.

Each agent orchestrates external tooling (IDA Pro via `idalib-mcp`, dnSpy via `dnspyc`, pyinstxtractor + pycdas) and an AI assistant (`goose` CLI) to produce a human-readable malware analysis report. The system exposes both a CLI entry point and a FastAPI HTTP server.

---

## Entry Points

### CLI — `main.py`
```
python main.py <path/to/binary>
```
- Instantiates `HyperAgentOrchestrator`, calls `orchestrator.run(file_path)`.
- Prints the final JSON result to stdout.
- Uses `argparse` for argument parsing; `asyncio.run()` drives the async pipeline.

### HTTP API — `api.py` (FastAPI, served via Uvicorn)
```
uvicorn api:app --host 0.0.0.0 --port 8000
```

| Method | Endpoint          | Description                                                    |
|--------|-------------------|----------------------------------------------------------------|
| POST   | `/analyze/path`   | Accepts JSON `{"file_path": "..."}`, analyzes the server-local file |
| POST   | `/analyze/upload` | Accepts a multipart file upload; optionally persists with `keep_file=true` |

Both endpoints delegate to the same `HyperAgentOrchestrator.analyze()` coroutine and return a unified JSON response.

---

## Core Components

### `HyperAgentOrchestrator` (`main.py`)
- **Role**: Top-level orchestrator / router.
- Loads `config.yaml` on initialization.
- Instantiates `DIEHandler` to classify the incoming file.
- Based on the returned `AnalysisType`, constructs the correct agent instance and calls `agent.analyze(file_path)`.
- Returns a normalized dict:
  ```json
  {
    "file_path": "...",
    "detected_type": "NATIVE | DOTNET | PYTHON_SCRIPT | UNKNOWN",
    "die": { ...die metadata... },
    "result": { ...agent report... }
  }
  ```

### `DIEHandler` (`core/die_handler.py`)
- **Role**: File-type classification via the external `diec.exe` (Detect It Easy CLI).
- Invokes `diec -b -p -u <file>` as a subprocess.
- Parses the plain-text output line-by-line to extract `file_class`, `packer`, `compiler`, `language`, `library`, `tool`, and `malware` fields.
- `identify(file_path)` → `(die_data: dict, AnalysisType)`
- Classification logic:
  - `.net` in library/compiler → `AnalysisType.DOTNET`
  - `python` in language or `pyinstaller` in packer → `AnalysisType.PYTHON_SCRIPT`
  - `c`, `c++`, or any detected compiler/packer → `AnalysisType.NATIVE`
  - Go/JavaScript language hits → `AnalysisType.NATIVE`
  - Anything else → `AnalysisType.UNKNOWN`

### `NativeAgent` (`agents/native_agent.py`)
- **Role**: Static analysis of native binaries (PE/ELF, Go, C/C++, etc.).
- **Tools used**: `idalib-mcp` (IDA Pro MCP HTTP server) + `goose` CLI AI agent.
- Workflow:
  1. Computes SHA-256 of the target file.
  2. Launches `idalib-mcp` as a background subprocess on `127.0.0.1:8745`.
  3. Polls `/sse` (SSE endpoint) and `/` via raw TCP until the MCP HTTP server is ready (configurable timeout, default 180 s).
  4. Waits an additional 5 s for IDA auto-analysis to settle.
  5. Sends a structured `goose run --text <instruction>` with a Senior Malware Researcher prompt including the IDA MCP SSE URL.
  6. Streams Goose stdout line-by-line, collecting the full log.
  7. Filters the raw log to extract the `**Start of Analysis** … **End of Analysis**` block, stripping MCP tool-call decorators.
  8. Terminates the IDA MCP server process (Windows: `taskkill /T /F`; Unix: `terminate()`).
- Returns: `{ file_name, file_hash, ai_analysis_report }`.

### `DotNetAgent` (`agents/dotnet_agent.py`)
- **Role**: Decompile and analyze .NET managed assemblies.
- **Tools used**: `dnspyc.exe` (dnSpy console) + `goose` CLI AI agent.
- Workflow:
  1. Computes SHA-256 → creates output directory `dotnet_output/<hash>/`.
  2. Runs `dnspyc -o <output_dir> <file>` to decompile the assembly to C# source files.
  3. Scans the decompiled output for "interesting" `.cs` files (by name keywords: `program.cs`, `assemblyloader.cs`, `mainwindow.xaml.cs`; or by content keywords: `load`, `inject`, `decrypt`, `http`, `shell`, etc.) — up to 15 files.
  4. Sends a structured `goose run --text <instruction>` with a Senior .NET Malware Researcher prompt and workspace-relative paths.
  5. Filters the raw Goose log to the analysis block.
- Returns: `{ file_name, file_hash, source_directory, ai_analysis_report }`.
- Helper: `_resolve_executable()` searches config, PATH, and repo-root-relative paths for the tool binary.

### `ScriptAgent` (`agents/script_agent.py`)
- **Role**: Analyze PyInstaller-packed Python executables.
- **Tools used**: `pyix.exe` (pyinstxtractor) + `pycdas.exe` (Python bytecode disassembler) + `goose` CLI.
- Workflow:
  1. Computes SHA-256 → creates extraction directory `python_output/<hash>_extracted/`.
  2. Runs `pyix.exe <file>` to unpack the PyInstaller bundle.
  3. Walks the extraction directory for `.pyc` files; runs `pycdas <file.pyc>` on each, saving output to `<file.pyc>.pyasm`.
  4. Prioritizes `pyiboot`, `main`, `entry`, `script` named files; processes up to 15 `.pyc` files.
  5. Sends a `goose run --text <instruction>` with a Python Bytecode Specialist prompt listing the generated `.pyasm` files.
  6. Filters and returns the report.
- Returns: `{ file_name, file_hash, extracted_path, ai_analysis_report }`.

### `UnsortAgent` (`agents/unsort_agent.py`)
- **Role**: Stub/fallback for unidentified file types.
- Returns a static `{ type: "UNSORT", info: "Unsorted analysis not implemented yet." }`.

---

## Data Flow

```
User Input (file path)
        │
        ▼
[Entry Point: CLI main.py  OR  FastAPI api.py]
        │
        ▼
HyperAgentOrchestrator.analyze(file_path)
        │
        ├─► DIEHandler.identify(file_path)
        │       │
        │       ├─ subprocess: diec.exe -b -p -u <file>
        │       ├─ parse_die_text_output()
        │       └─ returns (die_data: dict, AnalysisType enum)
        │
        ├─ AnalysisType.NATIVE      ──► NativeAgent.analyze()
        │                                   │
        │                                   ├─ SHA-256 hash
        │                                   ├─ subprocess: idalib-mcp (background)
        │                                   ├─ HTTP probe loop (127.0.0.1:8745)
        │                                   └─ subprocess: goose run --text <prompt>
        │                                         └─ streams stdout → filter → report
        │
        ├─ AnalysisType.DOTNET      ──► DotNetAgent.analyze()
        │                                   │
        │                                   ├─ SHA-256 hash
        │                                   ├─ subprocess: dnspyc -o <dir> <file>
        │                                   ├─ pick interesting .cs files
        │                                   └─ subprocess: goose run --text <prompt>
        │                                         └─ collect stdout → filter → report
        │
        ├─ AnalysisType.PYTHON_SCRIPT ─► ScriptAgent.analyze()
        │                                   │
        │                                   ├─ SHA-256 hash
        │                                   ├─ subprocess: pyix.exe (PyInstaller unpack)
        │                                   ├─ subprocess: pycdas per .pyc → .pyasm
        │                                   └─ subprocess: goose run --text <prompt>
        │                                         └─ collect stdout → filter → report
        │
        └─ AnalysisType.UNKNOWN     ──► UnsortAgent.analyze()
                                            └─ static stub response

        ▼
Final Response (JSON):
{
  "file_path": "...",
  "detected_type": "...",
  "die": { file_class, packer, compiler, language, library, tool, malware },
  "result": { file_name, file_hash, ai_analysis_report, ... }
}
```

For the **upload** endpoint, `api.py` additionally:
- Writes the uploaded bytes to a temp file (or a stable `uploads/<uuid>_<name>` if `keep_file=True`).
- Appends `upload_id` and `saved_path` to the response.
- Deletes the temp file in the `finally` block.

---

## Design Patterns

| Pattern | Where Applied |
|---|---|
| **Orchestrator / Strategy** | `HyperAgentOrchestrator` selects an agent (strategy) at runtime based on `AnalysisType` returned by DIE |
| **Chain of Responsibility** | DIE classification → agent dispatch → external tool invocation → AI summarization |
| **Facade** | Each agent hides multi-step subprocess orchestration behind a single `analyze()` coroutine |
| **Factory (implicit)** | `HyperAgentOrchestrator.analyze()` acts as a factory constructing the right agent |
| **Template Method** | All agents share the same `analyze()` public signature; each overrides the internal steps |
| **Subprocess Bridge** | External tools (diec, idalib-mcp, dnspyc, pyix, pycdas, goose) are driven via `asyncio.create_subprocess_exec` |
| **Polling/Probe loop** | `NativeAgent._wait_for_http_ready()` probes the MCP HTTP port with configurable timeout and interval |
| **Report Filtering (Marker Extraction)** | All agents share the `filter_goose_report()` static method pattern to extract bounded `**Start**…**End**` report sections and strip MCP tool decorators |

---

## Key Abstractions

### `AnalysisType` (Enum — `core/die_handler.py`)
```python
class AnalysisType(Enum):
    NATIVE         # C/C++, Go, JS-compiled, generic native PE/ELF
    DOTNET         # .NET managed assembly
    PYTHON_SCRIPT  # PyInstaller-packed Python
    UNKNOWN        # Unrecognized; handled by UnsortAgent stub
```

### Agent Interface (informal / duck-typed)
All agents expose:
```python
async def analyze(self, file_path: str) -> Dict[str, Any]: ...
```
There is no formal ABC/Protocol class; the interface is enforced by the orchestrator calling `agent.analyze()`.

### `HyperAgentOrchestrator` (public API surface)
```python
async def analyze(file_path: str) -> dict  # used by both CLI and FastAPI
async def run(file_path: str)              # CLI-only; calls analyze() and prints
```

### Goose Report Contract
All AI-generated reports follow a plain-text convention:
```
**Start of Analysis**
...structured report content...
**End of Analysis**
```
The `filter_goose_report()` static method (duplicated across all agents) extracts this block and strips MCP tool-call lines (e.g., `─── tool_name | ida ───`).

### Configuration (`config.yaml`)
```yaml
tools:
  diec: "diec.exe"      # Detect It Easy CLI
  de4dot: "de4dot.exe"  # .NET deobfuscator (reserved, commented out)
  dnspy: "dnspyc.exe"   # dnSpy console decompiler
mcp:
  ida_server_command: ["uv", "run", "idalib-mcp"]
  ida_startup_timeout_s: 180   # optional override
  ida_probe_interval_s: 0.5    # optional override
```
Tool resolution order (DotNetAgent / ScriptAgent): config value → PATH lookup → repo-root-relative path.
