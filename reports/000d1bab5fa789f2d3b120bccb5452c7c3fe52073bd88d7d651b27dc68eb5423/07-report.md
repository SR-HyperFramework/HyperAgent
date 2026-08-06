# Malware Analysis Report

## 1. Sample Identification

| Field | Value |
|---|---|
| File name | 000d1bab5fa789f2d3b120bccb5452c7c3fe52073bd88d7d651b27dc68eb5423 |
| Absolute path | H:\Dataset\files\malware\000d1bab5fa789f2d3b120bccb5452c7c3fe52073bd88d7d651b27dc68eb5423 |
| SHA256 | 000d1bab5fa789f2d3b120bccb5452c7c3fe52073bd88d7d651b27dc68eb5423 |
| Architecture | x86 (PE32, Intel 80386) |
| Original entry point | 0x64012FAA (DllEntryPoint) |
| Packing / protection | No conventional packer observed; runtime string/API obfuscation |

*Source: 01-prepare-env, static-pass1 (sample-identity-service-dll-001, packing-no-standard-packer-001), unpack (packing-not-observed-001).*

## 2. Executive Summary

### Verdict

**Malicious** — interpreted as a service-proxy remote-tasking implant, on strong structural and capability evidence.

### Confidence

**0.72** (deepdive verdict confidence). Confidence is capped below 0.8 because none of the sample's worker-thread behaviors — C2 exchange, process launch, persistence — were executed and validated at runtime.

### Plain-language assessment

This is a legitimate-looking Windows *service DLL* (a DLL designed to be hosted by the `svchost.exe` service host, not run as a standalone program). It stands in for — and proxies — the real `wkssvc.dll` service, and in the background it runs its own worker thread. That worker is built to:

- keep a list of hidden (obfuscated) network addresses that it can rotate through,
- wait until the machine has internet connectivity,
- talk to one of those addresses using a custom, non-standard message format,
- collect information about the machine (storage devices, installed services, OS/architecture, and COM-based data) to send back, and
- run a program (via a `CreateProcessW`-style call) when the remote server sends back instructions to do so.

Because the DLL refuses to initialize unless it is running inside `svchost.exe`, and the dynamic analysis session could only load it under a generic debugger helper that is not `svchost.exe`, **none of these runtime behaviors actually executed during analysis.** They are confirmed *present in the code* (capability-level) but were **not observed running** and **no C2 address, mutex name, or command payload was recovered.**

### Key findings

- **Sample identity (confirmed, 0.99):** 32-bit PE service DLL gated on being hosted by `svchost.exe`, with `ServiceMain` / `SvchostPushServiceGlobals` / `DllEntryPoint` exports (sample-identity-service-dll-001, ev-sample-identity-1/2).
- **wkssvc service proxy (confirmed, 0.95, caveated):** exported service callbacks load `wkssvc.dll`, decode two export names, resolve them via `GetProcAddress`, and start a worker thread before forwarding the original service call — a proxy/hijack pattern. The specific proxied export names were **not recovered** (loader-wkssvc-forwarder-001, fr-loader-wkssvc-forwarder).
- **Host gating / singleton (confirmed, 0.88):** worker logic only proceeds under `svchost.exe`, after a mutex-based singleton check; no bespoke anti-debug routine confirmed (anti-analysis-host-gating-001, fr-anti-analysis-host-gating).
- **C2/network subsystem (capability, partial 0.70, caveated):** obfuscated IPv4 endpoint pool, connectivity wait, and a custom 0x1D0-byte-framed, magic-validated message protocol are present in code but were **never executed**; endpoints and API names are unrecovered (network-obfuscated-ip-pool-001, fr-network-obfuscated-ip-pool).
- **Host fingerprinting (capability, partial 0.68, caveated):** storage-device IOCTL, Windows service enumeration, OS/arch labeling, and COM-backed collection routines are present; **no exfiltration was observed** (collection-host-fingerprinting-001, fr-collection-host-fingerprinting).
- **Process-launch handoff (capability only, 0.55, caveated):** a `CreateProcessW`-compatible path exists, reached only after C2 task data; it was **not executed** and the API identity is inferred from calling convention, not a recovered string (process-task-launch-001, fr-process-task-launch).
- **Runtime limitation (observed, 0.97):** under x64dbg's `DLLLoader32` helper the DLL was requested for load (`LoadLibraryExW` with the sample path) but was **not retained** as a mapped module — consistent with svchost host-gating, though the cause is inferred (runtime-helper-hosted-session-001, fr-runtime-helper-hosted-session).

## 3. Analysis Scope and Environment

| Field | Value |
|---|---|
| Work directory | reports/000d1bab5fa789f2d3b120bccb5452c7c3fe52073bd88d7d651b27dc68eb5423 |
| Static readiness | Ready (IDA / idalib; PE triage) |
| Dynamic readiness | Ready (approved VMware guest + x64dbg MCP; vmrun workflow) |
| Isolation model | Host orchestrator + isolated guest execution |
| Analysis limitations | Runtime session was **helper-hosted** (`DLLLoader32_<suffix>.exe`), not the intended `svchost.exe` service context, so the worker/C2/task path never executed. No `04-static-pass2.json` or external-intelligence artifact was supplied. No recovered payload artifact exists. |

*Source: 01-prepare-env, 05-dynamic (runtime-helper-hosted-session-001), 06-deepdive (limitations).*

## 4. Packing and Artifact Recovery

- **Packing decision:** No packer detected (`unpack_status = not_needed`). The image is a directly analyzable PE32 DLL with ordinary sections and a populated import directory; protection is **runtime string/API obfuscation**, not a compressed/self-decoding stub (packing-not-observed-001, packing-no-standard-packer-001, packing detected=false, confidence 0.91).
- **Recovery status:** None attempted — unpacking was evaluated as unnecessary. No recovered artifact was produced.
- **Candidate handoff/OEP:** N/A (no unpack round; OEP is DllEntryPoint 0x64012FAA).
- **Recovered artifacts:** None. The only artifacts are the original sample (validated PE32 DLL) and the dynamic support-stage JSON (`05-prepare-vm.json`, `05-trace_guest_loader.json`). No unpacked/secondary payload was recovered.
- **Note (caveat):** the absence of a startup packer does **not** exclude network-delivered compressed/encrypted secondary content, which is beyond this stage (fr-packing-no-standard-packer).

## 5. Static Analysis

### Original sample

- A 32-bit PE service DLL (PE32, image base 0x64000000, 5 sections: .text/.rdata/.data/.rsrc/.reloc, 208896 bytes, entry RVA 0x12FAA, populated import directory). Interpreted for hosting by the Windows service host **`svchost.exe`** (sample-identity-service-dll-001; unpack ev-packing-2).
- **wkssvc proxy/forwarder:** the exported service callbacks (`ServiceMain`, `SvchostPushServiceGlobals`) reach `sub_6400F350`, which calls `LoadLibraryW(L"wkssvc.dll")`, decodes two ASCII export names via `sub_64006890`, resolves them with `GetProcAddress` into `dword_6402D4B8`/`dword_6402D4BC`, and spawns a worker thread (`CreateThread(sub_64011630)`) before forwarding the original call. This is a proxy/hijack pattern (loader-wkssvc-forwarder-001). *Caveat:* the two proxied export names were not recovered and were never runtime-verified (fr-loader-wkssvc-forwarder).
- **Host-gated worker (`sub_64011630`):** lowercases the module path, looks for `L"svchost.exe"`; only then runs the mutex singleton gate (`sub_64010690`, `CreateMutexW` + `WaitForSingleObject(...,0)`) and starts the worker (sample-identity-service-dll-001, anti-analysis-host-gating-001).
- **C2/network (`sub_64010390`, `sub_6400A2E0`, `sub_6400A620`):** decodes five 12-byte obfuscated blobs and converts each with `inet_addr` into a rotating IPv4 pool; waits on an `InternetGetConnectedState`-compatible check (`sub_6400F450`); exchanges data in 0x1D0-byte (464-byte) fragments with retry/timeouts; normalizes fields with `htonl/ntohl`, builds 0x19-byte-header frames via a local encoder, and validates inbound frames against expected tokens/magics (network-obfuscated-ip-pool-001). *Caveat:* code is reachable-but-unexecuted; endpoints/API names unrecovered (fr-network-obfuscated-ip-pool).
- **Host fingerprinting (`sub_6400B120`, `sub_64006120`, `sub_64010850`/`sub_6400B530`):** storage-device `DeviceIoControl`-style queries (codes 0x2D1400, 0x700A0), Windows service enumeration (`EnumServicesStatusW`), OS/arch labeling, and COM-backed inventory via `CoInitializeEx`/`CoCreateInstance`/`Variant` APIs (collection-host-fingerprinting-001). *Caveat:* routines present but never executed; data being actually exfiltrated is unverified (fr-collection-host-fingerprinting).
- **Process-launch handoff (`sub_6400FF30`/`sub_6400DDD0`):** after a non-empty network response, calls a dynamically-resolved API with a `CreateProcessW`-compatible argument layout, then closes `hProcess`/`hThread` (process-task-launch-001). *Caveat:* capability only; not executed; API identity inferred from calling convention (fr-process-task-launch).
- **Config/CLSID (`sub_640039D0`, `sub_64006340`):** reads an obfuscated HKLM path/value and falls back to a resource string + `CLSIDFromString` for a GUID consumed by COM collection. Exact key/value/GUID unrecovered (configuration-registry-clsid-001, fr-configuration-registry-clsid).

### Recovered artifact

- Not applicable. No recovered/unpacked artifact exists to analyze in a pass-2 round (unpack recovery_status `not_needed`; no `04-static-pass2.json`).

## 6. Dynamic Analysis

*Runtime was performed guest-side via the approved x64dbg workflow. The session was hosted by x64dbg's generic DLL loader (`DLLLoader32_<suffix>.exe`) rather than the intended `svchost.exe` service host.*

### Observed behavior

- The debugger helper issued a `LoadLibraryExW` request for the sample's exact guest copy path `C:\Users\h26v\Desktop\000d1bab5fa789f2d3b120bccb5452c7c3fe52073bd88d7d651b27dc68eb5423`, i.e., an attempt to load the sample DLL occurred (behavior-helper-dllload-001, ev-helper-load-sample-1).
- The sample was **not retained** as a mapped module: it never appeared in `module_list`, and a memory search for the `MZ` signature in the expected image region returned 0 results — i.e., a load-then-rollback (behavior-sample-not-retained-001, ev-helper-not-retained-1). *Caveat:* the cause is inferred as svchost host-gating; a captured `DllMain` return value was not obtained (fr-runtime-helper-hosted-session, contradiction-host-gate-rejection-direction).

### Not observed during the run

- The svchost host-gate and mutex singleton gate did **not fire** — the DLL never loaded, so the gate path never executed (runtime-gate-not-exercised-001). No plaintext mutex name was captured.
- **No worker thread** was launched (behavior-worker-001, not_observed).
- **No network activity**: no obfuscated IP-pool decode, no DNS/socket activity, no C2 exchange (behavior-network-001, runtime-no-ip-pool-or-c2-001, not_observed).
- **No process launch** / task-execution handoff (behavior-task-exec-001, not_observed).
- **No persistence write and no exfiltration** observed (deepdive final_claim_policy allowed claim 8).

### Runtime limitations

- The dynamic environment (x64dbg `DLLLoader32` helper) does **not** reproduce `svchost.exe` service hosting, which blocked the worker from running. The absence of runtime behavior is attributable to the missing natural service host, **not** contradiction of the statically-present capabilities (contradiction-static-capability-vs-dynamic-absence).
- No C2 IPs, domains, mutex names, or command payloads are recoverable from this session — these remain live targets (runtime limitations in 05-dynamic).
- The VM was reverted to the clean `VMRunV4` snapshot; no guest analysis process remains (cleanup-revert-success-001 in both 03-unpack and 05-dynamic).

## 7. Deepdive Reconciliation

### Confirmed findings

- Sample is a 32-bit svchost-gated PE service DLL (ServiceMain/SvchostPushServiceGlobals/DllEntryPoint) — **0.99** (fr-sample-identity-service-dll).
- Runtime session was helper-hosted, not `svchost.exe`; the DLL was requested for load but not retained — **0.97** (fr-runtime-helper-hosted-session).
- Host gating + mutex singleton; no active anti-debug — **0.88**, **increased** by dynamic corroboration (fr-anti-analysis-host-gating).
- No startup packer; protection is runtime string/API obfuscation — **0.87**, two independent PE-layout observations (fr-packing-no-standard-packer).

### Findings requiring caveats

- **wkssvc proxy/forwarder** (0.95): confirmed as pattern; specific proxied export names unrecovered and never runtime-verified (fr-loader-wkssvc-forwarder).
- **C2/network capability** (0.70, downgraded from 0.95): code reachable-but-unexecuted; endpoints/API names unrecovered (fr-network-obfuscated-ip-pool).
- **Host-fingerprinting collection** (0.68, downgraded): present, unexecuted, partially obfuscated; exfiltration unverified (fr-collection-host-fingerprinting).
- **CreateProcessW-compatible task handoff** (0.55, downgraded): capability only; not executed; API identity inferred from calling convention (fr-process-task-launch).
- **Config/CLSID selection** (0.62, downgraded): present, fully obfuscated, unvalidated at runtime (fr-configuration-registry-clsid).

### Rejected or downgraded findings

- No finding was rejected outright. The task-execution (0.55) and C2 (0.70) claims were **downgraded** to capability-level because they are static-only, unexecuted, and the underlying API identities/endpoints are unrecovered.

### Unresolved decision point

- **Whether C2 task data triggers local process execution** — the `CreateProcessW`-compatible handoff was never reached (no C2 data). Resolving it (plus recovering the plaintext IP pool, mutex name, and any task payload) requires launching/attaching the sample through its intended `svchost.exe` service host (remote decision point in deepdive; inv-svchost-hosted-runtime, inv-c2-task-payload-and-launch).
- **Root cause of the DLL not being retained** is inferred as host-gating (0.82), but an exception/crash inside `DllMain` or a missing dependency is not fully excluded (contradiction-host-gate-rejection-direction, unresolved).

## 8. Payloads and Artifacts

| Artifact | SHA256 | Type | Validation | Context |
|---|---|---|---|---|
| 000d1bab5fa789f2d3b120bccb5452c7c3fe52073bd88d7d651b27dc68eb5423 | 000d1bab5fa789f2d3b120bccb5452c7c3fe52073bd88d7d651b27dc68eb5423 | original-sample-pe32-dll | validated | Primary analyzed sample; static + dynamic source |
| DLLLoader32_<suffix>.exe (guest) | — | runtime helper loader | observed | x64dbg helper that hosted the session; not the sample's payload |
| 05-prepare-vm.json / 05-trace_guest_loader.json | — | dynamic support artifacts | present | Runtime guest/trace support; no recovered payload |

No unpacked or secondary payload artifact was recovered. No plaintext endpoint, mutex, or command payload exists to list as a confirmed IOC.

## 9. Indicators of Compromise

*Per the deepdive final claim policy, **no IOC values are presented as confirmed** because none were recovered. The following report stage names describe what was expected but not observed.*

### Network
```text
Not observed — no C2 connection, no endpoint/domain contact, no plaintext IPs or task payloads captured.
(Static-only: obfuscated IPv4 pool + custom 0x1D0-byte framed protocol present in code, unexecuted — network-obfuscated-ip-pool-001)
```

### Host
```text
Not observed — no confirmed host IOCs. No mutex name, registry path, or GUID recovered (host-gate and config values remain obfuscated/unrecovered).
```

### Persistence
```text
Not observed — no persistence mechanism was installed or observed; the service-installation path is not visible from the standalone DLL and cannot be claimed (prohibited by final claim policy).
```

## 10. Detection Opportunities

### Behavioral

- Detect an unexpected DLL registering the `wkssvc` service entry points and loading/forwarding to `wkssvc.dll` while spawning a background worker thread — a proxy-service signature (loader-wkssvc-forwarder-001).
- Watch `svchost.exe` processes for the worker-thread fingerprinting routine immediately after startup: storage-device `DeviceIoControl` queries, `EnumServicesStatusW`, and COM `CoCreateInstance` calls clustered shortly after service start (collection-host-fingerprinting-001).
- Flag a service process that tries to reach multiple IPs after a connectivity check (`InternetGetConnectedState`-style) using a high-frequency custom-framed (464-byte) protocol (network-obfuscated-ip-pool-001).

### Host-based

- Detect the DLL only running correctly when hosted by `svchost.exe` and refusing to initialize under other loaders — a strong gating indicator (host-gating-001, runtime-helper-hosted-session-001).
- Monitor for the mutex singleton gate pattern (`CreateMutexW` on a service context) as an execution vector, though the name is currently unknown (anti-analysis-host-gating-001).
- Note the custom string/API obfuscation helpers (`sub_64006890`-style runtime decoding) as a general family fingerprint, though no resolver string is recovered.

### Network-based

- Look for outbound connections from `svchost.exe` to non-standard services using a 0x1D0-byte-fragmented, magic-validated custom protocol (static capability; exact magics/ports not recovered) (network-obfuscated-ip-pool-001).
- Correlation of host-fingerprint telemetry strings returning command/response traffic would discriminate command-and-control; this remains a hypothesis pending a svchost-hosted run (fr-network-obfuscated-ip-pool).

## 11. Mitigations and Triage Notes

- Treat any process hosting this DLL (`svchost.exe` with a `wkssvc` service registration) as suspect; because it cannot run standalone, a standalone execution appears as benign/no-op.
- Apply the established detection story before a real service installation is seen — the sample does not carry its own persistence code visibly, and the installation mechanism is not proven from the DLL alone (fr-loader-wkssvc-forwarder limitations; prohibited claim on persistence).
- Do **not** attribute to a specific malware family or claim ransomware/exfiltration/credential-theft behavior — none is supported (final claim policy prohibited claims).
- The verdict rests on strong structural/capability evidence, not on observed runtime payload behavior; keep confidence appropriately bounded (0.72).

## 12. Classification and Risk

| Field | Value |
|---|---|
| Malware family | Unknown / unconfirmed (no attribution) |
| Malware type | Service DLL proxy / remote-tasking implant (structural/capability interpretation) |
| Risk level | **High** (service-context execution, C2 and process-launch capability designed into the code) |
| Final confidence | 0.72 (verdict), with individual claim confidences per section |

## 13. Priority Follow-up Actions

| Priority | Target | Action | Success criterion |
|---:|---|---|---|
| 5 | svchost-hosted runtime | Install/launch the DLL as a real service under `svchost.exe` in the approved guest (or attach the debugger to the hosting svchost); break on the gate (RVA 0x11672) and worker launch (`CreateThread` in sub_6400F350) | Observe svchost hosting, worker creation, resolved wkssvc forwards; recover plaintext mutex name and IPv4 pool (inv-svchost-hosted-runtime) |
| 4 | wkssvc forwarded export names | Break after each `sub_64006890` decode inside sub_6400F350 (RVA 0xF37B); read the ASCII buffers before `GetProcAddress` | Identify both proxied wkssvc export names and confirm they resolve into legitimate wkssvc.dll (inv-recover-wkssvc-forwarded-names) |
| 4 | IP pool + mutex | In a svchost-hosted run, break after each decode in sub_64010390 and on `CreateMutexW` | Recover every endpoint (incl. duplicates), rotation logic, and the mutex identifier (inv-recover-ip-pool-and-mutex) |
| 3 | C2 task payload / launch | Instrument protocol decode (sub_6400A620, RVA 0xA76F/0xA8A4) and break at the process-launch call (RVA 0x101C3); inspect command line, PID, delete/move-on-reboot | Determine whether C2 delivers behavior strings or a secondary executable payload (inv-c2-task-payload-and-launch) |
| 2 | Host-gate vs DllMain failure | At DllMain entry (0x64012FAA) and host-gate (0x64011672), capture the branch outcome and DllMain return; enable exception breakpoints early | Confirm rejection is deliberate host-gating, not an exception/crash (inv-distinguish-host-gate-vs-dllmain-fail) |
| 2 | Static config/string decode | Complete decode of `sub_64006890` outputs for config/collection blobs in IDA or script it | Recover registry path/value, resource GUID, and any additional endpoint/API strings (inv-static-string-decode-of-config) |

## 14. Final Assessment

### Supported conclusion

- The sample is a **32-bit, svchost-gated PE service DLL** that **proxies `wkssvc.dll` service callbacks** and runs a **long-lived worker thread** containing: an obfuscated IPv4 C2 pool, a connectivity wait, a custom 0x1D0-byte-framed network protocol, host-fingerprinting collection, and a `CreateProcessW`-compatible task-execution path. This supports a **malicious** verdict at 0.72 confidence, best described as a **service-proxy remote-tasking implant** — as a structural/capability interpretation, **not** a runtime-confirmed behavior or family attribution (final claim policy caveat).
- The worker behaviors and all concrete IOCs (**C2 endpoints, mutex name, command payloads**) are **confirmed-present-in-code but not executed**, because the sample refuses to initialize outside `svchost.exe` and the runtime session could not reproduce that host.

### Claims not supported by current evidence

- **No** C2 connection or specific endpoint/domain contact.
- **No** payload execution or process injection of a secondary payload.
- **No** ransomware, exfiltration, or credential-theft behavior.
- **No** specific malware-family attribution.
- **No** installed persistence mechanism.
- **No** confirmed IOC values (IPs, domains, mutex names, hashes).

*(These match the deepdive `prohibited_claims` list and must not be reported as conclusions.)*

### Analyst notes

- The single largest evidence gap is the absence of a `svchost.exe`-hosted runtime run. Until one is performed, the sample's payload-stage capability (what its C2 can actually do) remains **unresolved**, and the cause of the DLL not loading under the helper remains **inferred** as host-gating rather than confirmed (contradiction-host-gate-rejection-direction).
- The strongest, most defensible claims are the **identity, wkssvc-proxy structure, and host-gating** findings (0.88–0.99). The **C2, collection, and process-launch** claims are capability-level with reduced confidence (0.55–0.70).
- The secondary-payload (download-and-run) and hidden anti-analysis hypotheses remain **open/weakened** — not rejected, but unconfirmed (hyp-secondary-payload-via-c2, hyp-decoys-or-anti-analysis-hidden).
- No `04-static-pass2.json` or external-intelligence artifact was supplied; the report is based on 01-prepare-env, 02-static-pass1, 03-unpack, 05-dynamic, and the authoritative 06-deepdive.
