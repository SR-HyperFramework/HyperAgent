# HyperAgent Unpack Environment

## Required

- Isolated Windows guest VM with a clean restorable snapshot
- VMware Workstation and `vmrun` available on the analyst host
- x64dbg matching the sample architecture (`x32dbg` for 32-bit, `x64dbg` for 64-bit)
- x64dbg MCP service reachable from the orchestrator
- Python 3 for health checks and artifact hashing
- Safe host workspace for reports and non-executed recovered artifacts

## Recommended host tools

- `upx` for trusted UPX test/decompression
- `7z` or equivalent archive utility
- PE parser/validator such as PE-bear, Detect It Easy, or a Python `pefile`-based validator
- `sha256sum` or Python hashing
- YARA and FLOSS for non-executing post-recovery triage

## Recommended guest/debugger capabilities

The x64dbg MCP deployment should expose:

- debug control: `debug_init`, `debug_run`, `debug_pause`, `debug_restart`, `debug_stop`
- modules/symbols: `module_get_main`, `module_list`, `symbol_resolve`
- breakpoints: `breakpoint_set`, `breakpoint_delete`, `breakpoint_list`
- registers/stack: `register_get_batch`, `stack_get_trace`
- memory: `memory_read`, `memory_get_info`, `memory_enumerate`
- disassembly: `disassembly_at`, `disassembly_range`
- dump: `dump_analyze_module`, `dump_detect_oep`, `dump_get_dumpable_regions`, `dump_memory_region`, `dump_module`

Always enumerate tools with `tools/list`; implementations may differ.

## Suggested workspace

```text
reports/<sha256>/
  02-static-pass1.json
  03-unpack.json
  04-static-pass2.json
  artifacts/
    unpack/
      round-01/
      round-02/
      round-03/
```

## Suggested pipeline placement

```text
prepare-env
-> static pass 1
-> unpack (conditional)
-> static pass 2 on validated artifact
-> dynamic behavior validation
-> deepdive / reconciliation
-> report
```

## Setup verification

1. Revert and boot the clean VM.
2. Confirm x64dbg MCP health:
   ```bash
   python hyperagent-unpack/healthcheck.py
   ```
3. Call MCP `initialize`, then `tools/list`.
4. Confirm the dump and memory tools listed above.
5. Test on a harmless UPX-packed lab binary before using a malware sample.
6. Confirm artifacts can be copied out without being launched.
7. Confirm the VM can be reverted successfully after the test.
