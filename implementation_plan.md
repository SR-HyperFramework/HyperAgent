# HyperAgent v3 → v4 SDK Migration — Hand-off & Implementation Plan

---

## 1. Executive Summary

Migrate HyperAgent from a **Claude Code CLI subprocess** architecture to a **self-hosted agentic loop using the Anthropic SDK** (primary) with a provider abstraction layer for OpenAI (secondary). The entire pipeline logic, state management, schema contracts, and analysis quality remain unchanged, but the engine is rebuilt from the ground up to serve **scientific research and experimental evaluation**.

**Research Scope & Objectives**:
- **Reproducibility & Ablation Studies**: Replace opaque CLI execution with a transparent execution engine layer, allowing researchers to swap LLM providers (Anthropic vs. OpenAI), toggle tools, and evaluate model performance under controlled conditions.
- **Granular Telemetry**: Expose internal agent states, including token consumption, reasoning traces, API latency, and context degradation metrics.
- **Security Evaluation**: Sandbox execution boundaries (replacing generic shells with strict tools) and isolate prompt injection handling to study LLM safety in hostile environments (malware analysis).

**Confirmed architectural decisions**:
- Provider: Anthropic SDK first, OpenAI stub (supports cross-model benchmarking)
- MCP: Keep JSON-RPC protocol, write a standalone MCP client for instrumentation
- Subagent: In-process (spawn additional LLM calls for hierarchical agent research)
- Deployment: FastAPI server (enables batch job submission and evaluation)
- API keys: Both Anthropic and OpenAI available

---

## 2. Current Architecture — Coupling Audit

### 2.1 Current Execution Flow

```
User → python claude_spawn.py sample.exe
         │
         ├─ sha256_of(sample) → report_dir = reports/<sha256>
         ├─ pipeline_state.ensure_state(report_dir)
         │
         └─ for each Stage in STAGES:
              ├─ Check STATE.json → skip if completed
              ├─ Build prompt: "/<skill-name> @<input_file>"
              ├─ Build command: ["claude", "--dangerously-skip-permissions", "-p", ...]
              │    └─ if reads_sample_content: add "--append-system-prompt" INJECTION_GUARD
              ├─ subprocess.run(command, env={HYPERAGENT_*}, cwd=input.parent)
              │
              │   Inside Claude Code process:
              │    ├─ Parse /skill-name → load SKILL.md as system prompt
              │    ├─ Parse @file → provide file context
              │    ├─ Auto-discover MCP servers (x64dbg, IDA Pro)
              │    ├─ Execute agentic loop (tool calls, reasoning)
              │    ├─ Monitor context usage (80% → checkpoint)
              │    └─ Subagent delegation via "Agent tool"
              │
              ├─ Check STATE.json after exit:
              │    ├─ status=running → resume (loop)
              │    ├─ status=completed → validate artifact → next stage
              │    └─ else → fail
              └─ MAX_STAGE_ATTEMPTS = 20
```

### 2.2 Coupling Points — Per-Skill Audit

Each SKILL.md has **3 types of coupling** that must be addressed:

| Coupling Type | Description | Found in |
|---------------|-------------|----------|
| **C1: Claude Code CLI invocation** | `claude -p`, `--dangerously-skip-permissions`, `--append-system-prompt` | [claude_spawn.py](file:///e:/Github/HyperAgent/claude_spawn.py) L189-193 |
| **C2: Claude Code skill resolution** | `/<skill-name> @<file>` prompt pattern | [claude_spawn.py](file:///e:/Github/HyperAgent/claude_spawn.py) L189 |
| **C3: Claude Code Agent tool** | `subagent_type: general-purpose` for delegation | [hyperagent-static](file:///e:/Github/HyperAgent/skill/backup/hyperagent-malware-analyze/v3/hyperagent-static/SKILL.md) L109-119, [hyperagent-dynamic](file:///e:/Github/HyperAgent/skill/backup/hyperagent-malware-analyze/v3/hyperagent-dynamic/SKILL.md) L60-76 |
| **C4: MCP auto-discovery** | Claude Code automatically connects to MCP servers (IDA, x64dbg) | [hyperagent-static](file:///e:/Github/HyperAgent/skill/backup/hyperagent-malware-analyze/v3/hyperagent-static/SKILL.md) L136-137, [hyperagent-dynamic](file:///e:/Github/HyperAgent/skill/backup/hyperagent-malware-analyze/v3/hyperagent-dynamic/SKILL.md) L133 |
| **C5: Context usage monitoring** | Claude Code's implicit `context_usage >= 80%` detection | All 9 SKILL.md files (State/Resume Contract section) |
| **C6: IDA Pro Claude plugin** | `/ida-pro:idapython` — Claude Code plugin, not standard MCP | [hyperagent-static](file:///e:/Github/HyperAgent/skill/backup/hyperagent-malware-analyze/v3/hyperagent-static/SKILL.md) L136, [hyperagent-prepare-env](file:///e:/Github/HyperAgent/skill/backup/hyperagent-malware-analyze/v3/hyperagent-prepare-env/SKILL.md) L78-87 |

### 2.3 Per-Skill Coupling Matrix

| Skill | C1 | C2 | C3 Subagent | C4 MCP | C5 Context | C6 IDA Plugin | Tool Dependencies |
|-------|----|----|-------------|--------|------------|---------------|-------------------|
| `hyperagent-prepare-env` | ✓ | ✓ | ✗ | ✓ x64dbg | ✓ | ✓ `/ida-pro:idapython` | vmrun, curl, IDA |
| `hyperagent-static` (×2) | ✓ | ✓ | **✓ Tasks 2-5** | ✗ direct | ✓ | ✓ IDA Pro MCP tools | IDA Pro (survey_binary, decompile, etc.) |
| `hyperagent-unpack` | ✓ | ✓ | ✗ | ✓ x64dbg | ✓ | ✗ | x64dbg MCP, vmrun, upx |
| `hyperagent-dynamic` | ✓ | ✓ | **✓ Tasks 5-6** | ✓ x64dbg | ✓ | ✗ | x64dbg MCP, vmrun |
| `hyperagent-intel` | ✓ | ✓ | ✗ | ✗ | ✓ | ✗ | Python scripts (fetch_vt, normalize_vt) |
| `hyperagent-deepdive` | ✓ | ✓ | ? | ✗ | ✓ | ✗ | Reads upstream JSON only |
| `hyperagent-report` | ✓ | ✓ | ✗ | ✗ | ✓ | ✗ | Reads upstream JSON only |
| `hyperagent-summary` | ✓ | ✓ | ✗ | ✗ | ✓ | ✗ | Reads upstream JSON only |

### 2.4 What STAYS Unchanged (Vendor-Agnostic)

| Component | Path | Reason |
|-----------|------|--------|
| Pipeline state | [pipeline_state.py](file:///e:/Github/HyperAgent/skill/backup/hyperagent-malware-analyze/v3/_hyperagent-common/scripts/pipeline_state.py) | Pure Python, JSON-based, CLI interface |
| Output validation | [validate_output.py](file:///e:/Github/HyperAgent/skill/backup/hyperagent-malware-analyze/v3/_hyperagent-common/scripts/validate_output.py) | JSON Schema validation |
| Pipeline validation | [validate_pipeline.py](file:///e:/Github/HyperAgent/skill/backup/hyperagent-malware-analyze/v3/_hyperagent-common/scripts/validate_pipeline.py) | Cross-stage consistency checks |
| VT fetch script | [fetch_vt_file_report.py](file:///e:/Github/HyperAgent/skill/backup/hyperagent-malware-analyze/v3/_hyperagent-common/scripts/fetch_vt_file_report.py) | Direct API call, no LLM dependency |
| VT normalizer | [normalize_vt_to_intel.py](file:///e:/Github/HyperAgent/skill/backup/hyperagent-malware-analyze/v3/_hyperagent-common/scripts/normalize_vt_to_intel.py) | Pure data transformation |
| Schema definitions | `schema.json` per skill | JSON Schema contracts |
| WebUI | [webui/](file:///e:/Github/HyperAgent/webui) | Read-only Flask viewer |
| STATE.json contract | Stage table, status semantics, recommend_next_stage | Pure data, no LLM coupling |
| Report directory layout | `reports/<sha256>/XX-stage.json` | Convention only |

---

## 3. New Directory Structure

```
hyperagent/                          # New Python package (v4 SDK edition)
├── __init__.py
├── config.py                        # Central config (API keys, VM, MCP endpoints)
├── cli.py                           # CLI entry point: hyperagent analyze sample.exe
│
├── providers/                       # LLM Provider Abstraction Layer
│   ├── __init__.py                  # Factory: create_provider(name)
│   ├── base.py                      # Abstract base: LLMProvider
│   ├── anthropic_provider.py        # Anthropic Claude SDK
│   └── openai_provider.py           # OpenAI SDK (stub, interface only)
│
├── tools/                           # Tool Integration Layer
│   ├── __init__.py
│   ├── base.py                      # ToolDefinition, ToolResult models
│   ├── registry.py                  # Central registry: tool_name → callable
│   ├── mcp_client.py                # Generic JSON-RPC MCP client
│   ├── x64dbg_tools.py              # x64dbg MCP tool wrappers
│   ├── ida_tools.py                 # IDA Pro MCP tool wrappers (replaces /ida-pro:idapython)
│   ├── vmware_tools.py              # vmrun command wrappers
│   ├── filesystem_tools.py          # File read/write/hash/validate
│   └── analysis_tools.py            # Bounded safe wrappers (upx, vt fetch) replacing shell_tools
│
├── skills/                          # Skill System
│   ├── __init__.py
│   ├── config.py                    # SkillConfig dataclass
│   ├── loader.py                    # Parse SKILL.md → system_prompt + SkillConfig
│   └── registry.py                  # Map stage_id → SkillConfig
│
├── engine/                          # Agentic Execution Engine (Research Core)
│   ├── __init__.py
│   ├── agent_loop.py                # Core tool-calling loop (emits execution traces)
│   ├── subagent.py                  # In-process subagent spawning
│   ├── checkpoint.py                # Token counting + threshold degradation tracking
│   ├── injection_guard.py           # Anti-prompt-injection testing ground
│   └── launcher.py                  # Pipeline orchestrator (replaces claude_spawn.py)
│
├── telemetry/                       # Research Data Collection (NEW)
│   ├── __init__.py
│   ├── logger.py                    # Structured JSON logging for traces/metrics
│   └── metrics.py                   # Token, latency, and tool-use counters
│
├── api/                             # FastAPI Server
│   ├── __init__.py
│   ├── server.py                    # FastAPI app + uvicorn entry
│   ├── models.py                    # Pydantic request/response schemas
│   └── jobs.py                      # Background job manager (asyncio)
│
└── tests/                           # Test suite
    ├── test_providers.py
    ├── test_tools.py
    ├── test_agent_loop.py
    └── test_launcher.py
```

---

## 4. Detailed Module Specifications

### 4.1 Provider Layer — `hyperagent/providers/`

#### `base.py` — Abstract Base Class

```python
@dataclass
class CompletionResult:
    content: str                              # LLM text response
    tool_calls: list[ToolCall] | None         # Requested tool calls
    stop_reason: str                          # "end_turn", "tool_use", "max_tokens"
    input_tokens: int                         # For checkpoint tracking
    output_tokens: int
    total_tokens_so_far: int                  # Cumulative for session

class LLMProvider(ABC):
    @abstractmethod
    def complete(self, messages: list[Message], tools: list[ToolDefinition],
                 system_prompt: str) -> CompletionResult: ...

    @abstractmethod
    def count_tokens(self, messages: list[Message]) -> int: ...

    @abstractmethod
    def max_context_tokens(self) -> int: ...

    def context_usage_ratio(self, messages) -> float:
        return self.count_tokens(messages) / self.max_context_tokens()
```

#### `anthropic_provider.py` — Key Design Decisions

- **Model**: `claude-opus-5` default, configurable. The default lives only in
  `providers/anthropic_provider.DEFAULT_MODEL`; an empty `provider.model` in
  config resolves to it. Context windows are read from the Models API at
  runtime, not hardcoded — model ids and window sizes both change per release.
- **Max tokens**: Use `anthropic.count_tokens()` for accurate tracking
- **Tool format**: Map `ToolDefinition` → Anthropic `tools` param format
- **System prompt**: Pass as `system` parameter in Messages API
- **Prompt caching**: Use `cache_control` on system prompt (SKILL.md content is stable across calls within a stage)
- **Extended thinking**: Enable for deepdive/report stages when model supports it
- **Error handling**: Retry on `overloaded_error`, `rate_limit_error` with exponential backoff

#### `openai_provider.py` — Stub

- Implement `LLMProvider` interface only
- Raise `NotImplementedError` on `complete()`
- Token counting via `tiktoken` for future use

### 4.2 Tool Layer — `hyperagent/tools/`

#### `base.py` — Tool Definition Model

```python
@dataclass
class ToolDefinition:
    name: str                            # e.g. "debug_get_state"
    description: str                     # Human-readable for LLM
    parameters: dict                     # JSON Schema for params
    handler: Callable[[dict], ToolResult]  # Actual execution

@dataclass
class ToolResult:
    content: str                         # Result text for LLM
    is_error: bool = False
    metadata: dict | None = None         # For internal tracking
```

#### `mcp_client.py` — Generic MCP Client

Key behaviors:
- Connect to any MCP server via HTTP POST (JSON-RPC 2.0)
- `initialize()` → `tools/list` → cache tool definitions
- `call_tool(name, arguments)` → parse `result.content[0].text`
- Health check before first call
- Timeout: 30s per call, configurable
- Auto-reconnect on connection failure

#### `x64dbg_tools.py` — MCP Tool → ToolDefinition Mapping

Read tool definitions from [toolcall_references.md](file:///e:/Github/HyperAgent/skill/backup/hyperagent-malware-analyze/v3/hyperagent-dynamic/toolcall_references.md) and map each x64dbg MCP tool to a `ToolDefinition`:
- `debug_init`, `debug_get_state`, `debug_run`, etc. (all 35+ tools)
- Endpoint: `http://192.168.248.169:3000/mcp` (configurable)
- All calls routed through `mcp_client.py`

#### `ida_tools.py` — IDA Pro MCP Replacement

> [!WARNING]
> Currently `hyperagent-static` uses `/ida-pro:idapython` — this is a **Claude Code plugin**, NOT a standard MCP server. Needs confirmation:
> 1. Does IDA Pro expose its own MCP server? (Yes — based on SKILL.md references to `survey_binary`, `decompile`, `callgraph`, `xrefs_to`, `imports`, `find_regex`, `get_bytes`, `analyze_batch`)
> 2. MCP endpoint URL? (Needs user confirmation)
> 3. If IDA Pro runs MCP, use `mcp_client.py` same as x64dbg

Tools to wrap: `survey_binary`, `server_warmup`, `imports`, `find_regex`, `get_bytes`, `analyze_batch`, `callgraph`, `xrefs_to`, `decompile`

#### `vmware_tools.py` — vmrun Command Tools

Wrap each vmrun command as a `ToolDefinition`:

```python
VMWARE_TOOLS = [
    ToolDefinition("vm_revert_snapshot", "Revert VM to clean snapshot", ...),
    ToolDefinition("vm_start", "Start VM", ...),
    ToolDefinition("vm_get_guest_ip", "Wait for guest IP", ...),
    ToolDefinition("vm_copy_to_guest", "Copy file from host to guest", ...),
    ToolDefinition("vm_run_program", "Run program in guest (noWait)", ...),
]
```

- VMX path and credentials stored in config (configurable, supports environment variable overrides for security):
- VMX: `H:\VMware\WinVM\Windows 10 - RunSmt.vmx`
- Snapshot: `VMRunV4`
- Guest user: `h26v` / `123456`
- Guest debugger: `C:\Users\h26v\Downloads\x64dbg\release\x96dbg.exe`

#### `filesystem_tools.py` — File Operations

- `read_file(path)` → text content (enforces a 2MB file size safety limit to prevent OOM/DoS and context window bloating)
- `write_file(path, content)` → success/failure
- `sha256_file(path)` → hash
- `list_directory(path)` → entries
- `file_exists(path)` → bool

#### `analysis_tools.py` — Safe Bounded Execution (Replaces `shell_tools.py`)

> [!CAUTION]
> **Cybersecurity Fix**: Generic `run_command` and `run_python_script` tools have been **REMOVED**. Providing an LLM with arbitrary command execution on the host creates a massive risk for Remote Code Execution (RCE), Server-Side Request Forgery (SSRF), and API key exfiltration if the malware contains prompt injection payloads.

Instead of generic shell access, we expose strictly bounded wrappers:
- `upx_unpack(input_path, output_path)` → Runs only the `upx -d` binary
- `fetch_vt_report(sha256, endpoint, output_path)` → Runs `fetch_vt_file_report.py` securely
- `normalize_vt_report(...)` → Runs `normalize_vt_to_intel.py` securely
- `validate_json_output(schema_path, json_path)` → Runs `validate_output.py` securely

#### `registry.py` — Central Tool Registry

```python
class ToolRegistry:
    def register(self, tool: ToolDefinition): ...
    def get_tools_for_stage(self, stage_id: str) -> list[ToolDefinition]: ...
    def execute(self, tool_name: str, arguments: dict) -> ToolResult: ...

# Stage → required tools mapping
STAGE_TOOLS = {
    "01-prepare-env": ["vm_*", "filesystem_*", "x64dbg_health_check"],
    "02-static-pass1": ["ida_*", "filesystem_*", "analysis_*"],
    "03-unpack":       ["x64dbg_*", "vm_*", "filesystem_*", "analysis_*"],
    "04-static-pass2": ["ida_*", "filesystem_*", "analysis_*"],
    "05-dynamic":      ["x64dbg_*", "vm_*", "filesystem_*", "analysis_*"],
    "06-intel":        ["analysis_*", "filesystem_*"],           # bounded VT fetch scripts
    "07-deepdive":     ["filesystem_*"],                          # Reads JSON only
    "08-report":       ["filesystem_*", "analysis_*"],           # validate_pipeline.py
    "09-summary":      ["filesystem_*"],                          # Reads JSON only
}
```

### 4.3 Skill System — `hyperagent/skills/`

#### `config.py` — SkillConfig

```python
@dataclass
class SkillConfig:
    stage_id: str                   # "05-dynamic"
    skill_name: str                 # "hyperagent-dynamic"
    system_prompt: str              # SKILL.md content (cleaned of Claude Code specifics)
    reads_sample_content: bool      # Injection guard flag
    output_schema_path: Path | None # schema.json path
    output_filename: str            # "05-dynamic.json"
    required_tool_groups: list[str] # ["x64dbg_*", "vm_*", ...]
    supports_subagent: bool         # True for static, dynamic
    subagent_tasks: list[str]       # ["Task 5", "Task 6"] — which tasks to delegate
```

#### `loader.py` — SKILL.md Parser

1. Read SKILL.md → extract YAML frontmatter (`name`, `description`)
2. Extract body as system prompt text
3. **Surgery**: Remove/replace Claude Code-specific sections (see §5)
4. Return `SkillConfig` with structured metadata

### 4.4 Engine — `hyperagent/engine/`

#### `agent_loop.py` — Core Agentic Loop

```python
async def run_stage(
    provider: LLMProvider,
    skill: SkillConfig,
    tools: list[ToolDefinition],
    tool_registry: ToolRegistry,
    context: StageContext,           # report_dir, sample_path, stage_id, etc.
) -> StageResult:

    messages = build_initial_messages(skill, context)
    system_prompt = build_system_prompt(skill, context)

    while True:
        # Check context budget BEFORE calling LLM
        usage = provider.context_usage_ratio(messages)
        if usage >= 0.80:
            await checkpoint_stage(context, messages)
            return StageResult(status="checkpointed")

        result = provider.complete(messages, tools, system_prompt)

        if result.tool_calls:
            for tc in result.tool_calls:
                tool_result = tool_registry.execute(tc.name, tc.arguments)
                messages.append(tool_call_message(tc))
                messages.append(tool_result_message(tool_result))
        else:
            # LLM finished without requesting tools
            break

    return StageResult(status="completed", output=result.content)
```

**Key differences from Claude Code:**
1. WE track token count, not Claude Code runtime
2. WE dispatch tool calls, not Claude Code's internal executor
3. WE manage MCP connections, not Claude Code's auto-discovery
4. WE control subagent spawning, not Claude Code's Agent tool

#### `subagent.py` — In-Process Subagent

```python
async def spawn_subagent(
    provider: LLMProvider,
    parent_context: StageContext,
    task_prompt: str,              # Focused prompt for delegated work
    tools: list[ToolDefinition],   # Subset of parent's tools
    tool_registry: ToolRegistry,
    max_tokens: int | None = None,
) -> SubagentResult:
    """Spawn a child agentic loop with focused context."""
    # Fresh message history (not shared with parent)
    # Returns structured result only (no raw dumps)
    # Parent merges result into its own messages
```

Use cases:
- `hyperagent-static` Tasks 2-5: IDA Pro heavy code reading
- `hyperagent-dynamic` Tasks 5-6: x64dbg API tracing + capability validation

#### `checkpoint.py` — Token Tracking

```python
class ContextTracker:
    def __init__(self, provider: LLMProvider, threshold: float = 0.80):
        self.provider = provider
        self.threshold = threshold
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def update(self, result: CompletionResult):
        self.total_input_tokens += result.input_tokens
        self.total_output_tokens += result.output_tokens

    def should_checkpoint(self, messages: list[Message]) -> bool:
        return self.provider.context_usage_ratio(messages) >= self.threshold
```

#### `injection_guard.py`

Same text as [claude_spawn.py L48-56](file:///e:/Github/HyperAgent/claude_spawn.py#L48-L56), prepended to system prompt for stages where `reads_sample_content=True`.

#### `launcher.py` — Pipeline Orchestrator (replaces `claude_spawn.py`)

```python
async def run_pipeline(input_path: Path, config: HyperAgentConfig) -> int:
    provider = create_provider(config.provider_name, config)
    tool_registry = build_tool_registry(config)

    sample_sha256 = sha256_of(input_path)
    report_dir = input_path.parent / "reports" / sample_sha256
    pipeline_state.ensure_state(report_dir, sample_sha256, str(input_path))

    for stage in STAGES:
        # Check state (same logic as claude_spawn.py L151-283)
        state = pipeline_state.load_state(report_dir)
        entry = state["stages"][stage.stage_id]

        if entry["status"] == "completed":
            # validate artifact exists → skip
            continue

        skill = load_skill(stage)
        tools = tool_registry.get_tools_for_stage(stage.stage_id)

        attempts = 0
        while attempts < MAX_STAGE_ATTEMPTS:
            attempts += 1
            result = await run_stage(provider, skill, tools, tool_registry, context)

            if result.status == "checkpointed":
                continue  # Re-invoke with resumed context
            elif result.status == "completed":
                # Validate output artifact
                break
            else:
                pipeline_state.fail(report_dir, stage.stage_id, result.error)
                return 1

    return 0
```

### 4.5 FastAPI Server — `hyperagent/api/`

#### `server.py`

```python
app = FastAPI(title="HyperAgent", version="4.0.0")

@app.post("/analyze/path")
async def analyze_path(req: AnalyzeRequest) -> AnalyzeResponse:
    job_id = jobs.submit(req.file_path)
    return AnalyzeResponse(job_id=job_id, status="submitted")

@app.get("/jobs/{job_id}")
async def job_status(job_id: str) -> JobStatus:
    return jobs.get_status(job_id)

@app.get("/jobs/{job_id}/result")
async def job_result(job_id: str) -> JobResult:
    return jobs.get_result(job_id)

# Mount existing WebUI
from webui.app import create_app as create_flask_app
app.mount("/ui", WSGIMiddleware(create_flask_app()))
```

#### `jobs.py` — Background Job Manager

```python
class JobManager:
    async def submit(self, file_path: str) -> str:
        job_id = uuid4().hex
        asyncio.create_task(self._run_job(job_id, file_path))
        return job_id

    async def _run_job(self, job_id: str, file_path: str):
        config = load_config()
        result = await run_pipeline(Path(file_path), config)
        self.results[job_id] = result
```

---

## 5. SKILL.md Prompt Surgery Catalog

Each SKILL.md requires **surgical edits** to work with the SDK instead of Claude Code. Below is the exact catalog:

### 5.1 Sections to REMOVE from all 9 SKILL.md files

| Section | Reason | Replaced by |
|---------|--------|-------------|
| `Runtime Path Contract` (bash + powershell blocks) | References `$HOME/.claude/skills` — Claude Code-specific path | Config from `hyperagent.config` |
| `State / Resume Contract` bash/powershell commands | `python "$STATE_HELPER"` CLI calls | Agent loop calls `pipeline_state` Python API directly |
| `context usage >= 80%` instructions | Claude Code implicit detection | `checkpoint.py` handles this automatically |

### 5.2 Sections to MODIFY in specific skills

| Skill | Section | Current | Replace with |
|-------|---------|---------|--------------|
| `hyperagent-static` | Subagent delegation | "Use the Agent tool with `subagent_type: general-purpose`" | "Delegate to in-process subagent via `spawn_subagent()`" |
| `hyperagent-static` | Task 2 Fingerprint | "invoke `/ida-pro:idapython`" | "Use IDA Pro MCP tools via tool registry" |
| `hyperagent-dynamic` | Subagent delegation | "Use the Agent tool with `subagent_type: general-purpose`" | "Delegate to in-process subagent via `spawn_subagent()`" |
| `hyperagent-dynamic` | toolcall_references.md usage | "in this directory" reference | Tool definitions auto-provided by tool registry |
| `hyperagent-prepare-env` | IDA check | "Claude plugin `/ida-pro:idapython`" | "IDA Pro MCP server health check" |
| `hyperagent-prepare-env` | Dynamic readiness | curl + vmrun instructions | Tools auto-available via tool registry |

### 5.3 Sections to KEEP (domain logic)

All **malware analysis workflow** content remains unchanged:
- Role descriptions
- Task specifications (Fingerprint, Execution Graph, etc.)
- Output Contract (JSON schema requirements)
- Strict JSON Rules
- Rules sections
- Pass Selection logic (static)
- Stage Decision Policy (unpack)
- Claim Precedence (report)
- Failure and Fallback Policy (unpack)

---

## 6. Implementation Phases

### Phase 1: Foundation (Provider + Tool Models)
**Files**: `config.py`, `providers/base.py`, `providers/anthropic_provider.py`, `providers/openai_provider.py`, `tools/base.py`
**Verifiable**: Unit test — Anthropic provider can complete a simple prompt, OpenAI stub raises NotImplementedError

### Phase 2: Tool Integration
**Files**: `tools/mcp_client.py`, `tools/x64dbg_tools.py`, `tools/vmware_tools.py`, `tools/filesystem_tools.py`, `tools/analysis_tools.py`, `tools/registry.py`
**Verifiable**: Integration test — MCP client connects to x64dbg, calls `debug_get_state`, returns parsed result
**Dependency**: x64dbg MCP server running in guest VM

> [!IMPORTANT]
> **IDA Pro MCP**: Need to confirm IDA Pro MCP endpoint URL from user. If IDA runs on the host, the endpoint might be `http://localhost:<port>/mcp`. File `tools/ida_tools.py` will use the same `mcp_client.py`.

### Phase 3: Agentic Loop
**Files**: `engine/agent_loop.py`, `engine/checkpoint.py`, `engine/injection_guard.py`
**Verifiable**: Integration test — single-stage run (01-prepare-env) completed via Anthropic SDK, output validates against schema

### Phase 4: Skill System + Subagent
**Files**: `skills/config.py`, `skills/loader.py`, `skills/registry.py`, `engine/subagent.py`
**Verifiable**: Skill loader parses all 9 SKILL.md files into SkillConfig; subagent can complete a focused task

### Phase 5: Pipeline Launcher
**Files**: `engine/launcher.py`, `cli.py`
**Verifiable**: End-to-end test — full 9-stage pipeline on a known sample, output matches Claude Code baseline

### Phase 6: FastAPI Server
**Files**: `api/server.py`, `api/models.py`, `api/jobs.py`
**Verifiable**: Submit job via POST, poll status, retrieve result JSON

---

## 7. Research Challenges & Mitigations (Risk Analysis)

| Research Challenge | Impact | Mitigation / Measurement |
|--------------------|--------|--------------------------|
| **Baseline Regression** | LLM reasoning via SDK may differ from CLI (different system prompts/defaults) | A/B testing: Compare output JSON field-by-field against baseline CLI datasets |
| **Token Cost / Efficiency** | Multi-agent loops consume massive tokens during evaluation | Telemetry logging, prompt caching tracking, and context pruning experiments |
| **Tool Execution Stability** | Flaky MCP/VM connections ruin automated batch experiments | Retry logic, deterministic timeouts, and structured error logging |
| **Context Degradation** | Long context windows suffer from "lost in the middle" | Conservative checkpoint threshold (75%) and measuring accuracy vs context size |
| **Host Command Injection / SSRF** | LLM could execute arbitrary commands if malware contains prompt injections | Strict bounded tools (`analysis_tools.py`) to safely study injection resilience |
| **File Read DoS / OOM** | Large files block execution during bulk sample evaluation | Enforce strict 2MB limits; log truncation events for analysis |

---

## 8. Open Items (require user input before coding)

> [!IMPORTANT]
> **O1: IDA Pro MCP endpoint?**
> `hyperagent-static` uses IDA Pro tools (`survey_binary`, `decompile`, `callgraph`, etc.). In Claude Code, these are accessed via the `/ida-pro:idapython` plugin. In SDK mode, does IDA Pro expose an MCP server on the host? If so, what is the endpoint URL? (e.g., `http://localhost:13337/mcp`)

> [!IMPORTANT]
> **O2: API key management?**
> Where should API keys (Anthropic, OpenAI, VirusTotal) be stored?
> - Environment variables? (`ANTHROPIC_API_KEY`, etc.)
> - Config file? (`~/.hyperagent/config.yaml`)
> - Both? (env overrides config file)

> [!IMPORTANT]
> **O3: Model selection per stage?**
> Should different models be used for different stages? For example:
> - Sonnet for prepare-env, intel, report, summary (lightweight, fast)
> - Opus for static, unpack, dynamic, deepdive (requires deep reasoning)

---

## 9. Verification Plan

### Automated Tests

```bash
# Phase 1: Provider
pytest tests/test_providers.py -v

# Phase 2: Tools
pytest tests/test_tools.py -v  # Requires x64dbg MCP in VM

# Phase 3: Agent loop (single stage)
python -m hyperagent.cli analyze --stage 01-prepare-env sample.exe

# Phase 5: Full pipeline
python -m hyperagent.cli analyze sample.exe
```

### Baseline Comparison

Run the same sample through both the Claude Code pipeline (v3) and SDK pipeline (v4), then compare:
1. All `schema.json` validations pass
2. `STATE.json` final state identical
3. Finding IDs, categories, confidence ranges comparable
4. IOC sets overlapping > 90%
5. Final verdict + risk score within ±10 points

### Manual Verification

- User reviews 08-report.md output quality
- User confirms dynamic stage still runs correctly in VM
- User confirms IDA Pro analysis coverage
