# Malware Analysis Report

**Sample:** `000d6230792fefff601c0e5e87369196fdd5cfb484fdd87916a080d8b9ffc1c6`
**Report stage:** 08-report (presentation layer)
**Sources:** stages 01–07 JSON artifacts; `07-deepdive.json` is authoritative for claims.

---

## 1. Sample Identification

| Field | Value |
|---|---|
| File name | `000d6230792fefff601c0e5e87369196fdd5cfb484fdd87916a080d8b9ffc1c6` (VirusTotal identity: `...ffc1c6.exe`) |
| Absolute path | `H:\Dataset\files\malware\000d6230792fefff601c0e5e87369196fdd5cfb484fdd87916a080d8b9ffc1c6` |
| SHA256 | `000d6230792fefff601c0e5e87369196fdd5cfb484fdd87916a080d8b9ffc1c6` |
| Size | 390,144 bytes |
| Format | PE32 GUI, Intel 80386 |
| Architecture | x86 (32-bit) |
| Image base | `0x400000` |
| Original entry point | `0x401510` |
| Packing / protection | Custom in-place self-decoding packer (toolchain unidentified); obfuscated entry gate, import-table self-modification, GlobalFlags anti-debug checks, custom XOR+add+byteswap decode loop |

---

## 2. Executive Summary

### Verdict

**Malicious** — custom-packed loader/dropper. The sample is a loader stub: it decodes an in-memory first-stage shellcode, which in turn loads a second-stage PE. The second stage never executed in our isolated run, so its final behavior is unknown. Public detection is strong (64/64 engines on VirusTotal).

### Confidence

**0.9** for the malicious-loader verdict. Maliciousness is independently established; confidence is capped below certainty because the final payload's behavior (the factor that determines impact) was never observed locally.

### Plain-language assessment

This file is a packer that hides its real work. When run, it (1) passes through an obfuscated entry check, (2) decrypts a 1,728-byte block of shellcode in memory using a custom algorithm, and (3) hands control to that shellcode, which is a small hand-written PE loader. That loader was built to map and run a second, larger program in memory. In this analysis the second program never actually executed: the memory region the packer reserved for it was never committed, so the in-process run stopped at the point the shellcode begins. We recovered and validated the first-stage shellcode analytically. We also recovered a 335 KB blob claimed to be the second stage, but it is **not a valid loadable PE** and its origin could not be reproduced from the documented steps, so its contents and capabilities cannot be asserted. Public sandbox reports (VirusTotal) label the file `trojan.rogue/fraudtool` with a `spreader` tag and report a C2 endpoint and a RunOnce persistence key — these are external-only leads, not observations from this run.

### Key findings

- The original sample is a **malicious, custom-packed loader** (PE32 GUI, entry `0x401510`); VirusTotal reports **64 malicious / 0 suspicious / 8 undetected** engine detections. *(fr-001, confirmed, 0.9)*
- The packer uses an **obfuscated entry gate** (ROR-based, conditional `__halt`) that passes live to a chain of ~49 single-call wrapper functions, plus **GlobalFlags anti-debug** checks that detect the debugger (`0x8000`) but do **not** block execution. *(fr-003, confirmed, 0.88)*
- A custom decode loop (`sub_401B84`, key `0x22CC456A`, XOR+add+byteswap) produces a **validated 1,728-byte first-stage shellcode** (`decoded_payload.bin`, sha256 `9f8e4794…`), independently hash-verified. *(fr-002, confirmed, 0.92)*
- The stage-1 shellcode is a **position-independent PE loader**: PEB-walk, 16-API rolling-hash resolution, RWX `VirtualAlloc`, manual PE load (section mapping / relocation / imports / initterm). It contains **no anti-VM, anti-debug, or timing checks**. *(fr-002 / fin-p2-001, confirmed)*
- The claimed **"0x6AC-byte second-stage PE embedded at shellcode offset 0x15"** is **structurally impossible** (0x15+0x6AC exceeds the 1,728-byte shellcode) and is **rejected**. The `rep movsb` copies the shellcode's own body, not an embedded PE. *(fr-004, contradicted)*
- `decoded_stage2_raw.bin` (335,872 bytes, sha256 `0ec0a946…`) exists and contains a parseable PE header at offset `0xB30C`, but it is **not a valid loadable PE** and its production is **not reproducible** from the documented steps (the progress log records failures). Capabilities cannot be attributed from it. *(fr-005, caveated, 0.35)*
- **C2, persistence, network, and family identity were not observed locally**; the strongest public signal is a loader/dropper (spreader) character. *(fr-008)*

---

## 3. Analysis Scope and Environment

| Field | Value |
|---|---|
| Work directory | `C:\Users\ADMIN\HyperAgent\reports\000d6230792fefff601c0e5e87369196fdd5cfb484fdd87916a080d8b9ffc1c6` |
| Static readiness | Ready — IDA Professional 9.0 + IDALib MCP (`01-prepare-env.json`) |
| Dynamic readiness | Ready — VMware Workstation 17 guest (Win10 x64, snapshot `VMRunV4`, IP `192.168.248.169`), x64dbg remote-debug via x64dbg-MCP |
| Isolation model | Host orchestrator + isolated guest execution (VM only executes the sample; analysis tooling runs host-side) |
| Analysis limitations | Local dynamic run stopped at the decode exit (second stage never loaded); stage-1 shellcode decoded analytically, not executed in-process; 16 shellcode API hashes unmapped to names; public lookups were hash/report-only — no binaries uploaded |

---

## 4. Packing and Artifact Recovery

- **Packing decision:** Required. Only 8 KB of executable `.text` in a 390 KB binary with a 407 KB rw `.rdata` section, an obfuscated entry gate, import-table self-modification, and a single custom decode loop — execution logic is invisible until the decode runs. *(fin-002, 0.9; unpack_decision)*
- **Recovery status:** **Stage 1 recovered and validated**; **stage 2 recovered but not validatable**. The decode algorithm (`out = (src ^ key) + 1; key = byteswap(out)`, seed `0x22CC456A`, size `0x6BC`) was confirmed live in the guest; the shellcode was then produced analytically because in-process writes faulted on an uncommitted page.
- **Candidate handoff / OEP:** Stage-1 shellcode entry `0x0` (GetPC prologue). Second-stage parsed PE entry `0xA472` (ImageBase `0x400000`, SizeOfImage `0xC9000`) — but the containing artifact is **not a loadable PE**.
- **Recovered artifacts:**
  - `decoded_payload.bin` — 1,728-byte stage-1 x86 shellcode, **validated** (sha256 `9f8e47944d294db5888d3cab9dd35f43f212b8b7dff92ae4439fe5358d7303e3`).
  - `decoded_stage2_raw.bin` — 335,872-byte raw blob, **partial/unvalidated** (sha256 `0ec0a9464ed57a3b0451b1527006c2177fc183b760049c7a87322d6cca50e012`); parseable PE header at `0xB30C`, not loadable, provenance unreproducible.
  - `decoded_stage2_pe.exe` (host header-reconstruction attempt) — **invalid**; no `PE\0\0` signature at the reconstructed offset. *(ev-dd-007)*

---

## 5. Static Analysis

### Original sample

- **Obfuscated entry gate** (`0x401510`): writes to an `.idata` import slot, computes a `__ROR4__`-derived branch, with conditional `__halt()`/`JUMPOUT` paths. Statically unresolvable; confirmed live (see §6). *(fin-003, 0.9)*
- **Custom decode loop** (`sub_401B84`): the only non-trivial function; decodes 1,724 bytes from `byte_401ED1` with `out=(src^key)+1; key=bswap(out)`. Seed confirmed live as `0x22CC456A` (static pass-1 text mis-typed `0x22CC816A`; corrected by live disassembly). *(fin-004, 0.85; fin-003 unpack)*
- **Anti-debug:** `GlobalFlags(NULL)`/BeingDebugged checks at six+ sites across the wrapper chain. *(fin-005, 0.7)*
- **Import self-modification / dynamic resolution:** writes to `NSPStartup_1` import slot; function pointers derived via import-address arithmetic (e.g., `(char*)&HeapCreate - 2`); `LoadLibraryW` passed to a vtable-derived call at `0x4010E3`. *(fin-006, 0.8)*
- **49-wrapper loader chain:** near-linear chain of ~49 single-call wrappers (each ~0x38–0x50 bytes) with imported-API calls as decoy filler; deepest node `sub_401428` at depth 20. *(fin-007, 0.85)*
- **No embedded configuration:** all 43 static strings are API/module names; no MZ/PE, URL, IP, or registry path in static data (sampled scan). *(fin-008, 0.8)*

### Recovered artifact (`decoded_payload.bin`, stage-1 shellcode)

- **First-stage PE loader** (716 instructions, 0 `int3`): GetPC prologue → PEB walk `fs:[0x30]` → MZ/PE scan → rolling-hash API resolution (`ror eax,7; rol [esp],0xd; add`; 16-entry table at offset `0x64A`) → `VirtualAlloc(0,0x6AC,0x1000,0x40)` RWX → `rep movsb` → XOR+bswap decode → manual PE load (section mapping, relocation fixup, import resolution, `msvcrt.initterm` thunk). *(fin-p2-001, 0.95)*
- **File-I/O path:** `GetModuleFileNameA` + `CreateFileA` (+ `CreateFileMappingA`/`MapViewOfFile` per deepdive resolution) at `0x606` — opens the original PE from disk as a second-stage source. This is the basis for the **self-reloading-loader hypothesis** (see §7). *(fin-p2-005, 0.85; ev-dd-010)*
- **No anti-analysis** in the shellcode (0 `int3`/`rdtsc`/`int 0x2D` in 716 instructions); all anti-debug belongs to the original packer stub. *(fin-p2-004, 0.95)*
- **API hash-to-name mapping unresolved:** the algorithm and 16-entry table are confirmed, but the individual hash→name mapping was not computed; a partially inferred list (LoadLibraryA, GetProcAddress, HeapAlloc, VirtualAlloc, HeapFree, GetModuleFileNameA, CreateFileA, CreateFileMappingA, MapViewOfFile, initterm) is available. *(fr-007, unknown, 0.6)*

---

## 6. Dynamic Analysis

### Observed behavior

- **Entry gate passed live:** at `0x40152E`, the ROR gate computes `0x96`; `sub cl,ah` → `CF=0`, `jb` (conditional `__halt`) **not taken**; execution proceeds into the loader chain. *(ev-dyn-001, 1.0)*
- **Anti-debug detected but non-blocking:** `GlobalFlags`/BeingDebugged checks at `0x4010D0`/`0x4010FF`/`0x401346` returned `0x8000` (debugger present); no alternative path or crash — execution continues linearly. *(ev-dyn-005, 0.95)*
- **Decode loop executed with correct key:** seed `0x22CC456A` in EDI at `0x401BE1`; decode source at `0x401ED1`; loop reached exit (`0x401C0B`). *(ev-dyn-002, 1.0)*
- **Memory allocation:** packer reserved a 1 MB region (base `0x250000`) for the decode output. *(bhv-dyn-004, 0.95)*
- **Offline decode confirmed:** stage-1 shellcode decoded analytically matches the predicted output (sha256 `9f8e4794…`, verified). *(fin-dyn-004, 1.0)*

### Not observed during the run

- **Second-stage load / execution** — the decode destination (`0x2E0073+`) sat in an **uncommitted MEM_RESERVE** region; writes faulted and were skipped by the debugger, so the in-memory payload never materialized. *(ev-dyn-003, 0.95)*
- **Network communication** — the stage-1 shellcode has no networking capability; C2 config would live in the never-loaded second stage. *(bhv-dyn-007, unknown)*
- **Process injection** — none observed; the shellcode performs in-process manual PE loading, not cross-process injection. *(bhv-dyn-006, 0.9)*
- **Anti-VM** — none in packer or shellcode. *(bhv-dyn-003, 0.95)*
- **Persistence, C2, credential/exfiltration, destructive behavior** — none locally observed (observation gap, not proof of absence).

### Runtime limitations

- Uncommitted decode destination (MEM_RESERVE) + debugger exception-skipping prevented in-memory materialization. *(rca-001)*
- Debugger divergence at a **disguised `HeapCreate` int3 hotpatch** (`(char*)&HeapCreate - 2 = 0x75970CDE`) diverted the unpack live path. *(unpack limitations; rca-001)*
- Observation window limited to `entry_gate_to_decode_exit_only`. *(runtime.observation_window)*

---

## 7. Deepdive Reconciliation

### Confirmed findings

- **Malicious packed loader** (fr-001, 0.9) — identity, packer, and loader character confirmed live; verdict capped below certainty by unverified final-payload behavior.
- **Stage-1 shellcode recovery validated** (fr-002, 0.92) — decode algorithm confirmed live; artifact hash independently verified; full loader-stub reading corroborated across unpack + static-pass2 + dynamic.
- **Packer: obfuscated gate, import self-modification, non-blocking anti-debug** (fr-003, 0.88) — gate passage and `GlobalFlags`→`0x8000` confirmed in two independent dynamic runs; real but not evasive.

### Findings requiring caveats

- **`decoded_stage2_raw.bin`** (fr-005, 0.35): exists and hashes correctly; PE header at `0xB30C` parses (I386, 3 sections, entry `0xA472`, ImageBase `0x400000`, SizeOfImage `0xC9000`), but it is **not a valid loadable PE** (no valid DOS header, section `RawPtr` fields file-start-inconsistent with the mid-file header), its production is **not reproducible** from the documented attempt log (which records failures), and its SizeOfImage/ImageBase match the original sample. **No imports, strings, or capabilities can be asserted from it.**
- **Second-stage source = original PE mapped from disk (self-reloading loader) — hypothesis, not validated** (fr-006, 0.55): supported by the resolved `CreateFileA`/`CreateFileMappingA`/`MapViewOfFile` path, the matching SizeOfImage/ImageBase with the original, and a progress-log note that the decode "operates on the mapped view of the original PE file." Config fields `pe_offset=0xB20400` / `size=0x40000` exceed the original file size on their face and are unexplained.

### Rejected or downgraded findings

- **"0x6AC-byte second-stage PE embedded at shellcode offset 0x15" — REJECTED** (fr-004, contradicted, 0.1): `0x15 + 0x6AC = 0x6C1` exceeds the 1,728-byte (0x6C0) shellcode; the region is the shellcode's own code/config; a size-preserving XOR+bswap decode cannot expand `0x6AC`→`0x52000` bytes. The `rep movsb` (esi=`0x12`, ecx=`0x6AC`) copies the shellcode's own body + config block. *(ct-001, resolved)*
- **Stage-2 decode key misread** — resolved to `0x22CC456A` (config dword LE at `0x6B9` = `0x5A89AFFB` XOR `0x7845EA91`; the progress-log `0x7845B018` was a misaligned read). This key is identical to the packer's stage-1 seed — a genuine cross-stage corroboration. *(ct-002, resolved)*
- **"Decode loop reached exit" vs "decode output never materialized"** — resolved as non-contradictory: control flow reached the exit while writes were bypassed by exception-skipping. *(ct-004, resolved)*

### Unresolved decision point

- **`decoded_stage2_raw.bin` provenance** (ct-003, unresolved): progress-log failures contradict the final dynamic narrative; the artifact's exact origin is unknown and its production is not reproducible. **The report does not present it as a confirmed decoded second-stage payload.**
- **Final payload capabilities** (C2 endpoints, persistence mechanism, family identity) remain **not locally established**.

### Public-source corroboration or conflict reflected in Deepdive

- **VirusTotal** (06-intel.json): 64 malicious / 0 suspicious / 8 undetected / 4 type-unsupported; labels `trojan.rogue/fraudtool`; tags `spreader`, `obfuscator`; category `fakeav`. These are **public attribution hints only** — enrichment, not local confirmation, and not used to upgrade local claims. *(fr-001 / fr-008)*
- **External-only IOCs** (from `behaviour_summary`, **not observed locally**): C2 IP `175.41.28.156` with HTTP GET `/api/urls/` and `/api/stats/install/` (incl. `?ts=2b8bab86&affid=66803`); HKCU RunOnce persistence GUID `6F638C1208E9B91B55DDEB0F7B07D287` with matching mutex and All-Users AppData copy; IFEO key for `996E.exe`; SafeBoot and Safer `CodeIdentifiers` registry keys. These are follow-up leads, attributed to VirusTotal, not local evidence. *(ev-dd-011; fr-008)*
- Recovered-artifact hashes (`9f8e4794…`, `0ec0a946…`) return **no public record** on VirusTotal (404), consistent with freshly recovered in-house artifacts. *(06-intel)*

---

## 8. Payloads and Artifacts

| Artifact | SHA256 | Type | Validation | Context |
|---|---|---|---|---|
| `000d6230792fefff601c0e5e87369196fdd5cfb484fdd87916a080d8b9ffc1c6` (original) | `000d6230792fefff601c0e5e87369196fdd5cfb484fdd87916a080d8b9ffc1c6` | PE32 GUI packed loader | validated | Original sample; publicly detected malicious (64 engines). |
| `decoded_payload.bin` | `9f8e47944d294db5888d3cab9dd35f43f212b8b7dff92ae4439fe5358d7303e3` | x86 shellcode, stage-1 PE loader | **validated** (hash independently verified) | 1,728 bytes; recovered analytically from `sub_401B84` decode (key `0x22CC456A`). |
| `decoded_stage2_raw.bin` | `0ec0a9464ed57a3b0451b1527006c2177fc183b760049c7a87322d6cca50e012` | raw blob w/ embedded PE header @ `0xB30C` | **partial** — not a loadable PE; provenance unreproducible | 335,872 bytes; capabilities unknown. |
| `decoded_stage2_pe.exe` | — | header-reconstruction attempt | **invalid** (no `PE\0\0` at reconstructed offset) | Produced during recovery; not usable. |

---

## 9. Indicators of Compromise

### Network

```text
Not observed locally.

External-only leads (VirusTotal behaviour_summary, NOT local observations — follow-up leads only):
- http://175.41.28.156/api/urls/
- http://175.41.28.156/api/urls/?ts=2b8bab86&affid=66803
- http://175.41.28.156/api/stats/install/
```

### Host

```text
Observed / locally established (hashes):
- 000d6230792fefff601c0e5e87369196fdd5cfb484fdd87916a080d8b9ffc1c6   original packed PE32 loader
- 9f8e47944d294db5888d3cab9dd35f43f212b8b7dff92ae4439fe5358d7303e3   decoded stage-1 shellcode (1,728 B, PE loader)
- 0ec0a9464ed57a3b0451b1527006c2177fc183b760049c7a87322d6cca50e012   decoded stage-2 raw blob (335,872 B; NOT a validated payload)

External-only leads (VirusTotal behaviour_summary, NOT local observations):
- Mutex / RunOnce GUID: 6F638C1208E9B91B55DDEB0F7B07D287
- IFEO key: \Registry\Machine\Software\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\996E.exe
- SafeBoot / Safer policy keys (see 06-intel.json external_only for full list)
```

### Persistence

```text
Not observed locally.

External-only lead (VirusTotal behaviour_summary, NOT a local observation):
- HKEY_CURRENT_USER\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce\6F638C1208E9B91B55DDEB0F7B07D287
  (with matching mutex and AppData copy path C:\Documents and Settings\All Users\Application Data\6F638C1208E9B91B55DDEB0F7B07D287\6F638C1208E9B91B55DDEB0F7B07D287)
```

---

## 10. Detection Opportunities

### Behavioral

- **Trigger on self-decoding / shellcode indicators:** large rw section (`407 KB` `.rdata` in an 8 KB-code binary), import-table writes at entry, `VirtualAlloc(…, PAGE_EXECUTE_READWRITE)` followed by manual section mapping — all present in this sample.
- **Watch for manual PE-load sequences:** PEB walk (`fs:[0x30]`) → export-table hash loop → RWX allocation → `rep movsb` + decode → section mapping. EDR behavioral rules on "memory → execute after decode" catch this class.
- **GlobalFlags/BeingDebugged checks returning non-zero without action** are a packer-stub signature worth flagging even though they are non-evasive here.

### Host-based

- Hash-block the three locally established hashes above (original + two recovered artifacts).
- Monitor the external-only persistence leads (HKCU `RunOnce` GUID, IFEO `996E.exe`, All-Users AppData GUID dir) and Safer/SafeBoot policy keys as **candidate detections** pending local confirmation.
- If a loadable second-stage is ever reconstructed, its IAT/strings become additional hash/signature sources.

### Network-based

- **No local network evidence.** As **candidate** indicators only, watch HTTP GETs to `175.41.28.156` under `/api/urls/` and `/api/stats/install/` (external sandbox behavior). Any detection from these must be treated as lead-matching, not confirmed.

---

## 11. Mitigations and Triage Notes

- **Treat the sample as a loader, not the final threat.** Containment of this file alone may not remove the true payload — the second stage (where C2/persistence lives) was not recovered as a usable artifact.
- **Re-run in a guest with exception handling left to the sample** (no debugger Skip/erun) to let the packer's SEH commit-on-write materialize the second stage (see §13, tgt-004). This is the single highest-leverage next step for local capability confirmation.
- **Do not use the external-only IOCs as confirmed indicators** in detection signatures without local validation; they are public-sandbox observations.
- **Do not attribute a family** (`rogue`/`fraudtool`/`fakeav`/`spreader`) on the basis of public labels — local confirmation is required.
- Preserve `decoded_payload.bin` and the raw decode source (`src_hex.txt`) as evidence; they are the validated portion of the recovery chain.

---

## 12. Classification and Risk

| Field | Value |
|---|---|
| Malware family | **Unknown / unconfirmed** (public hints only: `rogue`/`fraudtool`/`fakeav`, `spreader` tag) |
| Malware type | Packed loader / dropper (stage-1 shellcode loads a second-stage PE in memory) |
| Risk level | **High** (malicious, obfuscated, self-decoding loader with a second stage whose capabilities are unconfirmed; public signal suggests spreading/C2 behavior) |
| Final confidence | **0.9** (malicious verdict); final-payload behavior unverified |

---

## 13. Priority Follow-up Actions

| Priority | Target | Action | Success criterion |
|---:|---|---|---|
| 5 | Second-stage decode provenance (tgt-001) | Reverse the exact `0x4DA` decode semantics (incl. `sub ecx,3`), reconcile config fields (`pe_offset`, `size`), decode candidate regions of the original sample with key `0x22CC456A`, compare to `decoded_stage2_raw.bin` | A reproducible decode yields a valid loadable PE with a real IAT; the artifact's role is established |
| 5 | Reconstruct loadable stage-2 header (tgt-002) | Fix DOS header (MZ at 0, valid `e_lfanew`), make section table file-start-consistent, validate with a PE parser, then extract imports/strings/config/family | A loadable PE whose capabilities (C2, persistence) can be assessed |
| 5 | Map all 16 shellcode API hashes (tgt-003) | Reimplement `ror/rol/add` rolling hash; compute over kernel32 export names; match the 64-byte table at offset `0x64A` | All 16 hashes mapped to specific functions |
| 4 | Clean guest re-run (tgt-004) | Revert to `VMRunV4`; run without exception-skipping so the sample's own SEH handler commits the decode destination; breakpoint `VirtualAlloc`/`VirtualProtect` and the manual-PE-load completion; dump the mapped image | Second stage materialized and entry reached; runtime behavior observed or conclusively absent |
| 3 | Validate external IOCs locally (tgt-005) | Network/persistence monitoring during the tgt-004 run; check for `/api/urls/`, `/api/stats/install/`, RunOnce writes, mutex open, IFEO `996E.exe` | Local evidence confirms, partially matches, or refutes each external IOC |
| 2 | Packer toolchain / family ID (tgt-006) | Compare the 49-wrapper/import-arithmetic packer style against known packers; correlate the shared `0x22CC456A` key and shellcode structure once a stage-2 hash exists | A named packer/family, or a documented "unidentified custom packer" with reproducible similarity |

---

## 14. Final Assessment

### Supported conclusion

- The sample is a **malicious, custom-packed loader** (PE32 GUI, entry `0x401510`), confirmed live: obfuscated entry gate passes; GlobalFlags anti-debug is present but non-blocking; a custom decode loop (key `0x22CC456A`) produces a validated 1,728-byte first-stage shellcode.
- The stage-1 shellcode is a **first-stage PE loader** (PEB-walk, 16-API rolling-hash resolution, RWX `VirtualAlloc`, manual PE load, initterm) with **no anti-analysis of its own** and a file-I/O path consistent with reading the original PE from disk as a second-stage source.
- `decoded_payload.bin` is **validated** (hash independently verified). `decoded_stage2_raw.bin` **exists but is not a loadable PE and its origin is unreproducible** — it is not a confirmed second-stage payload.
- The **"embedded 0x6AC-byte PE at offset 0x15"** claim is **rejected** as structurally impossible; the second-stage source is most plausibly the original file mapped from disk (**hypothesis**, not validated).
- **C2, persistence, network, and family identity were not locally observed**; public signals (`trojan.rogue/fraudtool`, `spreader`, external C2/RunOnce IOCs) are attributed follow-up leads only.

### Claims not supported by current evidence

- Any **distinct, recovered, analyzable second-stage PE** payload (rejected: not loadable, provenance unreproducible).
- **Persistence, C2 communication, C2 IPs/endpoints, credential access, exfiltration, destructive impact, or ransomware behavior** as locally observed.
- **Family identity** (`rogue`/`fraudtool`/`fakeav`) or the **`spreader` tag** as confirmed.
- **Payload execution beyond the stage-1 loader** (the second stage never executed locally).
- Presentation of **external-only public-sandbox IOCs** as local evidence or as `matched_local` indicators.

### Analyst notes

- Absence during the one observed run is **not** proof of nonexistence — the second stage simply never executed. Confidence in the *loader* verdict is high (0.9); confidence in any *capability* claim about the final payload is **not** established.
- The recovered stage-2 header's ImageBase/SizeOfImage identity with the original sample, plus the progress-log note that the decode operates on a mapped view of the original PE, are the strongest (though unproven) signals that this is a **self-reloading loader** rather than a distinct embedded payload.
- Priority is on **reproducing the second stage** (tgt-001/tgt-002/tgt-004) before any detection-signature or attribution work proceeds.
