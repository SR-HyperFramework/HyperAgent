# Tech Stack

## Languages

- **Python 3.11.9** — primary application language (confirmed via venv `pyvenv.cfg`)
  - Minimum supported: Python 3.10+ (per README)
- **C++** — bundled `pycdc` source (bytecode decompiler tool, not runtime Python)
- **YAML** — configuration (`config.yaml`)

## Frameworks & Libraries

### Web Framework
- **FastAPI 0.124.4** — REST API server (`api.py`), provides `/analyze/path` and `/analyze/upload` endpoints
- **Starlette 0.50.0** — ASGI foundation underlying FastAPI
- **Pydantic 2.12.5** — request/response model validation (`BaseModel` used in `api.py`)
- **pydantic-core 2.41.5** — Pydantic v2 Rust core
- **pydantic-settings 2.12.0** — settings management via env vars

### MCP (Model Context Protocol)
- **mcp 1.25.0** — Anthropic/open-source Model Context Protocol SDK; used for tool integrations (IDA Pro, DnSpy)

### Async / HTTP
- **anyio 4.12.0** — async I/O compatibility layer
- **httpx 0.28.1** — async HTTP client
- **httpx-sse 0.4.3** — SSE (Server-Sent Events) client for httpx; used to communicate with MCP SSE endpoints
- **sse-starlette 3.1.2** — SSE server support for Starlette/FastAPI
- **h11 0.16.0** — HTTP/1.1 protocol implementation
- **httpcore 1.0.9** — low-level HTTP core for httpx

### Security / Crypto
- **cryptography 46.0.3** — general-purpose cryptography
- **PyJWT 2.10.1** — JSON Web Token support
- **cffi 2.0.0** — C foreign function interface (dependency of cryptography)
- **pycparser 2.23** — C parser (dependency of cffi)

### Utilities
- **PyYAML 6.0.2** — YAML config loading (`config.yaml`)
- **python-dotenv 1.1.0** — `.env` file loading for API keys and environment variables
- **python-multipart 0.0.20** — multipart file upload parsing for FastAPI
- **click 8.3.1** — CLI framework (used by uvicorn and other tools)
- **colorama 0.4.6** — cross-platform colored terminal output (Windows)
- **jsonschema 4.25.1** — JSON schema validation
- **jsonschema-specifications 2025.9.1** — JSON Schema spec definitions
- **referencing 0.37.0** — JSON reference resolution
- **rpds-py 0.30.0** — persistent data structures (Rust)
- **attrs 25.4.0** — class utilities
- **idna 3.11** — international domain names
- **certifi 2025.11.12** — TLS/SSL certificate bundle
- **typing-extensions 4.15.0** — backported typing features
- **typing-inspection 0.4.2** — runtime type inspection
- **annotated-doc 0.0.4** — annotated documentation utility

### Windows-specific
- **pywin32 311** — Windows API bindings (process management, `taskkill` integration)

## Runtime & Build

### Runtime
- **Python 3.11.9** (CPython, Windows x64)
- **Uvicorn 0.38.0** — ASGI server with `[standard]` extras; runs FastAPI app
  - Launch: `uvicorn api:app --host 0.0.0.0 --port 8000`
- **asyncio** — built-in Python async engine; all agents use `async/await` and `asyncio.create_subprocess_exec`

### Build / Package Management
- **pip 24.0** — Python package manager
- **venv** — virtual environment at `./venv/`
- **uv** — optional fast package runner; used to launch `idalib-mcp` MCP server (`uv run idalib-mcp`)
- **setuptools 65.5.0** — packaging

### Platform
- **Windows** (primary target — uses `diec.exe`, `de4dot.exe`, `dnspyc.exe`, `CREATE_NEW_PROCESS_GROUP`, `taskkill`)
- Linux/macOS partially supported (fallback `server_proc.terminate()` path present)

### External Bundled Tools (non-Python, in `resource/` and `pycdc/`)
- **diec.exe (Detect It Easy CLI)** — file type/packer detection; Qt5-based, bundled under `resource/diec/`
- **pycdc / pycdas** — Python bytecode decompiler/disassembler (C++ source in `pycdc/`); produces `.pyasm` files
- **pyix.exe (pyinstxtractor)** — PyInstaller bundle extractor

## Dependencies

> From `requirements.txt` (direct) — installed versions from venv:

| Package | Version | Purpose |
|---|---|---|
| `mcp` | 1.25.0 | Model Context Protocol SDK |
| `pyyaml` | 6.0.3 | YAML config parsing |
| `python-dotenv` | 1.2.1 | `.env` environment loading |
| `fastapi` | 0.124.4 | REST API framework |
| `uvicorn[standard]` | 0.38.0 | ASGI server |
| `python-multipart` | 0.0.20 | File upload parsing |

## Dev Dependencies

> No explicit dev-only dependency file found (`requirements-dev.txt`, `pyproject.toml`, etc. absent).
> The following are present in the venv but serve infrastructure/dependency roles:

| Package | Version | Role |
|---|---|---|
| `setuptools` | 65.5.0 | Packaging |
| `pip` | 24.0 | Package management |
| `pydantic` | 2.12.5 | Data validation / schema |
| `starlette` | 0.50.0 | FastAPI ASGI layer |
| `anyio` | 4.12.0 | Async backend |
| `httpx` | 0.28.1 | HTTP client |
| `click` | 8.3.1 | CLI (uvicorn/internal) |
| `colorama` | 0.4.6 | Colored output (Windows) |
| `jsonschema` | 4.25.1 | Schema validation |
| `certifi` | 2025.11.12 | SSL certificates |
| `cryptography` | 46.0.3 | Crypto primitives |
| `PyJWT` | 2.10.1 | JWT handling |
