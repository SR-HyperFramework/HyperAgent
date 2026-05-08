# Integrations

## External APIs

### Goose AI Agent CLI
- **Tool**: [Goose](https://github.com/block/goose) — an AI agent CLI by Block
- **Invocation**: `goose run --text <instruction>` spawned as a subprocess from all analysis agents (`NativeAgent`, `DotNetAgent`, `ScriptAgent`)
- **Role**: AI reasoning layer that interprets decompiled code / disassembly and produces structured malware analysis reports
- **Configuration**: Goose provider and model set externally via Goose's own config (e.g., `GOOSE_PROVIDER: github_copilot`, `GOOSE_MODEL: gpt-4.1`)
- **Extensions used**:
  - `ida` extension (SSE, `http://localhost:8745/sse`) — connects Goose to IDA Pro MCP server
  - `developer` extension — used by DotNet/Script agents to read decompiled `.cs` / `.pyasm` files from the filesystem

### IDA Pro via idalib-mcp
- **Tool**: [idalib-mcp](https://github.com/mrexodia/ida-pro-mcp) — MCP server for IDA Pro
- **Protocol**: MCP over SSE (`http://127.0.0.1:8745/sse`)
- **Invocation**: `uv run idalib-mcp --host 127.0.0.1 --port 8745 <file>` spawned as a subprocess by `NativeAgent`
- **Role**: Static analysis and decompilation of native binaries (PE/ELF); Goose connects to this server via the `ida` MCP extension
- **Health check**: `NativeAgent` probes `/sse` and `/` HTTP endpoints to confirm server readiness before sending work to Goose

### LLM Provider (via Goose)
- **Provider**: Configured externally in Goose's config — example shows `github_copilot` with `gpt-4.1`
- **Integration point**: Goose handles all LLM API calls; HyperAgent does not directly call any LLM API
- **API key**: Loaded via `python-dotenv` (`load_dotenv()` in `main.py`) — expected in a `.env` file (exact var name project-specific, passed to Goose environment)

## Databases

- **None** — HyperAgent has no database integration. All state is file-system based:
  - Analysis outputs written to `dotnet_output/<sha256>/` (C# decompilation) and `python_output/<sha256>_extracted/` (PyInstaller extraction)
  - Uploaded files temporarily stored in `uploads/` directory (path configurable via `HYPERAGENT_UPLOAD_DIR` env var)
  - Results returned as JSON responses; no persistence layer

## Authentication

- **None (currently)** — No auth middleware or auth providers are implemented in the FastAPI app
  - API endpoints (`/analyze/path`, `/analyze/upload`) are open/unauthenticated
  - `PyJWT 2.10.1` and `cryptography 46.0.3` are present as installed dependencies (likely pulled in transitively by `mcp` SDK) but not actively used in application code
  - `python-dotenv` is used to load environment variables (API keys for the LLM provider used by Goose)

## Cloud Services

- **None** — HyperAgent is a fully local/self-hosted application
  - No AWS, GCP, Azure, Vercel, or other cloud provider integrations
  - All analysis runs on the local machine with local tool invocations
  - Network activity is limited to localhost MCP SSE communication (`127.0.0.1:8745`) and outbound LLM calls made by the Goose CLI process

## Other Services & Tools

### Detect It Easy (DIE / diec)
- **Tool**: `diec.exe` (Detect It Easy CLI) — file type and packer/compiler identification
- **Role**: Entry-point classification — determines whether a binary is Native, .NET, Python (PyInstaller), or Unknown, routing it to the correct analysis agent
- **Protocol**: Local subprocess (`subprocess.run`) with CLI flags `-b -p -u`
- **Bundled**: Qt5-based binary bundled under `resource/diec/` (includes `Qt5Core.dll`, `Qt5Script.dll`, databases)

### dnSpy / dnspyc (DnSpy Console)
- **Tool**: [dnSpyEx](https://github.com/dnSpyEx/dnSpy) v6.5.1 — .NET decompiler
- **Invocation**: `dnspyc.exe -o <output_dir> <file>` via `DotNetAgent`
- **Role**: Decompiles .NET assemblies to C# source files for Goose AI analysis
- **Setup**: Must be added to system PATH as `dnspyc.exe`

### pyinstxtractor (pyix)
- **Tool**: `pyix.exe` — PyInstaller bundle extractor
- **Role**: Extracts PyInstaller-packed Python executables to raw `.pyc` bytecode files
- **Invocation**: Subprocess call by `ScriptAgent`
- **Config key**: `tools.pyix` in `config.yaml`

### pycdc / pycdas
- **Tool**: pycdas (Python bytecode disassembler) — C++ source bundled in `pycdc/`
- **Role**: Disassembles `.pyc` files to `.pyasm` bytecode text for Goose AI to analyze
- **Invocation**: `pycdas.exe <file.pyc>` via `ScriptAgent._disassemble_with_pycdas()`
- **Config key**: `tools.pycdas` in `config.yaml`

### de4dot (Planned / Commented Out)
- **Tool**: `de4dot.exe` — .NET deobfuscator
- **Role**: Deobfuscate/clean .NET assemblies before decompilation (currently commented out in `DotNetAgent`)
- **Config key**: `tools.de4dot` in `config.yaml`

### MCP Protocol (Model Context Protocol)
- **SDK**: `mcp 1.25.0` (Anthropic open-source)
- **Transport**: SSE (Server-Sent Events) over HTTP on localhost
- **Role**: Structured tool-calling protocol between Goose AI agent and analysis backends (IDA Pro)
- **Future**: Ghidra adapter and Script adapter planned (roadmap Phase 2)

### Graphviz (Planned)
- **Tool**: Graphviz / `dot` CLI
- **Role**: Python script analysis visualization (mentioned in README for Python MCP Integration, not yet implemented)
