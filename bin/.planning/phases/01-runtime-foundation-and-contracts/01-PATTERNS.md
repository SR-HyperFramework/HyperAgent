# Phase 1: Runtime Foundation and Contracts - Pattern Map

**Mapped:** 2026-05-06  
**Files analyzed:** 9  
**Analogs found:** 9 / 9

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `agents/contracts/runtime_adapter.py` | model | request-response | `agents/unsort_agent.py` | role-match |
| `agents/contracts/error_taxonomy.py` | model | transform | `agents/unsort_agent.py` | role-match |
| `agents/contracts/state_machine.py` | utility | event-driven | `agents/native_agent.py` | flow-match |
| `agents/runtime/analysis_plan_builder.py` | service | transform | `main.py` | flow-match |
| `agents/runtime/tool_adapter_registry.py` | service | request-response | `main.py` | role-match |
| `agents/runtime/result_normalizer.py` | utility | transform | `agents/native_agent.py` | flow-match |
| `agents/native_agent.py` | service | request-response | `agents/native_agent.py` | exact |
| `agents/dotnet_agent.py` | service | request-response | `agents/dotnet_agent.py` | exact |
| `main.py` | route | request-response | `main.py` | exact |

## Pattern Assignments

### `agents/contracts/runtime_adapter.py` (model, request-response)

**Analog:** `agents/unsort_agent.py`

**Minimal contract class shape** (lines 1-8):
```python
from typing import Dict, Any

class UnsortAgent:
    async def analyze(self, file_path: str) -> Dict[str, Any]:
        return {
            "type": "UNSORT",
            "info": "Unsorted analysis not implemented yet."
        }
```

**Pattern to copy**
- Keep adapter contract minimal and typed (`Dict[str, Any]` / typed result objects).
- Use async method signatures for runtime lifecycle (`preflight/start/collect/stop`) just like `analyze`.

---

### `agents/contracts/error_taxonomy.py` (model, transform)

**Analog:** `agents/unsort_agent.py`

**Structured failure payload** (lines 4-8):
```python
    async def analyze(self, file_path: str) -> Dict[str, Any]:
        return {
            "type": "UNSORT",
            "info": "Unsorted analysis not implemented yet."
        }
```

**Pattern to copy**
- Return structured error fields, not free-form exceptions.
- Standardize key names for downstream consumers (`code`, `message`, `remediation`, `details`).

---

### `agents/contracts/state_machine.py` (utility, event-driven)

**Analog:** `agents/native_agent.py`

**Polling transition loop** (lines 80-91):
```python
    async def _wait_for_http_ready(self, host: str, port: int, timeout_s: float) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if await self._probe_http(host, port, "/sse", expect_sse=True, timeout_s=2.0):
                return True
            if await self._probe_http(host, port, "/", expect_sse=False, timeout_s=2.0):
                return True
            await asyncio.sleep(self.ida_probe_interval_s)
        return False
```

**Pattern to copy**
- Encode transitions with explicit deadlines and loop-based probe checks.
- Keep timeout budget and probe interval configurable.

---

### `agents/runtime/analysis_plan_builder.py` (service, transform)

**Analog:** `main.py`

**Deterministic route selection** (lines 25-39):
```python
    async def analyze(self, file_path: str) -> dict:
        die_data, analysis_type = self.die_handler.identify(file_path)

        agent = None
        if analysis_type == AnalysisType.NATIVE:
            agent = NativeAgent(self.config_path)
        elif analysis_type == AnalysisType.DOTNET:
            agent = DotNetAgent()
        elif analysis_type == AnalysisType.PYTHON_SCRIPT:
            agent = ScriptAgent()
        elif analysis_type == AnalysisType.UNKNOWN:
            agent = UnsortAgent()
        else:
            raise ValueError(f"Unsupported analysis type: {analysis_type}")
```

**Pattern to copy**
- Keep deterministic mapping from detected type/mode to plan output.
- Raise explicit errors for unsupported modes.

---

### `agents/runtime/tool_adapter_registry.py` (service, request-response)

**Analog:** `main.py`

**Registry-like import and dispatch** (lines 6-10, 30-37):
```python
from core.die_handler import DIEHandler, AnalysisType
from agents.native_agent import NativeAgent
from agents.dotnet_agent import DotNetAgent
from agents.script_agent import ScriptAgent
from agents.unsort_agent import UnsortAgent

        if analysis_type == AnalysisType.NATIVE:
            agent = NativeAgent(self.config_path)
        elif analysis_type == AnalysisType.DOTNET:
            agent = DotNetAgent()
        elif analysis_type == AnalysisType.PYTHON_SCRIPT:
            agent = ScriptAgent()
        elif analysis_type == AnalysisType.UNKNOWN:
            agent = UnsortAgent()
```

**Pattern to copy**
- Centralized adapter registration + selection in one module.
- Keep constructor usage consistent with existing orchestrator behavior.

---

### `agents/runtime/result_normalizer.py` (utility, transform)

**Analog:** `agents/native_agent.py`

**Post-processing normalization pattern** (lines 207-233):
```python
    @staticmethod
    def filter_goose_report(raw_log: str) -> str:
        start_marker = "**Start of Analysis**"
        end_marker = "**End of Analysis**"
        ...
        content = re.sub(r"───.*?\n", "", content)
        content = re.sub(r"-\d+: Could not interpret tool use parameters.*?\n", "", content)
        content = re.sub(r"\n\s*\n", "\n\n", content).strip()
        return content
```

**Pattern to copy**
- Provide one shared normalization step for all runtime outputs.
- Normalize text/keys before returning final envelope.

---

### `agents/native_agent.py` (service, request-response)

**Analog:** `agents/native_agent.py` (self, exact)

**Imports + config pattern** (lines 1-6, 15-26):
```python
import asyncio
import subprocess
import os
import yaml
from typing import Dict, Any, List
...
    def __init__(self, config_path: str = "config.yaml"):
        self.config = self._load_config(config_path)
        self.ida_mcp_cmd = "uv run idalib-mcp"
        self.goose_cmd = "goose"
        mcp_cfg = (self.config or {}).get("mcp") or {}
        self.ida_startup_timeout_s = float(mcp_cfg.get("ida_startup_timeout_s", 180))
        self.ida_probe_interval_s = float(mcp_cfg.get("ida_probe_interval_s", 0.5))
```

**Core lifecycle pattern** (lines 111-131):
```python
            server_proc = await asyncio.create_subprocess_exec(
                *server_args,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                creationflags=creationflags,
            )
            ready = await self._wait_for_http_ready(host, port, timeout_s=self.ida_startup_timeout_s)
            if not ready:
                ...
                return (
                    f"Error: IDA MCP HTTP not ready on http://{host}:{port} within {self.ida_startup_timeout_s:.0f}s. "
                    f"{server_err}"
                ).strip()
```

**Error handling/cleanup pattern** (lines 178-205):
```python
        except FileNotFoundError as e:
            return f"Missing dependency: {str(e)}"
        except Exception as e:
            return f"Lỗi thực thi Goose: {str(e)}"
        finally:
            if server_proc is not None:
                ...
            print("[INFO] Đã đóng IDA MCP Server.")
```

---

### `agents/dotnet_agent.py` (service, request-response)

**Analog:** `agents/dotnet_agent.py` (self, exact)

**Preflight tool resolution pattern** (lines 23-52):
```python
    def _resolve_executable(self, configured: str | None, fallbacks: list[str]) -> str | None:
        def _candidates() -> list[str]:
            out: list[str] = []
            if configured:
                out.append(configured)
            out.extend(fallbacks)
            return out
        ...
        return None
```

**Core command execution pattern** (lines 185-203):
```python
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                ...
                return False
            return True
        except Exception as e:
            print(f"[-] dnSpy-Ex failed: {e}")
            return False
```

**Structured analyze response** (lines 295-313):
```python
        dnspyc = await self.run_dnspy_decompile(file_path, specific_out_dir)
        if not dnspyc:
            return {
                "error": "Decompilation failed"
            }
        ...
        f_context = {
            "file_name": os.path.basename(file_path),
            "file_hash": file_hash,
            "source_directory": specific_out_dir,
            "ai_analysis_report": clean_rp
        }
```

---

### `main.py` (route, request-response)

**Analog:** `main.py` (self, exact)

**Orchestration and envelope pattern** (lines 25-47):
```python
    async def analyze(self, file_path: str) -> dict:
        die_data, analysis_type = self.die_handler.identify(file_path)
        ...
        analysis_data = await agent.analyze(file_path)
        return {
            "file_path": file_path,
            "detected_type": analysis_type.name,
            "die": die_data,
            "result": analysis_data,
        }
```

**Pattern to copy**
- Keep top-level return envelope stable with deterministic keys.
- Route through shared plan/registry layer without changing public result shape.

## Shared Patterns

### Configuration-Driven Runtime Behavior
**Source:** `config.yaml`, `agents/native_agent.py`, `agents/dotnet_agent.py`  
**Apply to:** `analysis_plan_builder`, both agents, runtime lifecycle modules.
```python
mcp_cfg = (self.config or {}).get("mcp") or {}
self.ida_startup_timeout_s = float(mcp_cfg.get("ida_startup_timeout_s", 180))
self.ida_probe_interval_s = float(mcp_cfg.get("ida_probe_interval_s", 0.5))
```

### Explicit Subprocess Control (No shell strings)
**Source:** `agents/native_agent.py`, `agents/dotnet_agent.py`, `agents/script_agent.py`  
**Apply to:** all runtime adapter `start/collect/stop`.
```python
proc = await asyncio.create_subprocess_exec(
    *cmd,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)
stdout, stderr = await proc.communicate()
```

### Structured Result Envelope
**Source:** `main.py`, `agents/dotnet_agent.py`, `agents/native_agent.py`  
**Apply to:** shared normalizer and taxonomy contract.
```python
return {
    "file_path": file_path,
    "detected_type": analysis_type.name,
    "die": die_data,
    "result": analysis_data,
}
```

### Deterministic Tool Selection
**Source:** `main.py`, `agents/dotnet_agent.py`  
**Apply to:** `analysis_plan_builder`, `tool_adapter_registry`.
```python
if analysis_type == AnalysisType.NATIVE:
    agent = NativeAgent(self.config_path)
elif analysis_type == AnalysisType.DOTNET:
    agent = DotNetAgent()
...
```

## No Analog Found

All currently implied Phase 1 files have at least a role-match or flow-match analog in the current codebase.

## Metadata

**Analog search scope:** `agents/`, project root (`main.py`, `config.yaml`)  
**Files scanned:** 6  
**Pattern extraction date:** 2026-05-06
