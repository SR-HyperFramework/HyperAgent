# Project Structure

## Directory Layout

```
HyperAgent/                          # Project root
├── main.py                          # CLI entry point; HyperAgentOrchestrator class
├── api.py                           # FastAPI HTTP server (uvicorn); 2 REST endpoints
├── config.yaml                      # Tool paths and MCP settings
├── requirements.txt                 # Python dependencies (fastapi, uvicorn, pyyaml, mcp, …)
├── die_result.json                  # Sample/debug DIE output (committed artifact)
├── README.md                        # Project documentation and setup guide
├── LICENSE
│
├── core/                            # Core infrastructure modules
│   ├── __init__.py                  # Empty (package marker)
│   └── die_handler.py               # DIEHandler class; AnalysisType enum; file classification
│
├── agents/                          # Analysis agent implementations
│   ├── __init__.py                  # Re-exports NativeAgent, DotNetAgent, ScriptAgent
│   ├── native_agent.py              # NativeAgent — IDA Pro + Goose pipeline for native binaries
│   ├── dotnet_agent.py              # DotNetAgent — dnSpy decompile + Goose for .NET binaries
│   ├── script_agent.py              # ScriptAgent — pyinstxtractor + pycdas + Goose for PyInstaller
│   └── unsort_agent.py              # UnsortAgent — stub/fallback for unknown file types
│
├── canvas/                          # Design/architecture diagrams
│   └── hyperagent_mcp.drawio        # draw.io system architecture diagram
│
├── resource/                        # Bundled external tool binaries (Windows)
│   ├── diec/                        # Detect It Easy CLI and Qt DLLs
│   │   ├── diec.exe
│   │   ├── Qt5Core.dll
│   │   ├── Qt5Script.dll
│   │   ├── db/                      # DIE signature database
│   │   └── db_custom/               # Custom DIE signatures
│   ├── pycdas/                      # Python bytecode disassembler binary
│   │   └── pycdas.exe
│   └── pyinstxtractor/              # PyInstaller extraction tool
│       └── pyix.exe
│
├── dotnet_output/                   # Runtime output: decompiled .NET C# source trees
│   └── <sha256_hash>/               # Per-sample output directory (hash-named)
│       └── solution.sln             # dnSpy-generated Visual Studio solution
│
├── uploads/                         # Runtime: uploaded files (keep_file=True mode)
│   └── <uuid>_<original_name>       # Persisted upload artifacts
│
├── pycdc/                           # Vendored C++ Python decompiler submodule (pycdc)
│   ├── ASTNode.{cpp,h}
│   ├── ASTree.{cpp,h}
│   ├── bytecode.{cpp,h}
│   ├── bytecode_ops.inl
│   ├── FastStack.h
│   ├── CMakeLists.txt
│   ├── bytes/                       # Per-Python-version bytecode maps
│   │   ├── bytecode_map.h
│   │   └── python_*.cpp             # Bytecode definitions for Python 1.0–3.12
│   ├── build/                       # Pre-compiled pycdc binaries (Windows)
│   │   ├── pycdc.exe                # Python decompiler (AST-level)
│   │   └── pycdas.exe               # Python bytecode disassembler (used by ScriptAgent)
│   └── tests/
│       └── input/                   # Python test scripts for pycdc coverage
│
├── venv/                            # Python virtual environment (not tracked by git)
│
├── __pycache__/                     # Python bytecode cache (auto-generated)
│
├── .planning/                       # Planning and documentation workspace
│   └── codebase/
│       ├── ARCHITECTURE.md          # This architecture document
│       └── STRUCTURE.md             # This structure document
│
├── .vscode/                         # VS Code workspace settings
│   ├── launch.json                  # Debug configuration (C++ GDB session)
│   ├── settings.json
│   └── c_cpp_properties.json
│
├── .gitignore
└── .git/
```

---

## Module Breakdown

### `main.py` — Orchestrator & CLI Entry Point
The central coordination module. Defines `HyperAgentOrchestrator` which:
- Loads `config.yaml` using PyYAML.
- Instantiates `DIEHandler` for file classification.
- Dispatches to the correct agent based on `AnalysisType`.
- Exposes `analyze()` (returns dict) used by both CLI and API, and `run()` for the CLI print loop.
- The module-level `main()` function is the `python main.py` entry point using `argparse`.

### `api.py` — HTTP API Layer
A thin FastAPI application that wraps the orchestrator:
- `POST /analyze/path` — Receives `{"file_path": "..."}` JSON body; validates file existence; delegates to orchestrator.
- `POST /analyze/upload` — Handles chunked multipart upload (1 MB chunks); writes to temp file or `uploads/`; delegates to orchestrator; cleans up temp file after analysis.
- Exposes a single global `orchestrator = HyperAgentOrchestrator()` instance (module-level singleton).
- Error handling: maps `FileNotFoundError` → HTTP 404, generic exceptions → HTTP 500.

### `core/die_handler.py` — File Classification
The only module in the `core` package that is currently implemented:
- `AnalysisType` enum: `NATIVE`, `DOTNET`, `PYTHON_SCRIPT`, `UNKNOWN`.
- `DIEHandler` class:
  - `run_die()` — Subprocess call to `diec.exe`; captures raw bytes to avoid Windows codepage issues.
  - `parse_die_text_output()` — Line-by-line text parser; no JSON parsing (DIE is called with text flags).
  - `identify()` — Runs DIE once; applies classification heuristics on parsed fields.
- Stub references in `__pycache__` suggest that `context_logger` and `mcp_client` modules existed or are planned but not currently present in source.

### `agents/native_agent.py` — Native Binary Analysis
Handles C/C++, Go, JavaScript-compiled, and any generic native PE/ELF binary:
- Depends on: `idalib-mcp` (external, launched as subprocess), `goose` CLI (external).
- Key methods: `_probe_http()`, `_wait_for_http_ready()`, `run_goose_analysis()`, `filter_goose_report()`, `analyze()`.
- Configurable via `config.yaml` `mcp:` section (`ida_startup_timeout_s`, `ida_probe_interval_s`).
- Windows-specific: uses `CREATE_NEW_PROCESS_GROUP` and `taskkill /T /F` for clean subprocess teardown.

### `agents/dotnet_agent.py` — .NET Assembly Analysis
Handles CLR-managed assemblies (.NET Framework, .NET Core):
- Depends on: `dnspyc.exe` (external), `goose` CLI (external).
- Key methods: `_resolve_executable()` (multi-location tool discovery), `_pick_interesting_cs_files()` (heuristic file selection), `run_dnspy_decompile()`, `run_goose_analysis()`, `filter_goose_report()`, `analyze()`.
- Outputs decompiled C# source to `dotnet_output/<sha256>/`.
- Safety guard: refuses to use output directories outside `output_root` (path traversal prevention).

### `agents/script_agent.py` — Python Script Analysis
Handles PyInstaller-packed Python executables:
- Depends on: `pyix.exe` (pyinstxtractor wrapper), `pycdas.exe` (bytecode disassembler), `goose` CLI.
- Key methods: `_extract_pyinstaller()`, `_disassemble_with_pycdas()`, `run_goose_analysis()`, `filter_goose_report()`, `analyze()`.
- Outputs extraction + `.pyasm` disassembly files to `python_output/<sha256>_extracted/`.
- Prioritizes `pyiboot`, `main`, `entry`, `script` named `.pyc` files for analysis.

### `agents/unsort_agent.py` — Unknown File Fallback
A minimal stub agent for files that could not be classified:
- Single `analyze()` method returning a static placeholder dict.
- Intended as a future extension point for generic analysis heuristics.

### `canvas/` — Architecture Diagrams
Contains a `draw.io` diagram (`hyperagent_mcp.drawio`) depicting the MCP integration topology. Not loaded at runtime.

### `resource/` — Bundled Tool Binaries
Pre-compiled Windows executables and associated runtime files bundled with the repo:
- `diec/` — Detect It Easy CLI (`diec.exe`) with Qt5 DLLs and signature databases.
- `pycdas/` — Python bytecode disassembler (`pycdas.exe`), output of building the `pycdc` submodule.
- `pyinstxtractor/` — PyInstaller archive extractor wrapper (`pyix.exe`).

### `pycdc/` — Vendored C++ Submodule
A Git submodule of the [pycdc](https://github.com/zrax/pycdc) Python decompiler:
- Provides `pycdc.exe` (AST-level decompiler) and `pycdas.exe` (bytecode disassembler).
- Only `pycdas.exe` is actively used by `ScriptAgent`; `pycdc.exe` is available but not wired in.
- The `build/` directory contains pre-compiled Windows binaries.
- `bytes/` contains per-Python-version bytecode opcode tables (Python 1.0 through 3.11+).

### `dotnet_output/` — Runtime .NET Decompilation Output
Generated at runtime by `DotNetAgent`. Each analyzed .NET binary gets a SHA-256-named subdirectory containing the full dnSpy-decompiled C# project (`.cs` files, `.sln`, etc.).

### `uploads/` — Runtime File Upload Storage
Generated at runtime by `api.py` when `keep_file=True` is passed to `POST /analyze/upload`. Files are named `<uuid_hex>_<original_filename>`.

---

## File Naming Conventions

| Convention | Examples | Notes |
|---|---|---|
| `snake_case` for Python modules | `die_handler.py`, `native_agent.py`, `script_agent.py` | All Python source files follow PEP 8 snake_case |
| `_agent.py` suffix for agents | `native_agent.py`, `dotnet_agent.py`, `script_agent.py`, `unsort_agent.py` | All agent files share this suffix |
| `PascalCase` for classes | `HyperAgentOrchestrator`, `DIEHandler`, `NativeAgent`, `DotNetAgent` | Standard Python class naming |
| `SCREAMING_SNAKE_CASE` for enums | `AnalysisType.NATIVE`, `AnalysisType.DOTNET` | Python `Enum` members |
| SHA-256 hex digest for output dirs | `dotnet_output/20d832deb632…/`, `python_output/<hash>_extracted/` | Deterministic, collision-resistant directory naming |
| `<uuid>_<safe_name>` for uploads | `uploads/a3f1…_malware.exe` | UUID prefix prevents filename collisions |
| `.pyasm` for disassembly output | `entrypoint.pyc.pyasm` | Appended to the `.pyc` source filename |
| `UPPERCASE.md` for docs | `README.md`, `ARCHITECTURE.md`, `STRUCTURE.md` | Top-level documentation convention |
