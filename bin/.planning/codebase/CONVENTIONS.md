# Conventions

## Code Style

- **Language**: Python 3.10+ (CPython 3.11 confirmed from `__pycache__` bytecode).
- **No formal linter config found**: No `.flake8`, `.pylintrc`, `pyproject.toml`, `setup.cfg`, or `tox.ini` present in the project root. `.gitignore` includes `.ruff_cache/`, implying Ruff may have been used at some point but is not actively configured.
- **VSCode settings** are C/C++ compiler settings only — no Python linter/formatter settings are configured.
- **Indentation**: 4 spaces (consistent across all Python files).
- **Line length**: No enforced limit; some lines reach 120+ characters (e.g., in `agents/native_agent.py`, string literals in instructions).
- **String quotes**: Double quotes preferred for string literals; single quotes appear occasionally. No strict enforcement.
- **Trailing whitespace / blank lines**: Inconsistently handled — some files have trailing blank lines, some do not.
- **Type annotations**: Used consistently on method signatures throughout the codebase (e.g., `-> Dict[str, Any]`, `-> str | None`). Uses both `typing` module imports (`Dict`, `Any`, `List`, `Optional`) and newer union syntax (`str | None`, `list[str]`) introduced in Python 3.10+.

## Naming Conventions

- **Classes**: `PascalCase` — e.g., `HyperAgentOrchestrator`, `DIEHandler`, `NativeAgent`, `DotNetAgent`, `ScriptAgent`, `UnsortAgent`, `YaraHandler`, `AnalysisType`.
- **Methods / Functions**: `snake_case` — e.g., `run_die`, `parse_die_text_output`, `get_file_hash`, `analyze`, `run_goose_analysis`.
- **Private/internal methods**: Prefixed with a single underscore `_` — e.g., `_load_config`, `_get_file_hash`, `_abs_path`, `_tool_config`, `_probe_http`, `_run_cmd`, `_run_goose`, `_compile_rules`.
- **Static methods**: Used for pure utility functions that don't need instance state — e.g., `filter_goose_report`, `filter_goose_report` (duplicated across agents), `_pick_interesting_cs_files`.
- **Variables**: `snake_case` — e.g., `file_path`, `analysis_type`, `die_data`, `goose_report_raw`, `clean_rp`.
- **Constants / Enum values**: `UPPER_SNAKE_CASE` for Enum members — e.g., `AnalysisType.NATIVE`, `AnalysisType.DOTNET`, `AnalysisType.PYTHON_SCRIPT`, `AnalysisType.UNKNOWN`.
- **Files**: `snake_case` — e.g., `die_handler.py`, `native_agent.py`, `dotnet_agent.py`, `script_agent.py`, `unsort_agent.py`, `yara_handler.py`.
- **Modules / Packages**: `snake_case` directory names — `agents/`, `core/`.
- **Log prefixes**: Consistent use of bracket-prefixed log tags: `[INFO]`, `[ERROR]`, `[WARN]`, `[DEBUG]`, `[*]`, `[-]` — a mix of severity levels and operational steps (e.g., `[*]` for progress, `[-]` for failures).

## Code Organization

- **Project structure**:
  ```
  /
  ├── main.py              # Entry point — HyperAgentOrchestrator class + CLI
  ├── api.py               # FastAPI application (REST endpoints)
  ├── config.yaml          # Tool paths and MCP configuration
  ├── requirements.txt     # Pip dependencies
  ├── core/
  │   ├── __init__.py      # (empty)
  │   ├── die_handler.py   # DIE tool wrapper + file type classifier
  │   └── yara_handler.py  # YARA rules compiler + scanner (in git, not on disk)
  └── agents/
      ├── __init__.py      # Re-exports the three main agents
      ├── native_agent.py  # IDA Pro + Goose integration for native binaries
      ├── dotnet_agent.py  # dnSpy + Goose integration for .NET binaries
      ├── script_agent.py  # pyinstxtractor + pycdas + Goose for Python binaries
      └── unsort_agent.py  # Stub for unrecognized file types
  ```

- **Class-per-file**: One primary class per file, following a single-responsibility pattern.
- **Agent pattern**: All agents implement a common `async def analyze(self, file_path: str) -> Dict[str, Any]` interface, though no abstract base class enforces this contract.
- **Orchestrator pattern**: `main.py`'s `HyperAgentOrchestrator` acts as a facade/router — it calls `DIEHandler.identify()` then delegates to the appropriate agent.
- **Config-driven**: All agents and the handler accept a `config_path: str = "config.yaml"` parameter; configuration is loaded via `yaml.safe_load`.
- **Code duplication**: `filter_goose_report` (static method) is copy-pasted identically across `NativeAgent`, `DotNetAgent`, and `ScriptAgent` — no shared utility module extracts this.
- **Commented-out code**: Significant amounts of commented-out code present (e.g., `de4dot` integration in `dotnet_agent.py`, `capa`/`floss` tasks in `native_agent.py`, `/health` endpoint in `api.py`). This reflects active development and partial feature removal.
- **`__init__.py` for agents**: Explicitly re-exports `NativeAgent`, `DotNetAgent`, `ScriptAgent` — `UnsortAgent` is intentionally excluded from the package-level export.
- **`if __name__ == "__main__":` guards**: Present in `main.py`, `core/die_handler.py` (with a mock usage comment). Not present in agents.

## Error Handling

- **Broad `except Exception as e` catch-all**: Used heavily throughout the codebase. Specific exceptions like `FileNotFoundError` are caught separately where expected (e.g., in `api.py` HTTP exception mapping, `NativeAgent.run_goose_analysis`).
- **Graceful degradation**: On tool failure, methods return empty dicts `{}`, empty lists `[]`, or empty strings `""` rather than propagating exceptions — e.g., `DIEHandler.run_die()` returns `{}` on any error; `YaraHandler.match()` returns `[]`.
- **API layer**: `api.py` wraps orchestrator calls in try/except and maps `FileNotFoundError` → HTTP 404, all other exceptions → HTTP 500.
- **Subprocess errors**: Non-zero return codes are logged with `print()` but execution continues. Stderr is captured and printed for diagnostics.
- **Logging**: No structured logging library (e.g., `logging` module) is used. All status messages use `print()` with consistent bracket-tag prefixes (`[INFO]`, `[ERROR]`, `[WARN]`, etc.).
- **Config load errors**: `_load_config()` methods return `{}` on any exception (file not found, YAML parse error) and print the error — silent partial failure.

## Documentation

- **Docstrings**: Selectively used — present on some methods (e.g., `DIEHandler.parse_die_text_output`, `DIEHandler.run_die`, `NativeAgent._probe_http`, `YaraHandler._compile_rules`, `YaraHandler.match`), absent from many others (e.g., `NativeAgent._get_file_hash`, most `ScriptAgent` methods, all `UnsortAgent` methods).
- **Docstring style**: Single-line or short multi-line descriptions in triple-double-quotes `"""..."""`. No formal docstring convention (e.g., Google, NumPy, Sphinx) is followed.
- **Inline comments**: Common throughout — explain intent for non-obvious logic, subprocess command flags, encoding workarounds, and Windows-specific behavior. Some comments are bilingual (Vietnamese + English), reflecting the primary contributor's background: e.g., `# Bước 2: Chạy Goose Analysis`, `# Khởi động IDA MCP Server`.
- **TODO / FIXME**: Expressed as comments within commented-out blocks or `# tùy chọn` (optional) notes. No formal `TODO:` tagging convention.
- **README.md**: Present at project root with setup instructions, usage examples, and a development roadmap with checkbox status.

## Import Structure

- **Standard library first**, then third-party, then local — loosely followed but not enforced:
  - Example (`die_handler.py`): `subprocess`, `json`, `os`, `yaml`, `enum`, `typing` — all stdlib except `yaml`.
  - Example (`native_agent.py`): `asyncio`, `subprocess`, `os`, `yaml`, `typing`, `hashlib`, `re`, `shlex`, `time` — all stdlib except `yaml`.
  - Example (`api.py`): stdlib (`os`, `tempfile`, `uuid`, `pathlib`, `typing`), then `fastapi`, `pydantic`, then local (`main`).
- **`from __future__ import annotations`**: Only in `api.py` — used to enable PEP 563 postponed evaluation (for forward references). Not used in other files.
- **Unused imports**: Some imports appear unused (e.g., `json` in `die_handler.py` — `json` is imported but DIE output is parsed as text, not JSON, in the current implementation).
- **Relative imports**: Not used. All local imports use absolute paths (e.g., `from core.die_handler import DIEHandler`, `from agents.native_agent import NativeAgent`).
- **`agents/__init__.py`**: Provides explicit re-exports (`from .native_agent import NativeAgent`, etc.) enabling `from agents import NativeAgent` style usage.
