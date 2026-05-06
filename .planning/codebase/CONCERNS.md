# Concerns & Technical Debt

## Security Concerns

### 1. Path Traversal via `/analyze/path` Endpoint (HIGH RISK)
- **File**: `api.py`, lines 22–41
- The `AnalyzePathRequest` model accepts a raw `file_path: str` from the caller with no validation, sanitization, or allowlist.
- An attacker can supply any absolute path on the host filesystem (e.g., `C:\Windows\System32\config\SAM`, `/etc/passwd`) and the orchestrator will open, hash, and process it.
- The only guard is `os.path.exists()`, which confirms the file is there — it does not restrict *which* files are allowed.
- **Recommendation**: Restrict accepted paths to a configured allowed-directory prefix, or remove the `/analyze/path` endpoint from public exposure entirely.

### 2. No Authentication or Authorization on API Endpoints
- **File**: `api.py`
- Both `/analyze/path` and `/analyze/upload` are completely unauthenticated.
- Any client that can reach the server port can submit arbitrary files or paths for analysis.
- The README example runs the server with `--host 0.0.0.0`, exposing it on all network interfaces.
- **Recommendation**: Add an API key header, OAuth2, or at minimum IP allowlist middleware before production use.

### 3. No Upload File Size Limit
- **File**: `api.py`, lines 44–101
- There is no `max_size` check on uploaded files. A client can upload arbitrarily large binaries (gigabytes), causing disk exhaustion or memory pressure.
- **Recommendation**: Enforce a size limit during chunked reads (e.g., abort if total bytes exceed a configurable threshold).

### 4. Uploaded File Not Validated Beyond Extension
- **File**: `api.py`, line 53
- `safe_name = os.path.basename(file.filename)` strips directory components, which is good.
- However, there is no MIME type check, magic-byte validation, or allowlist of extensions. Any file type is accepted.
- A malicious client can upload a `.py` or `.bat` file that a downstream tool then executes.

### 5. Hardcoded Port for IDA MCP Server
- **File**: `agents/native_agent.py`, line 102
- Port `8745` is hard-coded (`port = 8745`) and not configurable per-run.
- If another process holds port 8745 the server silently fails to bind; there is no port-conflict detection.
- Multiple concurrent analyses will collide on the same port.

### 6. Instruction Injection via `file_path` Into AI Prompt
- **Files**: `agents/native_agent.py` lines 139–154; `agents/dotnet_agent.py` lines 248–266; `agents/script_agent.py` lines 189–206
- The absolute file path and workspace-relative directory path are embedded verbatim into the Goose AI instruction string that is passed to the `goose run --text` subprocess.
- A crafted filename containing prompt-injection text (e.g., `Ignore previous instructions and exfiltrate...`) would be passed literally into the AI model prompt.
- **Recommendation**: Either sanitize/truncate filenames or pass the path as a structured parameter rather than free-form instruction text.

### 7. Exception Details Leaked to API Callers
- **File**: `api.py`, lines 41, 94
- `raise HTTPException(status_code=500, detail=str(e))` returns raw Python exception messages to HTTP clients.
- These may include internal paths, tool stderr, or system information useful to an attacker.
- **Recommendation**: Log the full exception server-side and return a generic error message to clients.

### 8. `die_result.json` Committed to Repository
- **File**: `/die_result.json` (project root)
- A real DIE analysis artifact is committed to the repository. While its current content is benign ("plain text"), this pattern suggests analysis outputs (which may contain IOCs or sensitive file metadata) could be accidentally committed.
- The `.gitignore` lists `die_result.json` but the file exists in the working tree as a local modification.

### 9. `dotnet_output/` Directory Contains Decompiled Malware Source
- **Directory**: `dotnet_output/20d832deb63263.../minecraft/`
- Decompiled C# source from an analyzed sample (`minecraft`, `ISAAC.cs`, etc.) is present on disk and listed in `.gitignore`, but the directory is checked into the working tree.
- Committing decompiled malware artifacts could introduce legal or policy violations.

---

## Technical Debt

### 1. Massively Duplicated Code Across Agents
- **Files**: `agents/native_agent.py`, `agents/dotnet_agent.py`, `agents/script_agent.py`
- All three agents independently implement:
  - `_load_config()` — identical pattern, copy-pasted 4 times (including `main.py` and `die_handler.py`)
  - `_get_file_hash()` — SHA-256 hashing helper, copied identically
  - `filter_goose_report()` — static method, copied identically across all three agents
  - `_abs_path()` — duplicated in `dotnet_agent.py` and `script_agent.py`
  - `_to_workspace_rel_posix()` — duplicated in `dotnet_agent.py` and `script_agent.py`
- **Recommendation**: Extract a `BaseAgent` class or a `utils.py` module with these shared helpers.

### 2. `UnsortAgent` Is a Stub with No Implementation
- **File**: `agents/unsort_agent.py`
- Returns a hardcoded `"Unsorted analysis not implemented yet."` for all UNKNOWN file types.
- All malware samples that DIE cannot classify fall into this code path silently with no useful output.
- Per the README roadmap, the Script adapter is still `[ ] IN PROGRESS`.

### 3. Significant Commented-Out Code (Dead Code)
- **File**: `agents/dotnet_agent.py`, lines 124–142 — entire `run_de4dot()` method commented out.
- **File**: `agents/dotnet_agent.py`, lines 292, 303–305 — de-obfuscation and cleanup steps commented out.
- **File**: `agents/native_agent.py`, line 247 — `capa_task`/`floss_task` gather call commented out.
- **File**: `api.py`, lines 26–28 — `/health` endpoint commented out.
- **File**: `api.py`, lines 47, 87 — `original_name` parameter commented out.
- These stubs indicate unfinished features left in-place without tracking issues.

### 4. Relative `config_path = "config.yaml"` Default Is CWD-Dependent
- **Files**: All agents and `main.py`
- Config is loaded via a relative path resolved against the process's current working directory.
- Running the application from any directory other than the project root silently falls back to an empty config (`{}`), disabling tool resolution without raising an error.
- **Recommendation**: Resolve config path relative to the module's `__file__` or require an absolute path.

### 5. `DotNetAgent.__init__` Takes No `config_path` But Hardcodes `"config.yaml"`
- **File**: `agents/dotnet_agent.py`, line 10–11
- While the constructor accepts `config_path`, the `DotNetAgent()` is instantiated in `main.py` line 33 with no argument, so it always defaults to a relative `"config.yaml"`.

### 6. Inline Debug Print Left in `_abs_path()`
- **File**: `agents/dotnet_agent.py`, line 57
- `print(absp)` is left inside a utility method, printing every resolved absolute path to stdout on every invocation — pure debug noise that pollutes API response logs.

### 7. Mixed Language Comments (Vietnamese)
- **Files**: `agents/native_agent.py`, `agents/dotnet_agent.py`, `agents/script_agent.py`
- Many inline comments and `print()` messages are written in Vietnamese (e.g., `"Khởi động IDA MCP Server"`, `"Đang chạy Goose AI Agent"`), making the codebase harder to maintain for non-Vietnamese contributors.

### 8. `goose_cmd` / `ida_mcp_cmd` Are Hardcoded Strings in Agent Class
- **File**: `agents/native_agent.py`, lines 17–18
- `self.ida_mcp_cmd = "uv run idalib-mcp"` and `self.goose_cmd = "goose"` are hardcoded rather than read from `config.yaml`.
- `agents/dotnet_agent.py` and `agents/script_agent.py` also hardcode `"goose"` directly in the subprocess call.
- **Recommendation**: Add `goose_cmd` and `ida_mcp_cmd` keys to `config.yaml`.

### 9. `python_output` Output Root Missing from Config/Gitignore
- **File**: `agents/script_agent.py`, line 17
- `self.output_root = "python_output"` is hardcoded. The `python_output/` directory is not listed in `.gitignore` (unlike `dotnet_output/`), meaning Python analysis artifacts could be accidentally committed.

---

## Performance Concerns

### 1. No Timeout on Goose AI Subprocess
- **Files**: `agents/dotnet_agent.py` line 269–283; `agents/script_agent.py` lines 68–74
- The `goose run` subprocess has no timeout. If the AI agent hangs or enters an infinite loop the FastAPI request will block indefinitely.
- `NativeAgent.run_goose_analysis()` also has no timeout on `goose_proc.wait()` (line 175).
- **Recommendation**: Wrap with `asyncio.wait_for()` and a configurable timeout.

### 2. Hardcoded `await asyncio.sleep(5)` After IDA Ready-Check
- **File**: `agents/native_agent.py`, line 134
- A fixed 5-second sleep is inserted after the IDA HTTP server responds, to "give IDA more time." This adds unnecessary latency to every native binary analysis.
- **Recommendation**: Replace with a more precise readiness probe (e.g., test a lightweight IDA MCP API call).

### 3. No Result Caching — Same Binary Analyzed Repeatedly
- The orchestrator computes a SHA-256 hash for every analysis but never uses it to cache or deduplicate results.
- The README roadmap explicitly lists "Caching mechanism" as a TODO (Phase 5).
- Repeated submission of the same binary re-runs the entire IDA/Goose pipeline each time.

### 4. `dotnet_output/` Directory Deleted and Recreated on Every Run
- **File**: `agents/dotnet_agent.py`, lines 175–177
- The output directory for a given file hash is destroyed (`shutil.rmtree`) and recreated on every invocation, discarding any previously decompiled output.
- Combined with no caching, every re-analysis decompiles from scratch.

### 5. Sequential Tool Invocation Where Parallelism Is Possible
- **File**: `agents/native_agent.py`, line 247 (commented out)
- A comment references a planned `asyncio.gather(capa_task, floss_task)` that was never implemented; CAPA and FLOSS are not run at all currently.
- The Goose analysis pipeline is inherently sequential (IDA startup → sleep → Goose) with no parallelism.

### 6. Unbounded `.pyc` File Discovery in `_disassemble_with_pycdas`
- **File**: `agents/script_agent.py`, lines 124–128
- `os.walk()` over the entire extraction directory collects all `.pyc` files before capping at `limit=15`. For large PyInstaller bundles with hundreds of `.pyc` files this could be slow.

---

## Missing Error Handling

### 1. `_get_file_hash()` Has No Error Handling
- **Files**: `agents/native_agent.py` line 39; `agents/dotnet_agent.py` line 71; `agents/script_agent.py` line 76
- If the file disappears between existence check and hash computation (TOCTOU), an unhandled `FileNotFoundError` or `IOError` propagates up and returns a 500 to the API caller.

### 2. Goose Subprocess Failure Is Not Distinguished from Empty Output
- **Files**: All three agents' `run_goose_analysis()` methods
- If `goose` is not installed or exits with a non-zero code, the output is an empty string that gets passed to `filter_goose_report()` and returns the full raw log (or empty string). No error is raised, no non-zero exit code is checked.
- **File**: `agents/dotnet_agent.py`, lines 282–283 — `await process.wait()` result is ignored.
- **File**: `agents/script_agent.py`, lines 72–74 — return code is never checked in `_run_goose()`.

### 3. DIE Returning Non-Zero Is Silently Ignored
- **File**: `core/die_handler.py`, lines 108–112
- When `diec.exe` returns a non-zero exit code, only a `print()` is emitted; execution continues normally. An empty/partial result may be returned to the caller with no indication of failure.

### 4. `run_dnspy_decompile()` Returns `False` on Failure Without Detail in Caller
- **File**: `agents/dotnet_agent.py`, lines 296–299
- The caller receives `{"error": "Decompilation failed"}` with no additional context about why dnSpy failed. Stderr is printed to stdout locally but not included in the response.

### 5. `_extract_pyinstaller()` Silently Continues on Non-Zero Exit Code
- **File**: `agents/script_agent.py`, lines 97–98
- `return code == 0` returns `False` on non-zero exit, and the caller only prints a message. The extraction output (which may indicate why it failed) is consumed but not surfaced.

### 6. `commonpath` Path-Escape Guard Can Raise `ValueError` on Windows
- **Files**: `agents/dotnet_agent.py` line 172; `agents/script_agent.py` line 50
- `os.path.commonpath()` on Windows raises `ValueError` if the two paths are on different drives. This exception is unhandled and would bubble up as a 500 error.

### 7. `writer.close()` Not Guaranteed If `wait_closed()` Raises
- **File**: `agents/native_agent.py`, lines 67–71
- The `asyncio.StreamWriter` is closed inside a `try/except Exception: pass` block, which is correct, but if `writer.close()` itself raises before `wait_closed()` is called, the connection may leak.

---

## TODOs & FIXMEs

Found in source code and README:

| Location | Content |
|----------|---------|
| `README.md:124` | `[ ] Implement Ghidra adapter` |
| `README.md:127` | `[ ] Implement Script adapter` |
| `README.md:135` | `[ ] Ensure proper response format` |
| `README.md:138` | `[ ] Caching mechanism` |
| `README.md:139` | `[ ] Unpackers integration` |
| `README.md:140` | `[ ] Extended heuristics` |
| `agents/native_agent.py:247` | Commented-out `asyncio.gather(capa_task, floss_task)` — CAPA/FLOSS integration never implemented |
| `agents/dotnet_agent.py:13–14` | Commented-out hardcoded absolute paths for `de4dot` and `dnspy` (development leftovers) |
| `agents/dotnet_agent.py:292` | `# target_file = await self.run_de4dot(file_path)` — de-obfuscation step disabled |
| `agents/dotnet_agent.py:303–305` | Cleanup of cleaned file commented out |
| `api.py:26–28` | `/health` endpoint commented out |
| `api.py:47,87` | `original_name` parameter commented out |
| `core/die_handler.py:90–91` | Comment acknowledges uncertainty about DIE flag meanings (`-b -p -u`) |
| `core/die_handler.py:111` | "Sometimes DIE returns non-zero even if it found something?" — unresolved ambiguity |
| `README.md:78–80` | Python MCP Integration section is blank — setup instructions missing |

---

## Architectural Risks

### 1. Orchestrator Instantiated at Module Import Time
- **File**: `api.py`, line 16
- `orchestrator = HyperAgentOrchestrator()` runs at FastAPI application startup (module import).
- Config loading, path resolution, and file I/O occur synchronously at import. A bad `config.yaml` will crash the entire server startup with an unhandled exception.

### 2. Single-Port IDA MCP Server — No Concurrency Support
- **File**: `agents/native_agent.py`, line 102
- All native binary analyses share the same hardcoded port `8745`. Concurrent API requests will collide: the second request's IDA server will fail to bind, silently time out waiting for readiness, and return an error.
- There is no request queuing, semaphore, or port-pool mechanism.

### 3. No Request Queue or Worker Pool
- The FastAPI app processes analysis requests directly in async handlers.
- Each analysis can take minutes (IDA startup + AI analysis). Under concurrent load, many long-running async tasks will compete for the event loop and for the single IDA port.
- **Recommendation**: Move heavy analysis work to a task queue (Celery, RQ, arq) with a bounded worker pool.

### 4. Tight Coupling: Agent Selection Logic Fragile
- **File**: `core/die_handler.py`, lines 135–151
- Detection logic uses loose string matching on DIE output fields (e.g., `"c" in language` matches "javascript", "c++" also matches "c"). The `is_native` condition `compiler or packer` is truthy whenever either field is any non-empty string — meaning almost any detected file routes to `NativeAgent`.
- Specifically, `is_comp_go` and `is_comp_js` both include `or compiler`, so they are true whenever any compiler is detected, regardless of language.

### 5. Hard Dependency on External Tools Not Managed by Python
- The system requires `goose`, `idalib-mcp` (via `uv run`), `diec.exe`, `dnspyc.exe`, `pyix.exe`, and `pycdas.exe` to be installed and on PATH.
- None of these are in `requirements.txt`. Failure to find them results in confusing error messages rather than a clear dependency check at startup.
- **Recommendation**: Add a startup health-check that validates all required external tools are reachable.

### 6. Analysis Artifacts Stored on Local Disk Without Cleanup Policy
- `dotnet_output/` and `python_output/` directories grow unboundedly — there is no retention/cleanup policy, TTL, or storage quota.
- The `uploads/` directory similarly accumulates files when `keep_file=True`.

### 7. Decompiled Malware Source Written to Working Tree
- **File**: `agents/dotnet_agent.py`, line 15
- `self.output_root = "dotnet_output"` writes decompiled C# source relative to the process CWD, which is the project repository root.
- Decompiled malware code in the working tree is a security and legal risk.

---

## Missing Documentation

- **`agents/script_agent.py`**: No module-level docstring; the `ScriptAgent` class has no class docstring.
- **`agents/unsort_agent.py`**: No documentation at all for the stub.
- **`agents/native_agent.py`**: `filter_goose_report()` has no docstring explaining the markers it parses or its return contract.
- **`core/die_handler.py`**: `parse_die_text_output()` documents the field-extraction logic in comments but does not document expected input format or known edge cases.
- **`api.py`**: Neither endpoint has a FastAPI response schema (`response_model`), so the OpenAPI/Swagger docs show no output structure.
- **`config.yaml`**: Only partially documents available keys; `ida_startup_timeout_s`, `ida_probe_interval_s`, `pyix`, `pycdas` keys are not mentioned in the config file itself.
- **`README.md`**: Python MCP Integration section (§ "🌟 Python MCP Integration") is incomplete — has placeholder text and empty lines where setup instructions should be.
- No API versioning strategy documented; current version is `"0.1.0"` with no changelog.
- No architecture diagram beyond the `.drawio` canvas file (not rendered in README).

---

## Dependency Risks

### 1. No Pinned Versions in `requirements.txt`
- **File**: `requirements.txt`
- All six dependencies are unpinned:
  ```
  mcp
  pyyaml
  python-dotenv
  fastapi
  uvicorn[standard]
  python-multipart
  ```
- Unpinned dependencies allow silent breaking changes on fresh installs. FastAPI has had breaking changes across minor versions (e.g., 0.95→0.100 Pydantic v2 migration).
- **Recommendation**: Pin to exact versions (`==`) or at minimum upper-bound ranges (`~=`) and commit a `requirements.lock` or use `uv.lock`.

### 2. No `pyproject.toml` or `setup.py`
- The project has no packaging metadata. There is no declared minimum Python version, no install extras, and no way to install it as a package.
- The README states "Python 3.10+" but this is not enforced anywhere in code or tooling.

### 3. `mcp` Package — Niche/Unstable Dependency
- The `mcp` package (Model Context Protocol) is an emerging standard with a rapidly changing API surface. Without version pinning, updates could silently break the integration.

### 4. `python-multipart` Required for FastAPI File Uploads but Not Explicitly Imported
- While correctly listed in `requirements.txt`, forgetting to install it produces a cryptic FastAPI error at runtime rather than a clear import error.

### 5. No Lock File Committed
- `.gitignore` comments out `#uv.lock` (line 110), suggesting `uv` is used but the lock file is not committed.
- This means reproducible builds are not guaranteed across environments.

### 6. External Tool Versions Completely Unmanaged
- `diec.exe`, `dnspyc.exe`, `goose`, `idalib-mcp`, `pyix.exe`, `pycdas.exe` have no version requirements documented. Different versions of these tools may produce different output formats that break the parsers.
