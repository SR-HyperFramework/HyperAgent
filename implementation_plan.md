# HyperAgent v4 — Revised Implementation Plan

Dựa trên phân tích **"Phân tích và Nâng cấp Hệ thống HyperAgent v4.md"** và đối chiếu với codebase hiện tại.

> [!IMPORTANT]
> **Ràng buộc cố định**: Project **không sử dụng Local LLM**. Tất cả mọi đề xuất tích hợp Ollama/vLLM/DeepSeek-Coder trong tài liệu phân tích v4 đều bị **bỏ qua hoàn toàn**. Cloud API (Anthropic primary, OpenAI stub) là lựa chọn duy nhất.
>
> **Thay thế Gap #4** (Confidentiality & Local LLM): Thay vì Local LLM, ta triển khai **Anonymization Module** — tiền xử lý để che dấu dữ liệu nhạy cảm *trước khi* gửi lên Cloud API.

---

## Tổng quan trạng thái hiện tại

### Đã có (hoạt động được)
| Module | File | Tình trạng |
|--------|------|-----------|
| Config | `hyperagent/config.py` | ✅ Hoàn chỉnh, env-only credentials |
| Provider base | `providers/base.py` | ✅ Interface đủ |
| Anthropic provider | `providers/anthropic_provider.py` | ✅ Hoạt động |
| OpenAI stub | `providers/openai_provider.py` | ✅ Stub như thiết kế |
| Tool base | `tools/base.py` | ✅ Complete |
| MCP client | `tools/mcp_client.py` | ✅ Complete |
| VMware tools | `tools/vmware_tools.py` | ✅ Complete — **cần thêm auto-rollback** |
| Filesystem tools | `tools/filesystem_tools.py` | ✅ Complete |
| Agent loop | `engine/agent_loop.py` | ✅ Functional |
| Injection guard | `engine/injection_guard.py` | ✅ Complete |
| Ablation runner | `experiments/ablation_runner.py` | ✅ Complete |
| Report generator | `experiments/report_generator.py` | ✅ Complete |
| Metrics | `telemetry/metrics.py` | ✅ Complete |

### Còn thiếu / cần sửa
| Module | File | Vấn đề |
|--------|------|--------|
| Analysis tools | `tools/analysis_tools.py` | Wrong CLI flags, wrong scripts_dir |
| Tool registry | `tools/registry.py` | Thiếu `get_tools_for_stage`, `build_full_registry` |
| x64dbg / IDA wrappers | `tools/x64dbg_tools.py`, `ida_tools.py` | Chưa nối vào registry |
| Checkpoint | `engine/checkpoint.py` | No-op — không ghi file progress |
| Subagent | `engine/subagent.py` | **Thiếu hoàn toàn** |
| Launcher | `engine/launcher.py` | **Thiếu hoàn toàn** |
| Skill system | `skills/` | **Thiếu hoàn toàn** |
| CLI | `hyperagent/cli.py` | **Thiếu hoàn toàn** |
| Pipeline state | `hyperagent/pipeline_state.py` | **Thiếu hoàn toàn** |
| FastAPI server | `api/server.py`, `models.py`, `jobs.py` | **Thiếu hoàn toàn** |
| **Anonymization module** | `tools/anonymizer.py` | **Thiếu — mới theo Gap #4** |
| **VM auto-rollback** | `tools/vmware_tools.py` | Thiếu trigger sau mỗi dynamic cycle |
| **Rule verification** | `tools/rule_verifier.py` | **Thiếu — mới theo Gap #2** |
| **Call graph metadata** | `tools/ida_tools.py` | Thiếu xrefs_to/callees enrichment |
| **Batch eval pipeline** | `experiments/batch_eval.py` | **Thiếu — mới theo Gap baseline** |
| Tests | `tests/test_agent_loop.py`, `test_launcher.py` | Thiếu |

---

## 5 Khoảng trống cần khắc phục (từ phân tích v4.md)

### Gap #1 — Context cô lập hàm (Caller/Callee)
**Vấn đề**: IDA tools hiện chỉ decompile từng hàm độc lập, mất đi ngữ cảnh caller/callee.  
**Giải pháp**: Khi `ida_decompile` được gọi, tự động enrich prompt với:
- `xrefs_to(func)` — các hàm gọi đến nó
- `callee(func)` — các hàm mà nó gọi đi
- **File**: `tools/ida_tools.py` → thêm `ida_get_context_subgraph`

### Gap #2 — FPR Verification Loop (Lọc dương tính giả)
**Vấn đề**: Không có pipeline xác thực luật JQ/YARA được sinh ra.  
**Giải pháp**: Module `tools/rule_verifier.py`:
- Chạy thử luật JQ trên tập **benign JSON reports** (100 file sạch)
- Luật nào match bất kỳ benign file → reject, trả lỗi về cho LLM để sửa
- FPR target: 0% (giống Trident)
- **File mới**: `tools/rule_verifier.py`

### Gap #3 — VM Auto-Rollback Safety
**Vấn đề**: Sau mỗi dynamic analysis cycle, VM không được revert về snapshot sạch.  
**Giải pháp**: Thêm `vm_safe_revert_after_cycle` — wrapper tự động gọi revert sau khi dynamic stage kết thúc.  
- **File**: `tools/vmware_tools.py` → thêm `vm_auto_revert_hook`
- **File**: `engine/launcher.py` → gọi hook sau mỗi dynamic stage

### Gap #4 — Bảo mật dữ liệu (KHÔNG dùng Local LLM)
**Vấn đề**: Dữ liệu nhạy cảm (IP nội bộ, domain, API key, PII) có thể bị gửi lên Cloud.  
**Giải pháp**: `tools/anonymizer.py` — tiền xử lý dữ liệu trước khi đưa vào prompt:
- Detect + hash/replace: IP nội bộ, domain, path chứa username, API keys, credentials
- Thay bằng token: `[INTERNAL_IP_1]`, `[VICTIM_DOMAIN_A]`, `[CREDENTIAL_TOKEN_1]`
- Áp dụng cho: decompiled code trước khi gửi, báo cáo sandbox, chuỗi hardcoded
- **File mới**: `tools/anonymizer.py`
- Tích hợp vào `engine/injection_guard.py` hoặc `engine/agent_loop.py`

### Gap #5 — Obfuscation / Junk Code Filter
**Vấn đề**: Code bị obfuscate/junk code làm giảm độ chính xác LLM.  
**Giải pháp**: Thêm pre-processing step vào `analysis_tools.py`:
- Strip dead code patterns (NOP sleds, junk sequences)
- Flag obfuscated strings cho agent để trigger self-repair loop
- **File**: `tools/analysis_tools.py` → thêm `preprocess_decompiled_code`

---

## Implementation Phases (Revised)

### Phase 1 — Sửa blockers hiện tại *(ưu tiên cao nhất)*

**Files cần sửa**:
- [`tools/analysis_tools.py`](file:///e:/Github/HyperAgent/hyperagent/tools/analysis_tools.py) — Fix tất cả CLI flags sai, fix `_get_scripts_dir()`
- [`tools/registry.py`](file:///e:/Github/HyperAgent/hyperagent/tools/registry.py) — Thêm `STAGE_TOOLS`, `get_tools_for_stage()`, `build_full_registry()`
- [`tools/x64dbg_tools.py`](file:///e:/Github/HyperAgent/hyperagent/tools/x64dbg_tools.py) — Nối vào registry, lazy connect
- [`tools/ida_tools.py`](file:///e:/Github/HyperAgent/hyperagent/tools/ida_tools.py) — Nối vào registry, thêm `ida_get_context_subgraph`
- [`pyproject.toml`](file:///e:/Github/HyperAgent/pyproject.toml) — Fix build backend → `setuptools.build_meta`
- Tạo `hyperagent/engine/__init__.py`, `hyperagent/telemetry/__init__.py` (nếu còn thiếu)

**Exit criteria**:
```bash
pip install -e .           # Không lỗi
python -c "import hyperagent.engine, hyperagent.telemetry"
pytest hyperagent/tests/test_tools.py -v   # Pass
```

---

### Phase 2 — Anonymization Module *(Gap #4 replacement)*

**Files mới**:

#### [NEW] `hyperagent/tools/anonymizer.py`
```python
class DataAnonymizer:
    """
    Scans decompiled code / sandbox reports for sensitive data patterns
    and replaces them with stable placeholder tokens before sending to Cloud API.
    
    Patterns detected:
    - Private IPv4/IPv6 (RFC 1918 + loopback)
    - Internal FQDNs (configurable domain suffix blocklist)
    - Windows/Linux user paths (/home/<user>/, C:\Users\<user>\)
    - API key patterns (common prefixes: sk-, AKIA, etc.)
    - Hardcoded credentials (password=, passwd=, pwd=)
    
    Token format: [TYPE_INDEX] e.g. [INTERNAL_IP_1], [USER_PATH_2]
    Mapping is stored in-memory per analysis session for reversibility.
    """
    
    def anonymize(self, text: str) -> tuple[str, dict[str, str]]:
        """Returns (anonymized_text, token_map)."""
    
    def restore(self, text: str, token_map: dict[str, str]) -> str:
        """Reverse anonymization for post-analysis reporting."""
```

**Tích hợp**: Vào `engine/injection_guard.py` → gọi `anonymizer.anonymize()` cho stages có `reads_sample_content=True`.

**Exit criteria**:
- Unit test: IP `192.168.1.100` → `[INTERNAL_IP_1]`, path `C:\Users\victim\` → `[USER_PATH_1]`
- Integration: Decompiled output qua anonymizer trước khi vào system prompt

---

### Phase 3 — Engine Completion

**Files mới/sửa**:

#### `hyperagent/pipeline_state.py` [NEW]
Import-clean copy của v3 helper. Public API: `ensure_state`, `load_state`, `checkpoint`, `complete`, `fail`.

#### `engine/checkpoint.py` [MODIFY]
Hiện tại là no-op. Cần:
- Ghi `_state/<stage_id>.progress.md` khi threshold vượt
- Gọi `pipeline_state.checkpoint(report_dir, stage_id)`
- `CheckpointReached` exception phải carry đủ state để resume

#### `engine/subagent.py` [NEW]
```python
async def spawn_subagent(
    provider: LLMProvider,
    parent_context: StageContext,
    task_prompt: str,
    tools: list[ToolDefinition],
    tool_registry: ToolRegistry,
    isolated: bool = True,  # AblationConfig.isolated_subagents
    max_tokens: int | None = None,
) -> SubagentResult:
    """Fresh message history (isolated=True) or shared history (isolated=False for ablation A3)."""
```

#### `engine/launcher.py` [NEW]
Port logic `claude_spawn.py:L151-283`. Thêm:
- Gọi `vm_auto_revert_hook` sau khi `05-dynamic` stage hoàn thành
- Hỗ trợ `AblationConfig` để skip stages, disable cache, disable guard
- `run_pipeline_with_config(sample_path, ablation_config, run_id) -> RunMetrics`
  (signature mà `AblationRunner` đang expect)

#### `skills/config.py`, `skills/loader.py`, `skills/registry.py` [NEW]
Theo thiết kế §4.3 trong implementation_plan.md gốc. Loader phải strip:
- `Runtime Path Contract` sections
- `State / Resume Contract` bash blocks
- `context usage >= 80%` instructions

#### `hyperagent/cli.py` [NEW]
```bash
hyperagent analyze <sample.exe>
hyperagent analyze <sample.exe> --stage 01-prepare-env
hyperagent analyze <sample.exe> --provider anthropic --model claude-opus-4-5
hyperagent batch <samples_dir> --output-dir experiments/results
```

**Exit criteria**:
- Single stage `01-prepare-env` completes via SDK
- Checkpoint: forced low threshold → progress file written, resume works
- Full 9-stage pipeline trên known sample → `pipeline_complete`

---

### Phase 4 — VM Auto-Rollback & Rule Verifier *(Gap #2 và #3)*

#### `tools/vmware_tools.py` [MODIFY]
Thêm `vm_auto_revert_after_dynamic()`:
```python
def vm_auto_revert_after_dynamic(config: VMwareConfig) -> ToolResult:
    """
    Called automatically by launcher after '05-dynamic' stage completes.
    Reverts VM to clean snapshot unconditionally.
    This is a safety hook — NOT exposed to the LLM as a callable tool.
    """
    return _run_vmrun(["-T", "ws", "revertToSnapshot", config.vmx_path, config.snapshot_name])
```

> [!CAUTION]
> `vm_auto_revert_after_dynamic` **không được đăng ký vào ToolRegistry** — nó là internal safety hook, chỉ launcher gọi trực tiếp. Mục đích: ngăn mã độc lây ngược từ guest vào host.

#### `tools/rule_verifier.py` [NEW]
```python
class RuleVerifier:
    """
    Validates JQ/YARA rules generated by agent against a benign corpus.
    Implements the Trident FPR=0 policy.
    """
    
    def __init__(self, benign_reports_dir: Path):
        """benign_reports_dir: chứa ~100 sandbox JSON reports của file lành tính."""
    
    def verify_jq_rule(self, jq_rule: str) -> VerificationResult:
        """
        Chạy rule trên tất cả benign reports.
        Returns:
          - passed=True, fps=[] nếu không có false positive
          - passed=False, fps=[filenames] nếu rule match bất kỳ benign file nào
        """
    
    def generate_repair_prompt(self, rule: str, fps: list[str]) -> str:
        """Tạo prompt yêu cầu LLM sửa rule, kèm thông tin về false positives."""
```

**Tích hợp**: Vào `engine/agent_loop.py` hoặc task-specific subagent — khi LLM sinh ra JQ rule, tự động verify trước khi save.

**Exit criteria**:
- Unit test: rule `.|has("pe")` match trên benign PE JSON → blocked
- Integration: agent retry loop khi rule bị reject

---

### Phase 5 — Batch Evaluation Pipeline *(Gap baseline)*

#### `experiments/batch_eval.py` [NEW]
```python
class BatchEvaluator:
    """
    Multi-sample evaluation pipeline.
    Minimum: 200 samples (100 malware + 100 benign).
    Uses temporal split (samples divided by first-seen date) to detect concept drift.
    
    Outputs:
    - Per-sample: precision, recall, F1, FPR, token_cost
    - Aggregate: macro/micro averages, temporal drift plot data
    """
    
    async def evaluate_corpus(
        self,
        malware_dir: Path,
        benign_dir: Path,
        output_dir: Path,
        ablation_config: AblationConfig | None = None,
    ) -> EvaluationReport: ...
    
    def temporal_split(self, samples: list[SampleMeta], split_date: date) -> tuple[list, list]:
        """Split by first-seen date for temporal generalization testing."""
```

**Exit criteria**:
- Chạy được trên 10 mẫu test (thay vì 200) với `--quick-test` flag
- Xuất CSV/JSONL với đầy đủ metrics

---

### Phase 6 — FastAPI Server

**Files**: `api/server.py`, `api/models.py`, `api/jobs.py` theo thiết kế §4.5.

**Bổ sung mới**:
```python
@app.post("/verify-rule")
async def verify_rule(req: RuleVerifyRequest) -> RuleVerifyResponse:
    """Endpoint cho WebUI để verify JQ rule trước khi save."""

@app.post("/analyze/batch")
async def analyze_batch(req: BatchAnalyzeRequest) -> BatchJobResponse:
    """Submit nhiều samples cùng lúc — dùng cho batch evaluation."""
```

---

### Phase 7 — Tests & Verification

**Files mới**:
- `tests/test_anonymizer.py` — unit tests cho data anonymization
- `tests/test_rule_verifier.py` — unit tests cho FPR verification
- `tests/test_agent_loop.py` — với fixture provider responses
- `tests/test_launcher.py` — pipeline state machine tests
- `tests/test_vm_safety.py` — mock vmrun, verify auto-revert called

---

## Tóm tắt thay đổi so với implementation_plan.md gốc

| Phần | Thay đổi |
|------|---------|
| **Gap #4 (Local LLM)** | ❌ Bỏ hoàn toàn — thay bằng `anonymizer.py` (PII scrubbing trước khi gửi Cloud) |
| **Gap #3 (VM Safety)** | ✅ Thêm `vm_auto_revert_after_dynamic` — internal hook, không expose cho LLM |
| **Gap #2 (FPR)** | ✅ Thêm `rule_verifier.py` — Trident-style FPR=0 verification loop |
| **Gap #1 (Context)** | ✅ Thêm `ida_get_context_subgraph` — enrich prompt với caller/callee |
| **Gap #5 (Obfuscation)** | ✅ Thêm `preprocess_decompiled_code` trong `analysis_tools.py` |
| **Baseline testing** | ✅ Thêm `batch_eval.py` — 200 samples, temporal split |
| **Provider layer** | Giữ nguyên: Anthropic primary, OpenAI stub |
| **Ablation runner** | Giữ nguyên, launcher cần implement `run_pipeline_with_config` |
| **Telemetry** | Giữ nguyên architecture |

---

## Open Items

> [!IMPORTANT]
> **O1 — IDA Pro MCP endpoint?** `config.py` đang dùng `http://localhost:13337/mcp` làm default. Cần xác nhận endpoint thực tế.

> [!IMPORTANT]
> **O2 — Benign corpus cho Rule Verifier?** `rule_verifier.py` cần thư mục chứa ~100 benign sandbox JSON reports. Cần chuẩn bị dataset này trước Phase 4.

> [!IMPORTANT]
> **O3 — Anonymizer domain blocklist?** Cần danh sách domain suffix nội bộ (`.corp`, `.internal`, `.lan`, v.v.) và IP range tổ chức để cấu hình.

> [!NOTE]
> **O4 — Per-stage model selection?** `ProviderConfig.stage_models` đã có nhưng chưa được đọc. Stage 5 (launcher) sẽ wire nó vào. Đề xuất: Sonnet cho prepare-env/intel/summary, Opus cho static/dynamic/deepdive.

---

## Verification Plan

### Automated Tests
```bash
# Phase 1
pytest hyperagent/tests/test_tools.py -v

# Phase 2
pytest hyperagent/tests/test_anonymizer.py -v

# Phase 3
python -m hyperagent.cli analyze --stage 01-prepare-env sample.exe

# Phase 4
pytest hyperagent/tests/test_rule_verifier.py -v
pytest hyperagent/tests/test_vm_safety.py -v

# Phase 5 (quick mode)
python -m experiments.batch_eval --quick-test --malware-dir samples/malware --benign-dir samples/benign

# Full pipeline
python -m hyperagent.cli analyze sample.exe
```

### Baseline Comparison
Chạy cùng sample qua v3 (Claude Code) và v4 (SDK), so sánh:
1. Tất cả `schema.json` validations pass
2. `STATE.json` final state identical
3. IOC set overlap > 90%
4. Final verdict + risk score within ±10 points
5. **Mới**: FPR của JQ rules = 0% trên benign corpus
