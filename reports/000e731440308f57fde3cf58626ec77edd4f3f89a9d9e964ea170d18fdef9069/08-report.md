# Malware Analysis Report

## 1. Sample Identification

| Field | Value |
|---|---|
| File name | 000e731440308f57fde3cf58626ec77edd4f3f89a9d9e964ea170d18fdef9069 |
| Absolute path | H:/Dataset/files/malware/000e731440308f57fde3cf58626ec77edd4f3f89a9d9e964ea170d18fdef9069 |
| SHA256 | `000e731440308f57fde3cf58626ec77edd4f3f89a9d9e964ea170d18fdef9069` |
| Architecture | PE32 GUI Intel 80386, for MS Windows |
| Image base / entry | 0x400000 / 0x4018A0 |
| Sections | 4 (standard PE32: .text, .rdata, .data, .rsrc) |
| Packing / protection | Multi-layer: XOR layer → self-relocating PE loader shellcode → PECompact2-packed PE |

## 2. Executive Summary

### Verdict

**Malicious** — confident classification based on a validated multi-layer packing architecture, offline-recovered loader shellcode performing in-place process hollowing, a delta-encoded embedded PECompact2-packed second stage, and public sandbox corroboration (60/74 VT detection).

### Confidence

**0.85** — The loader architecture is fully resolved with offline replication; the malicious nature of the packing and loader logic is certain. The terminal payload capability (behind the PECompact2 layer) and most runtime IOCs remain unconfirmed locally because the sample never reached its entry point in the analysis environment.

### Plain-language assessment

This sample is a heavily protected, multi-layer malware. It does not run normally in this analysis environment because it depends on a Windows Control Panel applet (DESK.cpl) that is missing from the analysis VM. The outer layer is a simple XOR decryption stub that reveals a small piece of shellcode. That shellcode is a sophisticated custom loader: it reads the original file, extracts and decodes a hidden second program embedded inside it, and overwrites the parent process's memory to run that hidden program in place. The hidden program is itself packed with a commercial packer (PECompact2), so its actual behavior is doubly obscured. Public sandbox reports describe it phoning home to a C2 server, writing to the registry for persistence, and dropping files, but this was not locally reproduced.

### Key findings
- **Multi-layer packing confirmed**: Layer 1 (XOR decryptor), Layer 2 (self-relocating PE loader shellcode), Layer 3 (PECompact2-packed PE).
- **Key reuse across layers**: The XOR key `0x9A246A73` is used in both the parent stub and the recovered shellcode's embedded PE decoder.
- **In-place process hollowing**: The recovered shellcode reads its own module file, delta-decodes an embedded PE, and rewrites the parent PEB/LDR entry — no `CreateProcessW`/`WriteProcessMemory`/`NtUnmapViewOfSection` (self-hollowing, not RunPE).
- **Loader gate blocks dynamic analysis**: The process terminates at ntdll loader init with `STATUS_ENTRYPOINT_NOT_FOUND` before the module entry point executes, due to unresolved `DESK.cpl!DisplaySaveSettings` and possibly `DispatchMessageA` IAT slots.
- **Public sandbox C2**: External sandboxes report HTTP callback to `112.121.178.189` and `RunOnce` persistence — not locally confirmed.
- **No free-running execution past the loader gate**: All runtime evidence is limited to the loader phase; the terminal payload behavior was not observed.

## 3. Analysis Scope and Environment

| Field | Value |
|---|---|
| Work directory | `reports/000e731440308f57fde3cf58626ec77edd4f3f89a9d9e964ea170d18fdef9069/` |
| Static readiness | IDA Pro (idalib MCP), capstone, Python analysis scripts |
| Dynamic readiness | VMware guest (Windows 10), x64dbg MCP debugger, vmrun orchestration |
| Isolation model | Host orchestrator + isolated guest execution (sample executed only in guest VM) |
| Analysis limitations | Process terminated during loader init before module entry; no post-entry dynamic analysis possible. The DESK.cpl module (Control Panel applet) is absent from the analysis VM. ntdll code pages are `PAGE_EXECUTE_READ` and protection-change scripts silently no-op. |

## 4. Packing and Artifact Recovery

- **Packing decision**: Required — multi-layer packing confirmed with high confidence.
- **Recovery status**: Layer 1 (XOR shellcode) and Layer 2 (self-relocating loader shellcode + delta-encoded second-stage PE) recovered offline. Layer 3 (PECompact2) identified but not unpacked.
- **Candidate handoff/OEP**: Shellcode entry offset 0 (priming byte `0x50`, `push eax`). The PECompact2 second-stage entry RVA is `0xA4D5`.
- **Recovered artifacts**:
  - `decrypted_shellcode_1717.raw` — 1717-byte x86 shellcode, SHA256 `537c40bc...`
  - `decoded_second_stage_pe.bin` — Delta-decoded PECompact2-packed PE, SHA256 `8419a4bf...`

### Round 1: XOR decryptor (sub_401DF8)

The parent stub at entry `0x4018A0` walks a 50-deep linear wrapper call chain (pure obfuscation) to reach the real decryptor at `0x401DF8`. The decryptor materializes 1717 bytes of shellcode from ciphertext at `.text` VA `0x402A47`:

- **Transform**: `out[j] = (key_j XOR src[j]) - 1` with alternating key
- **Key**: `key_0 = 0x9A246A73`, `key_{j+1} = -key_j (mod 2^32)`
- **Priming byte**: `0x50` written to `dest+0`; subsequent writes at `dest+1+4j`
- **Destination**: Runtime-dependent (`[LoadLibraryW_return + 0x11C]`), content-independent

The offline Python replication of this transform produced a coherent 1717-byte blob validated as position-independent x86 shellcode with the same SHA256 every time.

### Round 2: Delta-decoded embedded PE

The recovered shellcode is a self-relocating loader that reads its own module file, seeks to file offset `0x50BA`, reads `0x4D200` bytes, and delta-decodes them using the same key `0x9A246A73` (derived from config slot `0x70 XOR 0x7845EA91`). Offline replication of this delta-decode produced a valid PE32 with `MZ`/`PE` signatures, 3 sections (`.text`/`.rsrc`/`.reloc`), and a `requireAdministrator` manifest.

The decoded PE is itself **PECompact2-packed** (markers `PEC2TO` at offset 0x218, `PECompact2` string at 0x98ED; `.text` entropy 7.954; raw size < virtual size). VT corroboration independently confirms PECompact 2.xx → BitSum Technologies (34/46 malicious). Terminal capability is indeterminate without a further unpack round.

## 5. Static Analysis

### Original sample

- **Obfuscated dynamic module loading**: The entry point reconstructs the WCHAR name `devenum.dll` byte-by-byte (`devenum*dll` → `devenum.dll` via byte `0x2A` → `0x2E` mutation) and calls `LoadLibraryW` to obtain a scratch base.
- **PE32 magic gate**: After `LoadLibraryW`, the stub validates the loaded module's `OptionalHeader.Magic` is `0x10B` (PE32); failure enters an infinite loop (`0x4018E6`). This is an anti-tamper mechanism but was never exercised at runtime (termination occurred earlier).
- **50-deep wrapper call chain**: A linear daisy chain of ~50 small functions from `0x401090` terminating at the real decryptor `sub_401DF8`. Each wrapper contains decoy API calls (NULL/0 args) and self-loop obfuscation. Confirmed by live disassembly in the unpack stage.
- **Import surface is largely decoy**: 42 IAT entries across KERNEL32 (20), USER32 (13), CRYPTNET (5), DESK (1). No `VirtualAlloc`, `CreateRemoteThread`, `Reg*`, `URL*`, network, or shell-execution APIs are imported. Real capability resides in the decrypted shellcode.
- **Oversized writable `.rdata`**: `.rdata` spans `0x4040A8–0x46B000` (~0x66f58 bytes, writable) but raw size is only 0x600; the remainder is zero-filled at rest. Confirmed as a decoy/reserved region, not a payload carrier.

### Recovered artifact (shellcode)

The 1717-byte shellcode is a **self-relocating two-phase PE loader / in-place process hollowing** routine:

- **Phase A (offset 0x0–0xAE)**: NOP-sled entry, `call+6` get-EIP, resolves 18 APIs into a hash-based config table at base 0x640 (including `LoadLibraryA`, `GetProcAddress`, `VirtualAlloc`, `VirtualProtect`, `CreateFileA`, `ReadFile`, `SetFilePointer`, `CreateToolhelp32Snapshot`, `Module32First/Next`, `HeapAlloc`/`HeapFree`), allocates an RWX buffer via `VirtualAlloc(NULL, 0x6A4, 0x1000, 0x40)`, and self-relocates.
- **Phase B (offset 0xAF+)**: Reads the parent module file via `GetModuleFileNameA` + `CreateFileA`, seeks to offset `0x50BA`, reads `0x4D200` bytes, delta-decodes the embedded PE, maps it in memory, and rewrites the parent's PEB/LDR entry (`DllBase`, `EntryPoint`, `PEB.ImageBaseAddress`). This is in-place hollowing, not RunPE — no `CreateProcessW`/`WriteProcessMemory`/`NtUnmapViewOfSection`.
- **msvcrt!fwprintf detour hook**: The shellcode builds a `push <addr>; ret` trampoline on `msvcrt!fwprintf`, gated by config slot `0x4C`. The hook's enable state and target are unconfirmed (static value at slot 0x4C is `0x6DD89C49`, non-zero, but semantics unknown).
- **No anti-analysis in shellcode**: No `rdtsc`, `GetTickCount`, `IsDebuggerPresent`, `int 0x2D`, or VM-detection instructions present in the 705-instruction disassembly.

## 6. Dynamic Analysis

### Observed behavior

- **Loader-phase termination**: The process terminates during ntdll loader initialization via `NtTerminateProcess(0xFFFFFFFF, STATUS_ENTRYPOINT_NOT_FOUND, 0xC0000139)` before the module entry point executes.
- **Two unresolved IAT slots at abort**:
  - `0x404088` (DispatchMessageA slot): NULL
  - `0x4040A4` (DESK.cpl!DisplaySaveSettings slot): Unpatched import-descriptor field `0x446A`
  - Cryptnet slots (`0x40408C–0x40409C`): Resolved to real `cryptnet.dll` addresses (contradicts the earlier "fabricated exports" hypothesis)
- **Bypass attempts failed**: Three approaches (NtTerminateProcess stub redirect, import-descriptor zeroing, IAT patching) all executed too late relative to the loader's abort decision. ntdll code pages are `PAGE_EXECUTE_READ` and protection-change scripts silently no-op.

### Not observed during the run

- Module entry point `0x4018A0` never reached across all debugger runs.
- No post-entry execution of the decryptor, shellcode, or PECompact2 stage.
- No network activity, filesystem changes, registry modifications, or process injection.
- No persistence mechanism observed.
- The `msvcrt!fwprintf` hook was never installed or triggered (shellcode never executed).

### Runtime limitations

- The sample never reached its entry point; all runtime conclusions are limited to the loader phase.
- The DESK.cpl module (Control Panel applet) is absent from the analysis VM. The `DisplaySaveSettings` export requires this module, which is not part of a standard Windows 10 installation.
- ntdll code pages are `PAGE_EXECUTE_READ` and protection-change scripts silently no-op, preventing direct in-place patching of ntdll.
- The DispatchMessageA NULL slot may be an artifact of x64dbg import-name reconstruction; the raw file's OFT entry has not been verified.

## 7. Deepdive Reconciliation

### Confirmed findings

- **Obfuscated dynamic module loading** (rev-fin-load-cmp, conf 0.9): The `devenum.dll` byte-reconstruction and `LoadLibraryW` scratch context mechanism is confirmed.
- **PE32 magic gate** (rev-fin-pe-magic-gate, conf 0.85): The gate exists in the code but was never exercised at runtime.
- **50-deep wrapper call chain** (rev-fin-callchain-obfuscation, conf 0.9): Pure obfuscation terminating at the real decryptor.
- **XOR decryptor reproduced** (rev-fin-decryptor, rev-fin-decryptor-reproduced, conf 0.95): The transform is fully characterized and replicated offline; the recovered shellcode is validated.
- **Shellcode is a self-relocating PE loader** (rev-fin-shellcode-self-loader, conf 0.9): The 1717-byte blob is a two-phase loader performing in-place process hollowing.
- **18-slot API table** (rev-fin-api-slot-table, conf 0.95): All 18 hashes verified against Windows export names.
- **Key reuse** (rev-fin-key-reuse, conf 0.95): Key `0x9A246A73` reused across layers 1 and 2.
- **Embedded second-stage PE** (rev-fin-embedded-second-stage-pe, conf 0.95): Delta-decoded PE at file offset `0x50BA` validated offline.
- **PECompact2-packed second stage** (rev-fin-second-stage-packed, conf 0.95): VT corroboration confirms PECompact 2.xx → BitSum Technologies.
- **Loader gate termination** (rev-fin-loader-gate-termination, conf 0.95): `STATUS_ENTRYPOINT_NOT_FOUND` from loader fail-fast path.
- **Unresolved IAT slots** (rev-fin-unresolved-iat-slots, conf 0.85): Two slots unresolved at abort.
- **Cryptnet imports are real** (rev-fin-cryptnet-imports-real, conf 0.85): Live IAT reads confirm addresses within `cryptnet.dll` range.
- **Entry never reached** (rev-fin-entry-not-reached, conf 1.0): Definitive observation.
- **Payload handoff** (rev-fin-payload-handoff, conf 0.85): Decrypt-and-ret through wrapper chain into shellcode entry offset 0.
- **Shellcode entry offset 0** (rev-fin-entry-alignment, conf 0.85): Priming byte `0x50` confirmed.
- **No anti-analysis in shellcode** (rev-fin-no-antianalysis-in-blob, conf 0.85): Clean instruction scan.
- **Oversized `.rdata` is decoy** (rev-fin-rdata-decoy, conf 0.8): Real embedded payload at file offset `0x50BA`, not in `.rdata`.

### Findings requiring caveats

- **Decryptor destination unknown** (rev-fin-decryptor-dest-unknown, conf 0.65): Runtime-dependent (`[LoadLibraryW_return + 0x11C]`), but content-independent — the shellcode was recovered without it.
- **Decoy imports refinement** (rev-fin-decoy-imports, conf 0.75): The core claim (no network/injection/registry APIs directly imported) is correct, but cryptnet imports are real, not fabricated.
- **msvcrt!fwprintf hook** (rev-fin-fwprintf-hook, conf 0.7): Hook-building code present but enable state and target unconfirmed.
- **Bypass attempts** (rev-fin-bypass-readonly-gate, conf 0.9): All attempted too late relative to loader commit; loader-level hook not pursued.

### Rejected or downgraded findings

- **"Fabricated cryptnet exports"** (03-unpack): Rejected — live IAT reads show cryptnet slots resolve to real `cryptnet.dll` addresses.
- **"Anti-debug/anti-VM early exit"** (03-unpack): Refined — the termination is an environment-gated import dependency (`DESK.cpl!DisplaySaveSettings` missing), not an intentional anti-analysis check.
- **"Prohibited claims"** per final_claim_policy: The sample is NOT confirmed as "fake AV" / "fkealrt" family; no network activity/exfiltration/C2, persistence, injection, credential theft, or ransomware behavior was locally observed. No family attribution is confirmed.

### Public-source corroboration or conflict reflected in Deepdive

- **VT file_info**: 60/74 malicious detection for the original sample; tags `[peexe, spreader, corrupt]`; suggested labels `trojan.fkealrt/obfuscator`.
- **VT artifact corroboration**: The recovered delta-decoded second-stage PE matches VT at 34/46 malicious with packer `PECompact 2.xx → BitSum Technologies`, corroborating the local PECompact2 identification.
- **VT behaviour_summary (external only)**: Describes C2 HTTP callback to `112.121.178.189` (`/api/urls/` and `/api/stats/install/`), `RunOnce` persistence, file writes under `All Users\Application Data`, and child process spawn. This is **external-only context** — the local dynamic run terminated at the loader gate and reproduced none of this behavior.
- **Recovered shellcode hash** (`537c40bc...`): No VT record (404 NotFoundError); no public corroboration available.
- **Family labels** (`fkealrt`, `obfuscator`, `winwebsec`, `fakeav`): VT labels only, all require local confirmation and are not adopted in this report.

## 8. Payloads and Artifacts

| Artifact | SHA256 | Type | Validation | Context |
|---|---|---|---|---|
| Original sample | `000e731440308f57fde3cf58626ec77edd4f3f89a9d9e964ea170d18fdef9069` | PE32 executable | validated | Multi-layer packed malware; VT 60/74 |
| Decrypted shellcode | `537c40bc4192ce13b43891f959688f6c712b9d4bf33fb06e6dd5998f51cf32ea` | x86 shellcode | validated | 1717-byte self-relocating PE loader; no VT record |
| Decoded second-stage PE | `8419a4bff9b43af1f59a0f27cbf4535f4ed007bb7b3006fe77da2262cdb62f23` | PE32 (PECompact2-packed) | validated | 3-section GUI, requireAdministrator; VT 34/46, PECompact 2.xx |

## 9. Indicators of Compromise

### Network
```text
Not locally observed. External-only (VT behaviour_summary):
  112.121.178.189                          C2 IP (HTTP)
  http://112.121.178.189/api/urls/?ts=8b58a4b2&affid=59227
  http://112.121.178.189/api/stats/install/?ts=8b58a4b2&affid=59227&ver=3050007&group=liv
  User-Agent: Mozilla/4.0 (compatible; MSIE 7.0; Windows NT 5.1; GTB0.0; .NET CLR 1.1.4322)
  Server: Microsoft-IIS/10.0
```

### Host
```text
Not locally observed. External-only (VT behaviour_summary):
  Mutexes: 529C50FF01A6CA1B670EFB3DD151FC4E, 539D520002A7CB1C680FFC3ED252FD4F, RasPbFile, ShimCacheMutex
  Registry keys set (external):
    HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings\ZoneMap\*
    HKCC\Software\Microsoft\windows\CurrentVersion\Internet Settings\ProxyEnable
    HKEY_USERS\S-1-5-21-...\Software\Microsoft\windows\CurrentVersion\Internet Settings\*
```

### Persistence
```text
Not locally observed. External-only (VT behaviour_summary):
  HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce\
    529C50FF01A6CA1B670EFB3DD151FC4E
```

## 10. Detection Opportunities

### Behavioral
- **Loader-phase import-resolution failure**: The sample terminates with `STATUS_ENTRYPOINT_NOT_FOUND` during loader init if `DESK.cpl!DisplaySaveSettings` or `DispatchMessageA` (USER32) are unavailable. Systems with these imports present may see full execution.
- **Devenum.dll LoadLibraryW call**: The stub loads `devenum.dll` via a byte-reconstructed WCHAR name. Monitor for unusual `LoadLibraryW("devenum.dll")` calls from non-DirectShow processes.
- **NtTerminateProcess with STATUS_ENTRYPOINT_NOT_FOUND**: A process that terminates during loader initialization with this specific status code — particularly one with a `DESK.cpl` import — is a strong indicator of this sample.
- **Write to oversized writable .rdata**: The oversized `.rdata` section (virtual size ~0x66f58, raw size 0x600) is a structural anomaly.

### Host-based
- **File hash**: Monitor for the original sample SHA256 (`000e7314...`) and the recovered artifact SHA256s (`537c40bc...`, `8419a4bf...`).
- **PECompact2 signature**: `PEC2TO` / `PECompact2` strings in PE files are packer indicators.
- **MSVCrt fwprintf hook**: A `push; ret` trampoline on `msvcrt!fwprintf` with a `VirtualProtect` RWX transition is a specific hook signature.
- **Self-module file read**: The shellcode reads its own module file via `GetModuleFileNameA` + `CreateFileA` + `SetFilePointer` + `ReadFile` — an unusual pattern for a benign executable.

### Network-based
- **C2 HTTP traffic**: Monitor for HTTP GET requests to `112.121.178.189` with paths `/api/urls/` and `/api/stats/install/` and the `affid=59227` parameter (external-only; not locally confirmed).
- **IIS 10.0 server header**: The external C2 presents as Microsoft-IIS/10.0.

## 11. Mitigations and Triage Notes

- **Loader gate bypass strategy**: To enable dynamic analysis, supply a stub `DESK.cpl` that exports `DisplaySaveSettings`, or patch the IAT earlier in the loader process (e.g., hook `LdrpInitializeProcess` or the import-resolution routine in ntdll).
- **PECompact2 unpacking**: The decoded second-stage PE (`8419a4bf...`) requires a dedicated PECompact2 unpacker (e.g., `peuncompact` script or runtime dump) before terminal capability analysis.
- **The DispatchMessageA NULL slot** should be investigated by reading the raw file's OFT entry at RVA 0x4088 to determine whether the import name is genuine or deliberately obfuscated.
- **Public IOCs**: The external C2 IP and RunOnce key are high-confidence leads from public sandbox reports, but they require local confirmation. Set up network monitoring for the C2 IP and check for the RunOnce key in environments where the sample may have executed.
- **The fwprintf hook** may be a data-gathering, anti-forensics, or logging mechanism. Its purpose can only be determined after a loader gate bypass enables the shellcode to execute.

## 12. Classification and Risk

| Field | Value |
|---|---|
| Malware family | Unknown / unconfirmed (VT labels `fkealrt`/`obfuscator` are external-only) |
| Malware type | Multi-layer packed downloader/installer (suspected, based on loader architecture and public sandbox reports) |
| Risk level | High — the loader architecture is sophisticated (self-relocating shellcode, in-place process hollowing, commercial packer), and public reports describe C2 communication and persistence |
| Final confidence | 0.85 (malicious architecture confirmed; terminal payload capability and most IOCs unconfirmed) |

## 13. Priority Follow-up Actions

| Priority | Target | Action | Success criterion |
|---:|---|---|---|
| 1 | Unpack PECompact2 stage | Run a dedicated PECompact2 unpacker on `decoded_second_stage_pe.bin` (SHA256 `8419a4bf...`) | Decompressed `.text`; real import surface and execution path identified |
| 2 | Bypass loader gate | Supply stub DESK.cpl exporting `DisplaySaveSettings`, or hook `LdrpInitializeProcess` to patch IAT earlier | Entry BP 0x4018A0 trips; decryptor destination recorded |
| 3 | Confirm fwprintf hook | After bypass, breakpoint at hook installation (0x57E–0x58C) and record redirected destination | Hook target and enable state confirmed |
| 4 | Network observation | After bypass/unpack, monitor for WinHttp/WinInet/URL APIs and DNS/HTTP traffic | C2 communication confirmed or ruled out |
| 5 | Verify DispatchMessageA slot | Read raw file's OFT entry at RVA 0x4088 to determine if import name is genuine or obfuscated | Cause of NULL slot determined |

## 14. Final Assessment

### Supported conclusion
The sample is a multi-layer packed malware with a fully resolved loader architecture. Layer 1 (XOR-decrypting PE32 stub), Layer 2 (self-relocating two-phase PE loader shellcode performing in-place process hollowing), and Layer 3 (PECompact2-packed PE) are all validated through offline replication and static analysis. The loader chain is malicious: the shellcode reads its own module file, delta-decodes an embedded PECompact2-packed PE, and rewrites the parent process's PEB/LDR entry. The same XOR key (`0x9A246A73`) is reused across layers 1 and 2, confirming the architecture's integrity. The sample is malicious with high confidence (0.85), and the terminal payload (behind the PECompact2 layer) is likely a downloader/installer based on the loader architecture and public sandbox reports.

### Claims not supported by current evidence
- **No specific malware family** is confirmed (VT labels `fkealrt`/`obfuscator`/`winwebsec`/`fakeav` are external-only and not locally corroborated).
- **No network activity, C2 communication, or exfiltration** was locally observed.
- **No persistence, registry modification, or file drops** were locally observed.
- **No process injection, credential theft, or ransomware behavior** was locally observed.
- **The cryptnet imports are NOT fabricated** — they resolve to real `cryptnet.dll` addresses (live IAT reads).
- **The pre-entry termination is NOT an anti-debug check** — it is an environment-gated import dependency (`DESK.cpl!DisplaySaveSettings` missing).

### Analyst notes
- The loader gate termination is a significant analysis obstacle. The sample depends on `DESK.cpl!DisplaySaveSettings` (a Control Panel applet), which is not present in this analysis VM. Public sandboxes that successfully executed the sample likely had the required environment.
- The PECompact2 packer on the third layer is a commercial protection (BitSum Technologies). Its presence suggests the author invested in commercial obfuscation, which is consistent with a financially motivated or organized threat.
- The `msvcrt!fwprintf` hook is unusual. If confirmed as an active hook, it could indicate output capture, data redirection, or anti-forensics behavior. This warrants further investigation after a loader gate bypass.
- The `requireAdministrator` manifest on the PECompact2 stage indicates the terminal payload requires elevated privileges. This is consistent with installer-type malware that modifies system configuration.
- Key reuse across layers is a common weakness in custom packing schemes — the analyst can recover all layers once the first key is found.
- The recovered 1717-byte shellcode has no VT record, suggesting it is a custom or bespoke loader not previously seen in public collections.