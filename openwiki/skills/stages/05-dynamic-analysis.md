---
type: reference
title: Dynamic Analysis (Stage 05)
description: Runtime behavior capture via x64dbg debugger integration and VMware guest execution.
tags: [skills, stages, dynamic]
---

# Dynamic Analysis (Stage 05)

## Overview

Dynamic analysis observes and records malware behavior during execution:

- **Debugger**: x64dbg-mcp for breakpoint-based analysis
- **Sandbox**: VMware guest for isolated execution
- **Monitoring**: Process creation, file I/O, network traffic, memory modifications

## Execution Flow

```
Input: Sample (or unpacked artifact from stage 04)
   ↓
[Prepare guest VM] 
   ├─ Clone snapshot to isolated guest
   ├─ Mount analysis tools (debugger, monitoring)
   └─ Verify guest network isolation
   ↓
[Copy sample to guest] via vmrun -copyFileFromHostToGuest
   ↓
[Set breakpoints via x64dbg-mcp]
   ├─ kernel32!CreateRemoteThread
   ├─ kernel32!WriteProcessMemory
   ├─ kernel32!CreateFileA/W
   ├─ kernel32!RegCreateKeyEx/RegSetValueEx
   ├─ ws2_32!connect / ws2_32!send
   └─ ntdll!NtSetInformationFile (UAC bypass)
   ↓
[Execute sample in guest]
   ├─ Spawn via vmrun -runProgramInGuest
   ├─ Monitor via x64dbg
   └─ Timeout: 60 seconds
   ↓
[Collect findings]
   ├─ Breakpoint hits (e.g., process injection attempts)
   ├─ File modifications (logs created, binaries dropped)
   ├─ Registry changes (persistence mechanisms)
   ├─ Network connections (C&C beacons)
   └─ Memory dumps (shellcode analysis)
   ↓
Output: findings, IOCs, memory dumps
```

## MCP Server: x64dbg-mcp

The x64dbg-mcp MCP server provides debugger integration:

### Available Tools

| Tool | Parameters | Purpose |
|------|------------|---------|
| `debug_init` | `executable_path`, `args`, `cwd` | Start debugging executable |
| `debug_continue` | `run_until_breakpoint` | Resume execution |
| `debug_break` | — | Pause execution at next instruction |
| `module_get_main` | — | Get main module entry point |
| `module_list` | — | List loaded modules and base addresses |
| `debug_get_state` | — | Get CPU state (EAX, EBX, etc.) |
| `disassembly_at` | `address`, `num_instructions` | Disassemble at address |
| `disassembly_range` | `start_address`, `end_address` | Disassemble range |
| `memory_read` | `address`, `size` | Read memory contents |
| `memory_read_string` | `address`, `max_length` | Read null-terminated string |
| `memory_set` | `address`, `hex_data` | Patch memory |
| `breakpoint_set` | `address`, `name`, `enabled` | Create breakpoint |
| `breakpoint_delete` | `address` | Remove breakpoint |
| `breakpoint_list` | — | List all breakpoints |
| `breakpoint_hit` | `address` | Callback when breakpoint is hit |
| `stack_get_esp` | — | Get ESP (stack pointer) |
| `stack_get_trace` | — | Get call stack |
| `stack_push` | `value` | Push value to stack |
| `stack_pop` | — | Pop value from stack |

### Example x64dbg Workflow

```python
# Via x64dbg-mcp:

# 1. Start debugger
debug_init(
  executable_path="/path/to/sample.exe",
  args="",
  cwd="/temp"
)

# 2. Set breakpoints
breakpoint_set(address=0x401000, name="CreateRemoteThread")
breakpoint_set(address=0x402000, name="WriteProcessMemory")

# 3. Continue to breakpoint
debug_continue(run_until_breakpoint=True)

# 4. Check CPU state
state = debug_get_state()
print(f"EAX={state.eax}, EBX={state.ebx}")

# 5. Read call stack
stack = stack_get_trace()
print(f"Call stack: {stack}")

# 6. Read memory at breakpoint
memory = memory_read(address=state.eax, size=64)
print(f"Memory content: {memory}")

# 7. Disassemble around breakpoint
disasm = disassembly_range(start_address=state.eip - 32, end_address=state.eip + 32)
print(f"Disassembly:\n{disasm}")
```

## VMware Integration

### vmrun Commands

```bash
# Copy file to guest
vmrun -T ws copy /host/path/sample.exe /guest/path/

# Run program in guest
vmrun -T ws runProgramInGuest "{snapshot_id}" -noWait /path/to/sample.exe

# Read file from guest
vmrun -T ws copyFileFromGuestToHost "{snapshot_id}" /guest/path /host/path

# List running processes
vmrun -T ws listProcessesInGuest "{snapshot_id}"

# Kill process in guest
vmrun -T ws killProcessInGuest "{snapshot_id}" {pid}

# Take snapshot
vmrun -T ws snapshot "{snapshot_id}" "backup"

# Revert to snapshot
vmrun -T ws revertToSnapshot "{snapshot_id}" "clean"
```

### Guest Network Isolation

The guest VM is configured with:
- **Network**: Host-only or Internal network
- **Routing**: All traffic through monitoring agent
- **Logging**: All outbound connections logged before blocking

This prevents:
- Communication with real C&C servers
- Lateral movement to production systems

## Output Schema

```json
{
  "status": "completed",
  "execution_results": {
    "process_creation": [
      {
        "parent_pid": 1234,
        "child_pid": 5678,
        "executable": "svchost.exe",
        "command_line": "C:\\Windows\\System32\\svchost.exe -k netsvcs",
        "timestamp": "2026-01-15T10:36:00Z",
        "severity": "high",
        "finding_id": "find_005"
      }
    ],
    "file_operations": [
      {
        "operation": "write",
        "path": "C:\\Users\\User\\AppData\\Local\\malware.exe",
        "size_bytes": 102400,
        "timestamp": "2026-01-15T10:36:15Z",
        "finding_id": "find_006"
      }
    ],
    "registry_changes": [
      {
        "operation": "set_value",
        "key": "HKLM\\Software\\Microsoft\\Windows\\Run",
        "value_name": "Malware",
        "value_data": "C:\\Users\\User\\AppData\\Local\\malware.exe",
        "timestamp": "2026-01-15T10:36:20Z",
        "finding_id": "find_007"
      }
    ],
    "network_connections": [
      {
        "protocol": "TCP",
        "source_ip": "192.168.1.100",
        "source_port": 54321,
        "dest_ip": "1.2.3.4",
        "dest_port": 8080,
        "data": "GET /beacon?id=abc123 HTTP/1.1",
        "timestamp": "2026-01-15T10:36:25Z",
        "finding_id": "find_008"
      }
    ]
  },
  "breakpoint_hits": [
    {
      "breakpoint": "kernel32!CreateRemoteThread",
      "hit_count": 1,
      "first_hit_time": "2026-01-15T10:36:10Z",
      "finding_id": "find_009"
    }
  ],
  "memory_dumps": [
    {
      "dump_id": "dump_001",
      "address": "0x00400000",
      "size_bytes": 65536,
      "content_hash": "sha256:...",
      "contains_shellcode": true
    }
  ],
  "iocs": [
    {
      "type": "ip",
      "value": "1.2.3.4",
      "confidence": 0.99
    },
    {
      "type": "domain",
      "value": "malware-c2.example.com",
      "confidence": 0.95
    }
  ],
  "findings": [
    {
      "finding_id": "find_005",
      "artifact_id": "art_0000",
      "category": "behavior",
      "severity": "high",
      "title": "Spawns svchost.exe Process",
      "description": "Sample creates svchost.exe process, often used as a host for injected code.",
      "confidence": 0.99,
      "source_stage": "dynamic"
    }
  ],
  "recommend_next_stage": "06-intel"
}
```

## Safety Considerations

### Timeout & Termination

- **Execution timeout**: 60 seconds max
- **Auto-termination**: Sample process and children killed after timeout
- **Guest revert**: Guest reverted to clean snapshot after analysis

### Network Safety

- **Air-gapped**: Guest has no internet access
- **Monitoring**: All network connections logged and monitored
- **Blocking**: Outbound connections are blocked at VM hypervisor level

### File Isolation

- **Sandboxed**: Guest has isolated filesystem
- **Cleanup**: All dropped files removed after revert
- **No persistence**: Changes to guest don't persist after revert

## Configuration

```yaml
stages:
  dynamic:
    timeout_s: 120
    guest_revert_timeout_s: 30
    breakpoints:
      - kernel32!CreateRemoteThread
      - kernel32!WriteProcessMemory
      - kernel32!CreateFileA
      - kernel32!RegCreateKeyEx
      - ws2_32!connect
    vmware:
      snapshot_id: "dynamic-analysis-clean"
      network_mode: "internal"  # No external network access
```

## Related Documentation

- [Stage Dependencies](../../architecture/stage-dependencies.md) — How dynamic flows to deepdive
<!-- openwiki: broken internal link [./06-intel.md] file "./06-intel.md" does not exist. Fix the href or restore the target, then delete this comment. -->
- [Intel Enrichment (Stage 06)](./06-intel.md) — Next stage using IOCs from dynamic
- [Execution Model](../../orchestration/execution-model.md) — MCP server integration

