# x64dbg MCP Reference

Use the native x64dbg MCP wrapper tools surfaced by HyperAgent's registry. Do not write Python, batch, or raw HTTP helper scripts to call `/mcp`, and do not manually perform `initialize -> tools/list -> tools/call` when wrapper tools are already available.

## Preferred Flow

1. verify service readiness with `x64dbg_health_check`
2. use the direct wrapper tool names exposed to the stage
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

## Usage Notes

- Run `x64dbg_health_check` first.
- For runtime init, prefer:
  - `debug_init`
  - `module_get_main`
  - `debug_get_state`
- For loader and breakpoint setup, prefer:
  - `symbol_resolve`
  - `breakpoint_set`
  - `breakpoint_list`
- For live-memory and control-flow inspection, prefer:
  - `memory_enumerate`
  - `memory_read`
  - `disassembly_at`
  - `disassembly_range`
  - `stack_get_trace`
- For artifact recovery, prefer:
  - `dump_get_dumpable_regions`
  - `dump_memory_region`
  - `dump_module`
- Recalculate ASLR-sensitive addresses after every restart or re-init.
- Do not assume heuristic OEP matches live memory; verify with runtime tracing.
- If a direct wrapper tool exists, use it instead of inventing an out-of-band script.

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

## Reminder

This reference is for choosing native wrapper tools, not for teaching the agent to implement its own MCP client.