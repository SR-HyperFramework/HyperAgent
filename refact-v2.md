# HyperAgent v2 Refactor Plan

## Mục tiêu

Refactor HyperAgent từ mô hình:

```text
1 artifact -> 1 coarse agent -> 1 report text
```

sang mô hình:

```text
1 root sample -> artifact graph -> nhiều specialist sub-agent -> structured findings -> final synthesized report
```

## Nguyên tắc

- Artifact-first orchestration, không phải agent-chat-first.
- Mỗi sub-agent chỉ có một trách nhiệm hẹp.
- Tool execution giữ deterministic.
- LLM dùng cho reasoning, interpretation, synthesis.
- Mọi stage phải trả structured output trước, prose/report sau.
- Không rewrite big-bang; đi theo từng phase có rollback rõ ràng.

---

## Phase 0 — Baseline, Safety, và Contract hóa output

### Mục tiêu
- Giữ hệ hiện tại chạy được trong lúc refactor.
- Đóng khung output contract để các phase sau không trôi thiết kế.
- Xác định ranh giới an toàn cho tool execution.

### Việc cần làm
- Freeze interface hiện tại của `HyperAgentOrchestrator.analyze()` trong `main.py`.
- Chuẩn hóa result envelope tạm thời cho mọi agent hiện tại.
- Ghi lại các stage log đang có qua `PipelineLogger`.
- Xác định policy cho tool execution:
  - agent nào được gọi tool nào
  - agent nào chỉ được đọc context
  - không để reasoning layer có shell quyền rộng
- Rà lại chỗ gọi Claude Code trong `core/claude_code_runner.py` để chuẩn bị siết boundary ở phase sau.

### Deliverables
- Result contract v0 cho toàn pipeline.
- Danh sách tool boundary/allowed actions.
- Danh sách các điểm coupling lớn trong code hiện tại.

### Success criteria
- Chưa đổi behavior chính của hệ.
- Có một contract thống nhất để mọi phase sau bám vào.

---

## Phase 1 — Data model trung tâm: Artifact, Finding, AgentResult

### Mục tiêu
Tạo state model chung để toàn bộ hệ thống nói chuyện bằng object có cấu trúc thay vì text rời rạc.

### Việc cần làm
- Tạo model trung tâm:
  - `RunContext`
  - `ArtifactNode`
  - `Finding`
  - `AgentResult`
- Thêm `ArtifactRegistry` để quản lý artifact theo `id`, `sha256`, `parent_id`, `depth`.
- Thêm `FindingStore` để lưu finding theo artifact.
- Chuyển output của các agent hiện tại sang format mới, tối thiểu ở dạng adapter/wrapper.

### Gợi ý cấu trúc file
```text
core/
  result_models.py
  artifact_registry.py
  finding_store.py
```

### Deliverables
- Model dataclass/Pydantic dùng chung.
- Mọi agent hiện tại đều có thể trả `AgentResult`.

### Success criteria
- Không còn phụ thuộc vào mỗi `ai_analysis_report` để carry toàn bộ state.
- Một artifact có thể có nhiều findings và nhiều artifact con.

---

## Phase 2 — Tách preparation layer khỏi coarse agents

### Mục tiêu
Tách các bước deterministic preprocessing ra khỏi `NativeAgent`, `DotNetAgent`, `ScriptAgent`.

### Việc cần làm
- Tách `.NET` prep thành `DotNetDecompilerAgent`:
  - de4dot
  - dnSpy/dnspyc
  - chọn source files ưu tiên
- Tách Python prep thành `PythonBytecodePrepAgent`:
  - pyinstxtractor
  - pycdas
  - chọn `.pyasm` / entry candidates
- Tách native prep thành `NativeDisassemblyPrepAgent`:
  - mở IDA/bind MCP
  - thu entry/import/string/xref seeds
- Tách logic classify sơ bộ ra khỏi `main.py` thành `FileClassifierAgent`.

### Mapping từ code hiện tại
- `agents/dotnet_agent.py` -> bóc phần de4dot/dnSpy thành agent prep riêng.
- `agents/script_agent.py` -> bóc phần extract/disassemble thành agent prep riêng.
- `agents/native_agent.py` -> bóc phần chuẩn bị context cho IDA/Claude thành native prep.
- `core/die_handler.py` -> dùng lại trong `FileClassifierAgent`.

### Gợi ý cấu trúc file
```text
agents/
  file_classifier_agent.py
  dotnet_decompiler_agent.py
  python_bytecode_prep_agent.py
  native_disassembly_prep_agent.py
```

### Deliverables
- Prep agents hoạt động độc lập.
- Coarse agents cũ chỉ còn vai trò compatibility wrapper nếu cần.

### Success criteria
- Có thể gọi prep stage riêng lẻ trên một artifact mà không phải chạy full pipeline.

---

## Phase 3 — ArtifactGraphOrchestrator và queue-based scheduling

### Mục tiêu
Thay orchestration kiểu route-thẳng bằng queue/artifact graph.

### Việc cần làm
- Tạo `ArtifactGraphOrchestrator`.
- Thêm `WorkQueue` để enqueue/dequeue artifact theo priority/depth.
- Chuyển logic next-stage recursion từ `main.py` sang queue scheduler.
- Gắn `parent-child provenance` cho artifact con.
- Giới hạn `max_depth` ở orchestrator thay vì rải trong flow.

### Gợi ý cấu trúc file
```text
core/
  orchestration.py
  work_queue.py
  artifact_graph.py
```

### Deliverables
- Root sample được enqueue như root artifact.
- Mỗi artifact đi qua classify -> prep -> analysis/extraction -> next-stage hunting.

### Success criteria
- Không còn recursion ad-hoc theo extension trong `main.py`.
- Toàn bộ artifact tree được track bằng graph/state rõ ràng.

---

## Phase 4 — Specialist analysis agents

### Mục tiêu
Tách layer reasoning thành các sub-agent vai trò hẹp.

### Việc cần làm
- Tạo `BehaviorAnalyzerAgent`:
  - dựng execution flow
  - xác định malicious capabilities
- Tạo `ObfuscationAnalyzerAgent`:
  - detect packer/loader/string encryption/reflection
- Tạo `ConfigExtractorAgent`:
  - bóc config/blob/resource nếu có
- Chuẩn hóa evidence references thay vì chỉ viết prose.

### Gợi ý cấu trúc file
```text
agents/
  behavior_analyzer_agent.py
  obfuscation_analyzer_agent.py
  config_extractor_agent.py
```

### Deliverables
- Mỗi artifact có thể có nhiều analysis results độc lập.
- Findings được attach theo category.

### Success criteria
- Không còn một agent ôm cả prep + analyze + summarize.
- Dễ chạy song song nhiều analyst trên cùng artifact snapshot.

---

## Phase 5 — IOC, correlation, và final synthesis

### Mục tiêu
Biến kết quả phân tích thành output có thể dùng thật, không chỉ là text report.

### Việc cần làm
- Tạo `IOCExtractorAgent` để normalize IOC:
  - domain, IP, URL
  - mutex, registry key
  - file path, task/service
  - dropped payload path
- Tạo `CapabilityMapperAgent` để map findings sang taxonomy/ATT&CK nếu cần.
- Tạo `ReportSynthesizerAgent` để hợp nhất artifact chain thành final report.
- Tạo `RiskScoringAgent` hoặc verdict layer nhẹ.

### Gợi ý cấu trúc file
```text
agents/
  ioc_extractor_agent.py
  capability_mapper_agent.py
  report_synthesizer_agent.py
  risk_scoring_agent.py
```

### Deliverables
- Final result cấp run có:
  - `artifacts`
  - `findings`
  - `iocs`
  - `verdict`
  - `final_report_markdown`

### Success criteria
- Final report được synthesize từ structured findings, không phải nối text thô.

---

## Phase 6 — Next-stage intelligence và dedup

### Mục tiêu
Làm cho next-stage analysis thông minh hơn logic scan extension hiện tại.

### Việc cần làm
- Tạo `NextStageHunterAgent`.
- Dùng signals từ prep/analyzer/config để phát hiện artifact con đáng theo.
- Dedup bằng:
  - hash
  - canonical path
  - provenance
- Rank artifact nào đáng phân tích trước.
- Thêm policy skip cho artifact noise/low-value.

### Deliverables
- `new_artifacts` được sinh ra từ evidence thực, không chỉ từ extension.
- Queue có prioritization.

### Success criteria
- Giảm false-positive artifact expansion.
- Cải thiện chất lượng stage-2/stage-3 analysis.

---

## Phase 7 — Tool adapters và security boundary cứng

### Mục tiêu
Tách agent khỏi shell/tool raw để giảm coupling và rủi ro.

### Việc cần làm
- Tạo adapter cho từng tool:
  - `DIEAdapter`
  - `De4dotAdapter`
  - `DnSpyAdapter`
  - `PyInstxtractorAdapter`
  - `PycdasAdapter`
  - `IDAAdapter`
  - `ClaudeCodeAdapter`
- Chuẩn hóa interface async cho adapter.
- Mọi agent chỉ gọi adapter thay vì shell trực tiếp.
- Bổ sung logging/timeout/error handling ở adapter layer.

### Gợi ý cấu trúc file
```text
core/tool_adapters/
  die_adapter.py
  de4dot_adapter.py
  dnspy_adapter.py
  pyinstxtractor_adapter.py
  pycdas_adapter.py
  ida_adapter.py
  claude_code_adapter.py
```

### Deliverables
- Tool layer thay được từng adapter mà không đụng orchestration.
- Security boundary rõ giữa reasoning và execution.

### Success criteria
- Agent code mỏng hơn.
- Tool invocation thống nhất, dễ test, dễ audit.

---

## Phase 8 — Optional multi-agent coordination với CrewAI

### Mục tiêu
Chỉ thêm CrewAI khi các lớp state/model/boundary đã ổn định.

### Việc cần làm
- Dùng CrewAI ở analysis/synthesis layer, không dùng để sở hữu queue trung tâm.
- Có thể tạo:
  - `DotNetAnalysisCrew`
  - `PythonAnalysisCrew`
  - `NativeAnalysisCrew`
  - `FinalSynthesisCrew`
- Orchestrator trung tâm vẫn là code deterministic của HyperAgent.

### Deliverables
- CrewAI chỉ điều phối specialist reasoning trong một stage.
- Không để CrewAI nắm full control tool execution.

### Success criteria
- Tăng chất lượng reasoning/synthesis mà không phá determinism của pipeline.

---

## Thứ tự triển khai khuyến nghị

### Nếu muốn đi nhanh nhưng không tự đốt repo
1. Phase 0
2. Phase 1
3. Phase 2
4. Phase 3
5. Phase 5
6. Phase 4
7. Phase 6
8. Phase 7
9. Phase 8

### Nếu muốn ra giá trị nhanh nhất
Ưu tiên trước:
- Phase 1
- Phase 2
- Phase 5

Vì 3 phase này cho mày:
- output schema rõ
- prep layer tách bạch
- final report + IOC usable hơn ngay

---

## Minimal v2 milestone

Nếu muốn chốt một milestone đầu tiên đủ tốt, scope nên là:

- `FileClassifierAgent`
- `DotNetDecompilerAgent`
- `PythonBytecodePrepAgent`
- `NativeDisassemblyPrepAgent`
- `BehaviorAnalyzerAgent`
- `IOCExtractorAgent`
- `NextStageHunterAgent`
- `ReportSynthesizerAgent`
- `ArtifactGraphOrchestrator`
- `ArtifactNode / Finding / AgentResult`

Đây là mức vừa đủ để HyperAgent chuyển sang v2 direction mà chưa overengineer.

---

## Chốt

Refactor v2 nên đi theo hướng:

```text
artifact graph + specialist sub-agents + structured findings + deterministic orchestration
```

Không nên đi theo hướng:

```text
agent swarm tự do + LLM giữ full control flow
```
