# HyperAgent

HyperAgent là một malware-analysis orchestrator theo mô hình **artifact graph**. Hệ thống nhận mẫu đầu vào, nhận diện loại file, route sang coarse agent phù hợp, mở rộng artifact graph khi phát hiện payload con, chạy specialist analyzers, rồi tổng hợp về một **run-level public response** ổn định.

Phiên bản hiện tại có thêm lớp **task-session observability**:
- caller cũ vẫn có thể đọc `GET /runs/{run_id}` như compatibility snapshot
- operator và dashboard có thể theo dõi từng bước thực thi qua `GET /runs/{run_id}/tasks`
- các bước local và Claude-backed đều được project về cùng một task model

## 1. Mental model hiện tại

Dùng các khái niệm này khi đọc repo:

- **run** — lượt phân tích tổng thể, là compatibility projection public
- **task session** — một đơn vị công việc traceable bên trong run
- **artifact** — file hoặc thư mục được phát hiện trong quá trình phân tích
- **finding** — kết quả chuẩn hóa gắn với artifact
- **dashboard** — giao diện live hiển thị task board 3 cột và timeline chi tiết
- **`/hyperagent-malware-analyze`** — entrypoint Claude skill ổn định, hiện đóng vai trò dispatcher

Luồng end-to-end hiện tại:

```text
sample
  -> run created
  -> identify
  -> route
  -> coarse agent
  -> specialist analyzers
  -> next-stage hunting
  -> report synthesis
  -> risk scoring
  -> compatibility run snapshot + task snapshot
```

## 2. Kiến trúc hiện tại

Kiến trúc hiện tại là **artifact-graph orchestrator** với lớp **task-session observability** được thêm theo hướng compatibility-safe.

### Các model và store chính

- `TaskSession` — đơn vị công việc có `task_id`, `session_id`, `parent_task_id`, `status`, `terminal_state`, `executor_kind`, timestamps
- `RunContext` — context được truyền xuyên pipeline, bao gồm cả run/task identity
- `ArtifactNode` — artifact trong graph, có lineage và tùy chọn `sha256`
- `Finding` — finding chuẩn hóa gắn với artifact
- `AgentResult` — kết quả nội bộ của agent, giữ legacy payload đồng thời mở rộng structured fields
- `ArtifactRegistry` — index artifact theo id, path, hash, parent/child
- `FindingStore` — store findings theo artifact
- `WorkQueue` / `WorkItem` — queue ưu tiên cho next-stage analysis

### Orchestrator và execution model

Entry point orchestration chính nằm ở `core/orchestration.py` trong `ArtifactGraphOrchestrator.analyze()`.

Runtime hiện là hybrid:
- các bước deterministic như identify, route, next-stage hunting vẫn chạy local/in-process
- các bước reasoning-heavy có thể spawn Claude-backed child scope
- cả hai loại work đều xuất hiện trong cùng task projection

Các stage thường thấy trong run:
- `request`
- `identify`
- `route`
- `agent`
- `next_stage_hunter`
- `next_stage`
- `report_synthesizer`
- `risk_scoring`

Các Claude-backed child stages thường thấy:
- `native_agent.claude`
- `script_agent.claude`
- `dotnet_agent.claude`
- `claude_runner`

## 3. Agent và skill model

### Coarse agents

- `agents/native_agent.py` — native binaries
- `agents/dotnet_agent.py` — .NET binaries
- `agents/script_agent.py` — script / PyInstaller / Python bytecode workflows

### Specialist analyzers

- `BehaviorAnalyzerAgent`
- `ObfuscationAnalyzerAgent`
- `ConfigExtractorAgent`
- `IOCExtractorAgent`
- `CapabilityMapperAgent`
- `ReportSynthesizerAgent`
- `RiskScoringAgent`

### Skill runtime

Claude skill tree hiện đã tách thành dispatcher + specialist skills, nhưng vẫn giữ compatibility ở top-level entrypoint:

- `/hyperagent-malware-analyze` — stable dispatcher / compatibility alias
- specialist skills dưới `skill/`, gồm:
  - `hyperagent-triage`
  - `hyperagent-native-prep`
  - `hyperagent-native-analysis`
  - `hyperagent-dotnet-prep`
  - `hyperagent-dotnet-analysis`
  - `hyperagent-script-prep`
  - `hyperagent-script-analysis`
  - `hyperagent-behavior`
  - `hyperagent-obfuscation`
  - `hyperagent-config`
  - `hyperagent-ioc`
  - `hyperagent-capability`
  - `hyperagent-next-stage`
  - `hyperagent-report`
  - `hyperagent-risk`

**Compatibility contract quan trọng vẫn được giữ:** native prep vẫn emit đúng dạng:

```text
/hyperagent-malware-analyze @<ABSOLUTE_PATH>
```

## 4. API, dashboard, và projections

`api.py` hiện giữ state in-memory qua các store:

```python
RUNS: dict[str, dict[str, Any]] = {}
TASK_SESSIONS: dict[str, dict[str, Any]] = {}
RUN_TASK_INDEX: dict[str, list[str]] = {}
```

Điều này có nghĩa là:
- state chỉ sống theo process
- restart API sẽ mất run/task history
- đây chưa phải durable orchestration backend

### Run snapshot vs task snapshot

Public run snapshot vẫn giữ vai trò compatibility layer:

```text
GET /runs/{run_id}
```

Task snapshot dành cho live observability:

```text
GET /runs/{run_id}/tasks
```

Task snapshot điển hình có shape như sau:

```json
{
  "task_id": "...",
  "run_id": "...",
  "session_id": "...",
  "parent_task_id": null,
  "stage_key": "identify | route | agent | next_stage | response | ...",
  "title": "...",
  "status": "pending | processing | completed",
  "terminal_state": "success | failed | skipped | cancelled | null",
  "executor_kind": "local | claude",
  "artifact_id": null,
  "summary": "...",
  "created_at": "...",
  "started_at": null,
  "finished_at": null
}
```

### Dashboard

Dashboard trong `api.py` hiện kết hợp hai lớp quan sát:

1. **task board** với ba cột:
   - Pending
   - Processing
   - Completed
2. **timeline/detail view** để đọc event flow chi tiết

Các terminal outcomes như `failed`, `skipped`, `cancelled` vẫn nằm trong cột **Completed** và được hiển thị bằng badge.

## 5. Public response contract

Public response ở root vẫn giữ envelope ổn định sau:

```json
{
  "run_id": "...",
  "file_path": "...",
  "detected_type": "...",
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

Ý nghĩa compatibility hiện tại:
- `result` vẫn là legacy/coarse-agent payload
- structured fields như `artifacts`, `findings`, `iocs`, `verdict`, `final_report_markdown` được add phía trên
- task/session model là projection bổ sung, không thay thế run envelope cũ

## 6. Repository map

```text
HyperAgent/
├─ agents/
├─ core/
├─ skill/
├─ test/
├─ openwiki/
├─ api.py
├─ main.py
├─ bootstrap.ps1
├─ config.yaml.template
└─ requirements.txt
```

Điểm bắt đầu tốt theo nhu cầu:
- orchestration: `core/orchestration.py`
- models/task semantics: `core/result_models.py`
- task lifecycle/logging: `core/task_runtime.py`, `core/pipeline_logger.py`
- API/dashboard: `api.py`
- native/script/dotnet route behavior: các file trong `agents/`
- compatibility docs sâu hơn: `openwiki/`

## 7. Yêu cầu môi trường

Repository vẫn thiên về **Windows-first workflow**.

### Bắt buộc
- Python 3.10+
- Node.js LTS
- Claude Code CLI
- Detect It Easy CLI (`diec`)

### Tùy route
- **Native**
  - IDA Pro / idalib-related tooling
  - `uv`
- **.NET**
  - `dnspyc.exe` hoặc `dnSpy.Console.exe`
  - tùy chọn `de4dot.exe`
- **Script / Python bytecode**
  - `pyinstxtractor.py`
  - `pycdas`

## 8. Cài đặt nhanh

Cách khuyến nghị:

```powershell
powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1
```

Bootstrap sẽ:
- tạo `.venv`
- cài Python dependencies từ `requirements.txt`
- generate `config.yaml` từ `config.yaml.template`
- cài full Claude skill tree từ `skill/`
- giữ `/hyperagent-malware-analyze` khả dụng như entrypoint ổn định
- cài Claude plugin liên quan tới IDA nếu môi trường hỗ trợ
- chạy verify cơ bản trừ khi dùng `-SkipVerify`

Một số tùy chọn hữu ích:

```powershell
powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1 -Force
powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1 -SkipVerify
```

## 9. Cấu hình

Portable source of truth là `config.yaml.template`; không nên document hoặc commit các giá trị local trong `config.yaml`.

Các key cấu hình chính:

```yaml
tools:
  diec: "diec.exe"
  de4dot: "de4dot.exe"
  dnspy: "dnspyc.exe"
  pyinstxtractor: "pyinstxtractor.py"
  pycdas: "pycdas"

mcp:
  ida_server_command: ["uv", "run", "idalib-mcp"]

llm:
  claude_code_command: ["claude"]
```

## 10. Cách dùng

### CLI

```powershell
.\.venv\Scripts\Activate.ps1
python main.py C:\path\to\sample.exe
```

### API

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn api:app --host 0.0.0.0 --port 8000
```

Phân tích theo path:

```bash
curl -X POST http://127.0.0.1:8000/analyze/path \
  -H "Content-Type: application/json" \
  -d '{"file_path": "C:/path/to/sample.exe"}'
```

Phân tích bằng upload:

```bash
curl -X POST http://127.0.0.1:8000/analyze/upload \
  -F "file=@C:/path/to/sample.exe"
```

Đọc run snapshot:

```bash
curl http://127.0.0.1:8000/runs/<run_id>
```

Đọc task snapshot:

```bash
curl http://127.0.0.1:8000/runs/<run_id>/tasks
```

## 11. Testing và change guidance

Các suite có signal cao nhất hiện tại:

- `test/test_phase0_contract.py` — public API contract
- `test/test_result_models.py` — task/session semantics
- `test/test_orchestrator_next_stage.py` — artifact graph, next-stage, structured outputs
- `test/test_api_dashboard.py` — run/task projection và dashboard shell
- `test/test_claude_code_runner.py` — Claude invocation layer
- `test/test_phase2_prep_agents.py` — prep + compatibility handoff
- `test/test_agent_runner_integration.py` — route-specific invocation behavior

Chạy toàn bộ unittest:

```bash
python -m unittest discover -s test -p "test_*.py"
```

Một vài targeted suites hữu ích:

```bash
python -m unittest discover -s test -p "test_api_dashboard.py"
python -m unittest discover -s test -p "test_result_models.py"
python -m unittest discover -s test -p "test_orchestrator_next_stage.py"
python -m unittest discover -s test -p "test_phase2_prep_agents.py"
python -m unittest discover -s test -p "test_agent_runner_integration.py"
```

## 12. Real validation note

Một run thực tế đã được thử bằng CLI với mẫu:

```text
C:\Users\ADMIN\HyperAgent\RobloxPlayerInstaller.exe
```

Kết quả validation đó xác nhận:
- end-to-end CLI path hoạt động
- sample được detect là `NATIVE`
- `NativeAgent` route hoạt động
- Claude-backed child stages như `native_agent.claude` và `claude_runner` thực sự được emit
- specialist và synthesis stages cũng xuất hiện trong pipeline/task model

Điều này xác nhận task-session architecture đang hoạt động thực tế, không chỉ ở mức test.

## 13. Known caveats hiện tại

Những điểm cần nhớ khi maintain repo:

- API state vẫn chỉ là in-memory state, chưa durable.
- Public contract ưu tiên compatibility hơn là “làm đẹp lại” payload.
- Claude Code là một phần của runtime analysis, không chỉ là dev helper.
- `/hyperagent-malware-analyze` không nên bị rename hoặc remove casually.
- Native prep contract `/hyperagent-malware-analyze @<ABSOLUTE_PATH>` đang được test khóa.

Ngoài ra, real validation gần đây cũng cho thấy một vấn đề semantic còn tồn tại:
- coarse AI report có thể kết luận benign
- nhưng downstream specialists / risk synthesis vẫn có thể over-interpret prose report và inflate verdict
- một benign installer run đã bị đẩy thành `high risk` do capability/IOC extraction đọc quá rộng từ report text

Nói ngắn gọn: runtime path đang khỏe, nhưng specialist extraction và risk synthesis vẫn cần được siết lại để giảm false positives.

## 14. Hướng đọc repo

Nếu mới vào repo, nên đọc theo thứ tự:

1. `openwiki/quickstart.md`
2. `openwiki/architecture.md`
3. `openwiki/agents-and-analysis.md`
4. `openwiki/api-and-operations.md`
5. `openwiki/testing.md`

## 15. Summary cho maintainer

HyperAgent hiện là:
- một **artifact-graph malware-analysis orchestrator**
- có **run-level compatibility projection**
- có **task-session observability** cho live runtime tracing
- có **dispatcher-based Claude skill routing**
- vẫn giữ **compatibility** cho caller cũ và operator workflow hiện tại

Nếu bạn cần:
- **tương thích ngược** → đọc `GET /runs/{run_id}`
- **traceability runtime** → đọc `GET /runs/{run_id}/tasks`
- **operator workflow** → dùng `/hyperagent-malware-analyze`
- **implementation detail** → bắt đầu từ `core/orchestration.py`
