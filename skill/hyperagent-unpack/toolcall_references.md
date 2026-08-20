# x64dbg MCP Reference

Use the native x64dbg MCP tools surfaced by HyperAgent's tool registry. Do not write Python/HTTP helper scripts to call `/mcp`, and do not manually perform `initialize -> tools/list -> tools/call` when the wrapper tools are already available.

## Preferred Flow

1. verify service readiness with `x64dbg_health_check`
2. use the direct wrapper tool names exposed to the stage (for example `debug_init`, `debug_get_state`, `module_get_main`, `breakpoint_set`, `memory_read`, `dump_module`)
3. if a required wrapper tool is unavailable, record that limitation explicitly instead of inventing a raw HTTP client

## Verified Tool Names

### Debug control
- `debug_init`
- `debug_get_state`
- `debug_run`
- `debug_run_to`
- `debug_step_into`
- `debug_step_over`
- `debug_step_out`
- `debug_restart`
- `debug_stop`
- `debug_pause`

### Modules / symbols / disassembly
- `module_get_main`
- `module_list`
- `module_get`
- `module_get_imports`
- `module_get_exports`
- `symbol_resolve`
- `symbol_from_address`
- `disassembly_at`
- `disassembly_function`
- `disassembly_range`

### Breakpoints / registers / memory / stack
- `breakpoint_set`
- `breakpoint_delete`
- `breakpoint_list`
- `breakpoint_get`
- `breakpoint_set_condition`
- `breakpoint_set_log`
- `register_get`
- `register_get_batch`
- `register_list`
- `memory_read`
- `memory_write`
- `memory_search`
- `memory_get_info`
- `memory_enumerate`
- `stack_get_trace`
- `stack_get_pointers`
- `stack_read_frame`
- `stack_is_on_stack`

### Dump / analysis
- `dump_analyze_module`
- `dump_detect_oep`
- `dump_get_dumpable_regions`
- `dump_memory_region`
- `dump_module`

## Name Mapping

| Doc-style name | Callable tool |
|---|---|
| `debug.get_state` | `debug_get_state` |
| `debug.run` | `debug_run` |
| `debug.run_to` | `debug_run_to` |
| `debug.step_over` | `debug_step_over` |
| `module.get_main` | `module_get_main` |
| `module.list` | `module_list` |
| `module.get_imports` | `module_get_imports` |
| `symbol.resolve` | `symbol_resolve` |
| `symbol.from_address` | `symbol_from_address` |
| `breakpoint.set` | `breakpoint_set` |
| `breakpoint.list` | `breakpoint_list` |
| `register.get_batch` | `register_get_batch` |
| `memory.read` | `memory_read` |
| `memory.get_info` | `memory_get_info` |
| `stack.get_trace` | `stack_get_trace` |
| `dump.analyze_module` | `dump_analyze_module` |
| `dump.detect_oep` | `dump_detect_oep` |

## Minimal Python Example

```python
import json
import urllib.request

URL = "http://192.168.248.169:3000/mcp"


def rpc(payload):
    req = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))

rpc({
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "hyperagent", "version": "1.0"},
    },
})

print(rpc({
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/list",
    "params": {},
}))

print(rpc({
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {"name": "debug_get_state", "arguments": {}},
}))
```

## Parsing Results

`tools/call` often returns structured data inside `result.content[0].text` as a JSON string. Parse that inner string when needed.

Example shape:

```json
{
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\n  \"rip\": \"0x...\",\n  \"state\": \"paused\"\n}"
      }
    ]
  }
}
```

## Usage Notes

- Run healthcheck first.
- If health is OK, use: `initialize` -> `tools/list` -> `tools/call`.
- For runtime init, use:
  - `debug_init`
  - `module_get_main`
  - `debug_get_state`
- Recalculate ASLR-sensitive addresses after every restart or re-init.
- Do not assume heuristic OEP matches live memory; verify with runtime tracing.
