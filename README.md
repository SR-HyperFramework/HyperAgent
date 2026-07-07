# HyperAgent

HyperAgent là bộ điều phối phân tích malware theo hướng **artifact graph**: nhận một mẫu đầu vào, phân loại file, chọn agent phù hợp, tạo artifact con, chạy các specialist agent trên từng artifact, rồi tổng hợp lại thành kết quả có cấu trúc.

README này tổng hợp:
- những phần đã hoàn thành trong đợt refactor hiện tại
- kiến trúc hiện tại của hệ thống
- cách cài đặt và sử dụng bằng CLI / API
- contract output hiện tại để tích hợp hoặc test

## 1. Trạng thái hiện tại

Refactor hiện tại đã hoàn thành ổn định các phần chính sau:

### Đã hoàn thành
- **Phase 0 — contract hóa output và giữ nguyên behavior công khai**
  - Giữ ổn định interface `HyperAgentOrchestrator.analyze()` trong `main.py`
  - Khóa response envelope công khai bằng test contract
- **Phase 1 — data model trung tâm**
  - Có `RunContext`, `ArtifactNode`, `Finding`, `AgentResult`
  - Có `ArtifactRegistry` và `FindingStore`
- **Phase 2 — tách preparation/classification layer**
  - Có `FileClassifierAgent`
  - Các agent coarse hiện tại hoạt động như compatibility wrapper
- **Phase 3 — ArtifactGraphOrchestrator và queue scheduling**
  - Orchestration đã chuyển sang `ArtifactGraphOrchestrator`
  - Có `WorkQueue` và `WorkItem`
  - Next-stage recursion không còn bám kiểu scan ad-hoc trong `main.py`
- **Phase 4 — specialist analysis agents**
  - Có `BehaviorAnalyzerAgent`
  - Có `ObfuscationAnalyzerAgent`
  - Có `ConfigExtractorAgent`
- **Phase 5 — IOC / correlation / synthesis**
  - Có `IOCExtractorAgent`
  - Có `CapabilityMapperAgent`
  - Có `ReportSynthesizerAgent`
  - Có `RiskScoringAgent`
  - Root result đã có `artifacts`, `findings`, `iocs`, `verdict`, `final_report_markdown`
- **Phase 6 — next-stage intelligence (đã triển khai phần lớn các slice compatibility-safe)**
  - Có `NextStageHunterAgent`
  - Dedup theo **canonical path** và **SHA-256**
  - Hợp nhất **provenance** khi nhiều signal cùng trỏ đến một artifact
  - Ưu tiên candidate theo structured signals
  - Queue ưu tiên artifact quan trọng hơn trước
  - Fallback scan bỏ qua thư mục noise và bytecode Python giá trị thấp trong một số trường hợp

### Mục tiêu quan trọng đã giữ được
Toàn bộ các thay đổi trên được làm theo nguyên tắc:
- **giữ nguyên behavior công khai**
- **giữ nguyên `result["result"]` cho compatibility**
- **giữ nguyên shape của `next_stage_results`**
- **giữ các trường summary chỉ ở root**

## 2. Kiến trúc hiện tại

Luồng chính hiện tại:

```text
input file
  -> FileClassifierAgent
  -> routed coarse agent (Native / DotNet / Script)
  -> AgentResult + ArtifactRegistry update
  -> specialist analyzers
       - BehaviorAnalyzerAgent
       - ObfuscationAnalyzerAgent
       - ConfigExtractorAgent
       - IOCExtractorAgent
       - CapabilityMapperAgent
  -> NextStageHunterAgent tìm artifact con đáng phân tích
  -> WorkQueue điều phối phân tích tiếp theo
  -> ReportSynthesizerAgent
  -> RiskScoringAgent
  -> final public response
```

### Thành phần chính
- `main.py`
  - Entry point CLI
  - Tạo `HyperAgentOrchestrator`
- `core/orchestration.py`
  - `ArtifactGraphOrchestrator`
  - Điều phối classify -> agent -> specialist -> next-stage -> synthesis
- `core/result_models.py`
  - Các model trung tâm
- `core/artifact_registry.py`
  - Quản lý artifact graph, parent/child, hash, tra cứu theo path
- `core/finding_store.py`
  - Lưu finding theo artifact
- `core/work_queue.py`
  - Queue có ưu tiên cho next-stage analysis
- `agents/`
  - Chứa coarse agents và specialist agents
- `api.py`
  - FastAPI wrapper cho path/upload workflows

## 3. Response contract hiện tại

Kết quả public ở root hiện giữ ổn định envelope sau:

```json
{
  "run_id": "...",
  "file_path": "...",
  "detected_type": "NATIVE | DOTNET | PYTHON_SCRIPT | ...",
  "die": {},
  "result": {},
  "next_stage_results": [],
  "pipeline_log": [],
  "artifacts": [],
  "findings": [],
  "iocs": [],
  "verdict": null,
  "final_report_markdown": null
}
```

Ý nghĩa ngắn gọn:
- `result`: payload compatibility từ coarse agent hiện tại
- `next_stage_results`: các artifact con đã được phân tích tiếp
- `artifacts`: danh sách artifact đã biết ở root summary
- `findings`: danh sách finding đã chuẩn hóa
- `iocs`: IOC đã normalize
- `verdict`: đánh giá rủi ro cuối
- `final_report_markdown`: báo cáo cuối dạng markdown

## 4. Cấu trúc thư mục đáng chú ý

```text
HyperAgent/
├─ agents/
│  ├─ native_agent.py
│  ├─ dotnet_agent.py
│  ├─ script_agent.py
│  ├─ file_classifier_agent.py
│  ├─ next_stage_hunter_agent.py
│  ├─ behavior_analyzer_agent.py
│  ├─ obfuscation_analyzer_agent.py
│  ├─ config_extractor_agent.py
│  ├─ ioc_extractor_agent.py
│  ├─ capability_mapper_agent.py
│  ├─ report_synthesizer_agent.py
│  └─ risk_scoring_agent.py
├─ core/
│  ├─ orchestration.py
│  ├─ result_models.py
│  ├─ artifact_registry.py
│  ├─ finding_store.py
│  ├─ work_queue.py
│  ├─ pipeline_logger.py
│  └─ die_handler.py
├─ api.py
├─ main.py
├─ config.yaml.template
├─ bootstrap.ps1
└─ test_*.py
```

## 5. Yêu cầu môi trường

Repository hiện đang thiên về **Windows workflow**.

### Bắt buộc
- Python 3.10+
- Node.js LTS
- Claude Code CLI (`claude`)
- `diec` (Detect It Easy CLI)

### Tùy theo loại phân tích
- **Native**
  - IDA Pro
  - `uv`
  - `idalib-mcp`
- **.NET**
  - `dnspyc.exe` hoặc `dnSpy.Console.exe` đổi tên phù hợp
- **Script / Python bytecode**
  - `pyinstxtractor.py`
  - `pycdas`
  - tùy chọn: `de4dot.exe`

## 6. Cài đặt nhanh

### Cách khuyến nghị: dùng bootstrap

```powershell
powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1
```

Bootstrap sẽ:
- tạo `.venv`
- cài dependency Python từ `requirements.txt`
- dò tool ngoài từ `PATH` hoặc biến môi trường override
- tạo `config.yaml` từ `config.yaml.template`
- cài phần liên quan Claude / plugin nếu môi trường hỗ trợ
- chạy bước verify cơ bản

Nếu muốn tạo lại `config.yaml`:

```powershell
powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1 -Force
```

Nếu chỉ muốn setup mà bỏ verify cuối:

```powershell
powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1 -SkipVerify
```

## 7. Cấu hình

Template cấu hình nằm ở `config.yaml.template`.

Các giá trị mặc định hiện có:

```yaml
tools:
  diec: "diec.exe"
  de4dot: "de4dot.exe"
  dnspy: "dnspyc.exe"
  pyinstxtractor: "pyinstxtractor.py"
  pycdas: "pycdas"

mcp:
  ida_server_command: ["uv", "run", "idalib-mcp"]
  ida_startup_timeout_s: 180
  ida_probe_interval_s: 0.5

llm:
  claude_code_command: ["claude"]
```

Nếu tool không có trong `PATH`, có thể set biến môi trường trước khi bootstrap, ví dụ:

```powershell
$env:HYPERAGENT_DIEC_PATH = 'C:\Tools\diec.exe'
$env:HYPERAGENT_DNSPYC_PATH = 'C:\Tools\dnspyc.exe'
$env:HYPERAGENT_DE4DOT_PATH = 'C:\Tools\de4dot.exe'
$env:HYPERAGENT_PYINSTXTRACTOR_PATH = 'C:\Tools\pyinstxtractor.py'
$env:HYPERAGENT_PYCDAS_PATH = 'C:\Tools\pycdas.exe'
$env:HYPERAGENT_CLAUDE_CMD = '["claude"]'
$env:HYPERAGENT_IDA_SERVER_COMMAND = '["uv","run","idalib-mcp"]'
```

## 8. Cách sử dụng

### 8.1. Chạy bằng CLI

Kích hoạt môi trường:

```powershell
.\.venv\Scripts\Activate.ps1
```

Phân tích một file:

```powershell
python main.py C:\path\to\sample.exe
```

Entry point CLI hiện ở `main.py` và sẽ in kết quả phân tích ra stdout.

### 8.2. Chạy bằng API

Khởi động FastAPI:

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn api:app --host 0.0.0.0 --port 8000
```

#### Phân tích theo file path

```bash
curl -X POST http://127.0.0.1:8000/analyze/path \
  -H "Content-Type: application/json" \
  -d '{"file_path": "C:/path/to/sample.exe"}'
```

#### Phân tích bằng upload

```bash
curl -X POST http://127.0.0.1:8000/analyze/upload \
  -F "file=@C:/path/to/sample.exe"
```

Ghi chú:
- `/analyze/path` yêu cầu file đã tồn tại trên máy chạy API
- `/analyze/upload` hỗ trợ lưu tạm hoặc giữ file tùy tham số `keep_file`

## 9. Test và verification

Các test quan trọng đang khóa behavior hiện tại gồm:
- `test_phase0_contract.py`
- `test_result_models.py`
- `test_phase4_specialist_agents.py`
- `test_orchestrator_next_stage.py`
- `test_agent_runner_integration.py`

Chạy nhanh các suite chính:

```powershell
python -m unittest test_phase0_contract.py
python -m unittest test_result_models.py
python -m unittest test_phase4_specialist_agents.py
python -m unittest test_orchestrator_next_stage.py
python -m unittest test_agent_runner_integration.py
```

Nếu muốn chạy toàn bộ unittest trong repo:

```powershell
python -m unittest discover
```

## 10. Những gì đã thay đổi đáng chú ý so với bản cũ

So với kiến trúc cũ kiểu:

```text
1 artifact -> 1 coarse agent -> 1 report text
```

Hệ thống hiện đã chuyển sang:

```text
1 root sample -> artifact graph -> nhiều specialist sub-agent -> structured findings -> final synthesized report
```

Các thay đổi đáng chú ý nhất:
- orchestration đã tập trung hơn và có state model rõ ràng
- findings không còn chỉ nằm trong prose report
- root result đã có summary dùng được cho downstream processing
- next-stage analysis bớt nở artifact vô ích nhờ ưu tiên, dedup và skip policy
- compatibility công khai vẫn được giữ để tránh phá caller hiện tại

## 11. Hướng sử dụng khuyến nghị

Nếu bạn mới làm việc với repo này, nên đi theo thứ tự:
1. chạy `bootstrap.ps1`
2. chuẩn bị `config.yaml`
3. test một file nhỏ bằng `python main.py <file>`
4. kiểm tra output root envelope
5. nếu cần tích hợp service, chạy `uvicorn api:app ...`
6. trước khi sửa orchestration, luôn chạy lại các suite contract và next-stage

## 12. Lưu ý

- `config.yaml` là file local, không nên commit.
- Native / .NET / script analysis phụ thuộc khá nhiều vào tool ngoài; nếu thiếu tool, pipeline có thể không phân tích sâu được.
- Refactor hiện được làm theo hướng **không phá behavior công khai**, nên khi mở rộng logic nội bộ cần giữ ổn định envelope hiện tại.

---

Nếu cần tiếp tục roadmap, bước kế tiếp nên là hoàn thiện nốt Phase 6 hoặc chuyển sang Phase 7 theo cách vẫn giữ compatibility ở public contract.