# Testing

## Framework

- **Historical**: `unittest` (Python standard library) — used in all test files that existed prior to the January 2026 refactor.
- **Current**: No test framework is active in the current codebase. No `pytest`, `unittest`, or any other test runner is installed or configured.
- **No pytest.ini, setup.cfg, pyproject.toml, or tox.ini** present in the project root — test runner configuration is entirely absent.
- `requirements.txt` does not include `pytest`, `pytest-asyncio`, `unittest`, or any test/coverage dependencies.

## Test Organization

**Current state**: All test files were **deleted** during the major refactor commit (`82a258f`, January 3 2026). The `__pycache__` directory retains compiled `.pyc` artifacts of the deleted files, confirming they existed on disk previously:
- `test_api.cpython-311.pyc`
- `test_die_integration.cpython-311.pyc`
- `test_parsing.cpython-311.pyc`
- `test_parsing_text.cpython-311.pyc`

**Historical test layout** (recovered from git history):

```
/                              ← All tests were at project root (flat layout)
├── test_api.py                ← Manual/smoke test script (not a unittest)
├── test_die_integration.py    ← unittest for DIE subprocess integration
├── test_parsing.py            ← unittest for JSON output parser
└── test_parsing_text.py       ← unittest for text output parser
```

Tests were co-located at the project root alongside source files — no dedicated `tests/` directory was ever established.

## Coverage

- **Estimated current coverage**: ~0% — no tests exist in the current codebase.
- **Historical coverage** (before the refactor deleted tests): 3 functional test files covered the old `app/services/die_service.py` module:
  - `test_die_integration.py`: 1 test — mocked subprocess calls to `run_die()`, asserted parsed `file_class` and `compiler` fields.
  - `test_parsing.py`: 1 test — exercised `parse_die_output()` with a mock JSON payload covering PE32, packer, compiler, language fields.
  - `test_parsing_text.py`: 1 test — exercised `parse_die_text_output()` with a mock multi-line text output covering PE64, linker, compiler, language, tool fields.
- **Never tested** (neither before nor after refactor):
  - Agent classes (`NativeAgent`, `DotNetAgent`, `ScriptAgent`, `UnsortAgent`)
  - `HyperAgentOrchestrator` orchestration logic
  - FastAPI endpoints (`api.py`)
  - Config loading logic
  - `YaraHandler`
  - Async workflows

## Test Types

**Historical test types** (deleted):
- **Unit tests** (`unittest.TestCase`): `test_parsing.py`, `test_parsing_text.py`, `test_die_integration.py` used `unittest.mock.patch` and `MagicMock` to isolate the service under test from the filesystem and subprocess.
- **Manual smoke test** (`test_api.py`): Not a proper test — a CLI script using `argparse` and `requests` to POST a file to the running FastAPI server. Requires the server to be live and a real binary file to be provided.

**Current test types**: None.

## Running Tests

**No tests to run currently.**

Historical command to run the deleted tests (inferred from standard Python conventions):
```bash
# Activate virtual environment first
venv\Scripts\activate    # Windows

# Run all unittest-style tests
python -m unittest discover -v

# Or run individual files
python -m unittest test_parsing
python -m unittest test_parsing_text
python -m unittest test_die_integration

# Manual API smoke test (requires running server)
uvicorn api:app --host 0.0.0.0 --port 8000
python test_api.py -file path/to/sample.exe
```

No `Makefile`, `tox.ini`, or CI configuration (e.g., GitHub Actions `.yml`) was found to automate test execution.

## Gaps

The following areas have **zero test coverage** in the current codebase:

1. **`core/die_handler.py`** — `DIEHandler.parse_die_text_output()`, `DIEHandler.run_die()`, `DIEHandler.identify()`, `DIEHandler.get_analysis_route()` are all untested. The parser logic is non-trivial and was previously covered by deleted tests.

2. **`core/yara_handler.py`** — `YaraHandler._compile_rules()` and `YaraHandler.match()` have no tests. Rule compilation fallback logic (batch vs. individual) is complex and error-prone.

3. **`agents/native_agent.py`** — `NativeAgent.filter_goose_report()`, `_probe_http()`, `_wait_for_http_ready()`, and the full `run_goose_analysis()` async workflow are untested.

4. **`agents/dotnet_agent.py`** — `DotNetAgent._resolve_executable()`, `_pick_interesting_cs_files()`, `run_dnspy_decompile()`, `filter_goose_report()`, and `run_goose_analysis()` have no tests.

5. **`agents/script_agent.py`** — `ScriptAgent._run_cmd()`, `_disassemble_with_pycdas()`, `filter_goose_report()`, and `run_goose_analysis()` have no tests.

6. **`main.py`** — `HyperAgentOrchestrator.analyze()` routing logic (the central dispatch table) has no tests.

7. **`api.py`** — FastAPI endpoints (`/analyze/path`, `/analyze/upload`) have no integration or unit tests.

8. **Async code**: The entire async subsystem (`asyncio.create_subprocess_exec`, `_probe_http`, MCP server startup/teardown) has never been tested — requires `pytest-asyncio` or equivalent.

9. **Error paths**: Error handling branches (config load failure, file-not-found, subprocess non-zero exit, encoding decode errors) are not covered by any test.

10. **No CI/CD pipeline**: No continuous integration is configured; tests are not automatically run on commits or pull requests.
