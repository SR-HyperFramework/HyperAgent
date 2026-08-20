---
name: hyperagent-static
description: Perform pass-aware static analysis and emit strict JSON for either the original sample or a validated recovered artifact.
---

> Defensive lab scope: this phase exists to understand malware behavior, extract evidence, and improve detection. Do not execute recovered artifacts on the host and do not use findings to operationalize offensive tradecraft.

# Runtime Path Contract

Do not assume the current working directory is the skill directory. Resolve paths as follows:

```bash
HYPERAGENT_SKILLS_ROOT="${HYPERAGENT_SKILLS_ROOT:-<repo>/skill}"
COMMON_ROOT="$HYPERAGENT_SKILLS_ROOT/_hyperagent-common"
SKILL_ROOT="$HYPERAGENT_SKILLS_ROOT/hyperagent-static"
```

On Windows PowerShell:

```powershell
if (-not $env:HYPERAGENT_SKILLS_ROOT) {
  throw "HYPERAGENT_SKILLS_ROOT must point at the repo skill directory."
}
$CommonRoot = Join-Path $env:HYPERAGENT_SKILLS_ROOT "_hyperagent-common"
$SkillRoot = Join-Path $env:HYPERAGENT_SKILLS_ROOT "hyperagent-static"
```

All analysis outputs are relative to the current project workspace. Schemas and helper scripts are relative to `HYPERAGENT_SKILLS_ROOT`. Never use a bare helper filename and never depend on `cwd`.

# State / Resume Contract

This skill runs twice in the pipeline. Resolve your own stage id, report directory, schema path, and default output path from the launcher prompt; never assume them from the skill name alone.

```text
Report directory: <provided by launcher>
STATE.json path: <provided by launcher>
Current stage_id: 02-static-pass1 or 04-static-pass2
Stage schema path: <provided by launcher>
Default stage output path: <provided by launcher>
```

- Before starting work, inspect the stage entry from the launcher-provided state path and use `$STAGE_ID` (not a hardcoded `02-static-pass1` or `04-static-pass2`) so Pass 1 and Pass 2 never read each other's entry.
- If the entry's `status` is `running`, do not restart from zero: open the file at its recorded `progress_path`, resume from the documented next step, and reuse the work already captured there.
- If the entry's `status` is `completed`, treat this pass as already finished and stop instead of re-running it.
- Do not run helper scripts or write `STATE.json` directly in the v4 launcher. Your job is to write this pass's required artifact (`02-static-pass1.json` or `04-static-pass2.json`, matching `$STAGE_ID`) and validate it with `validate_json_output`; the launcher records checkpoint/completion in `STATE.json` after your turn.
- If context usage reaches `>= 80%` before the final artifact is complete: stop immediately after writing a concise Markdown progress summary to `$REPORT_DIR/_state/${STAGE_ID}.progress.md` (what is done, key evidence already reviewed, remaining tasks, exact resume point). Exit without claiming completion; the launcher records the checkpoint.
- A valid `02-static-pass1.json` or `04-static-pass2.json` with `status: "blocked"`, `status: "partial"`, or `status: "not_needed"` is still a completed pipeline artifact when it truthfully records the condition and passes schema validation.
- Never treat the stage as complete merely because analysis ran; completion requires a validated final artifact and no outstanding issue for this specific pass.

# Role

Build a static execution map in one of two explicit modes:

- **Pass 1 — Original sample triage:** analyze the original submitted sample, identify packing/self-decoding indicators, map the loader path, and produce a runtime/unpack plan.
- **Pass 2 — Recovered artifact analysis:** read the unpack-stage handoff, analyze the recommended validated artifact, compare it with Pass 1, and expose the post-unpack execution logic for downstream dynamic validation.

Never silently mix the two modes. State the selected pass at the beginning of the report.

# Pass Selection

## Select Pass 1 when

- no unpack report is supplied or named for the run; or
- the target is the original sample; or
- `03-unpack.json` reports `status: "not_needed"`, `status: "blocked"`, or no usable recovered artifact.

## Select Pass 2 when all are true

- `reports/<sha256>/03-unpack.json` is explicitly supplied or named;
- its **Static Pass-2 Handoff** identifies a recommended artifact;
- that artifact exists and its SHA256 matches the handoff record;
- validation is `Success` or `Partial` with a clearly documented analyzable artifact.

If Pass 2 is requested but any requirement is missing, write a blocked Pass-2 report with the exact reason. Do not fall back silently to Pass 1.

# Required Inputs

## Pass 1

At minimum:
- original sample path

Optional:
- `reports/<sha256>/01-prepare-env.json`

## Pass 2

Required:
- `reports/<sha256>/02-static-pass1.json`
- `reports/<sha256>/03-unpack.json`
- the recommended artifact path from the unpack report

The artifact path, artifact SHA256, candidate entry/OEP, runtime base, repair limitations, and questions for re-analysis must be taken from the unpack report rather than guessed.

# Output Contract

Derive or reuse the original sample SHA256 as the report-directory key.

- Pass 1 output: `reports/<sha256>/02-static-pass1.json` with `stage` exactly `static-pass1`.
- Pass 2 output: `reports/<sha256>/04-static-pass2.json` with `stage` exactly `static-pass2`.

Do not emit Markdown. The selected output must validate against the corresponding branch in `schema.json`. Retain both original and recovered artifact identities in Pass 2.

# Subagent Delegation for Heavy Code Reading

Common Tasks 2 through 5 below (Fingerprint, Execution Graph Mapping, Anti-Analysis and Protection, Decryption/Configuration/Payload Analysis) routinely pull large volumes of decompiled code, disassembly, and call-graph data through the IDA Pro MCP tools. Reading all of that directly in this session bloats context the rest of the pipeline still needs. Delegate this reading and analysis work to one or more subagents instead of doing it directly here.

## When to delegate

- Default: spawn one subagent per selected pass to run Common Tasks 2-5 end to end (Fingerprint through Decryption/Configuration/Payload Analysis) for the current target.
- Split further into one subagent per task group (Fingerprint + Execution Graph Mapping as one; Anti-Analysis + Decryption/Configuration/Payload as another) when the binary is large, has many candidate functions, or the first subagent's result is incomplete.
- Do not delegate Task 1 (Input and Provenance Validation), Task 6 (Pass Comparison), Task 7 (Breakpoint and Dynamic Validation Planning), or the Pass-2 Decision Outcome — those depend on cross-pass context and the final schema shape, and stay in this session.

## How to delegate

- Use the Agent tool with `subagent_type: general-purpose` (or `Explore` for a read-only survey-only sub-step).
- Give the subagent: the concrete target path, the selected pass, the exact IDA Pro MCP workflow from the relevant task(s) below, and any upstream report paths it needs to read (e.g. `03-unpack.json` handoff fields for Pass 2).
- Tell the subagent explicitly to return a compact structured result only: findings (with id, evidence, confidence), artifacts, candidate execution-graph summary, anti-analysis mechanisms, decrypt/config findings, and investigation targets — never raw decompiled function bodies, full disassembly listings, or full call-graph dumps. Those must stay inside the subagent's own context.
- Perform JSON assembly, pass comparison, and the final schema-validated write in this session after receiving the subagent's structured result(s) — never delegate the output contract itself.
- If a subagent's result leaves a required question unanswered, spawn a narrower follow-up subagent rather than re-reading raw IDA output directly in this session.

# Common Tasks

## 1. Input and Provenance Validation

Before analysis:
- identify the selected pass;
- verify target path and SHA256;
- record every upstream report consulted;
- for Pass 2, verify the artifact hash against `03-unpack.json`;
- for Pass 2, record recovery status, recovery round, artifact type, candidate entry/OEP, runtime/image base, and repair limitations.

Do not analyze an artifact whose identity cannot be tied back to the unpack report.

## 2. Fingerprint (delegate to subagent)

Start by invoking `/ida-pro:idapython` with the selected target path, then use IDA Pro plugin tools:
- `survey_binary`
- `server_warmup`
- `imports`
- `find_regex`
- `get_bytes` when exact constants or hashes are required

Collect:
- hashes
- image base and entry point
- architecture and file type
- section/range layout
- imports and strings
- packer/obfuscation indicators

For Pass 2, also assess:
- whether the artifact is a full PE, mapped module, PE-like region, or raw code;
- whether IDA load parameters need to use the recovered runtime base;
- whether the candidate entry from the unpack report maps coherently into the artifact;
- whether packing/self-decoding indicators decreased.

## 3. Execution Graph Mapping (delegate to subagent)

Use:
- `analyze_batch` for entry point, dispatchers, loader functions, and candidate payload functions
- `callgraph` for bounded call relationships
- `xrefs_to` for suspicious strings, constants, runtime API tables, or decoded data
- `decompile` for focused rereads

Identify:
- real execution path
- loader/unpack stub boundaries
- shellcode or payload transfer points
- configuration/IOC parsing
- capability-relevant routines
- UI or challenge logic that may explain suspicious code without malware behavior

### Pass-2-specific mapping

Begin from the unpack handoff:
1. locate the candidate OEP or validated stage handoff;
2. determine whether it is code, a helper, a trampoline, another unpack stub, or a real payload entry;
3. map forward into stable post-unpack logic;
4. map backward only as needed to explain the handoff;
5. identify newly visible functions, imports, strings, and capabilities absent from Pass 1.

Do not redo the original loader analysis unless it is necessary to reconcile the handoff.

## 4. Anti-Analysis and Protection (delegate to subagent)

Identify:
- anti-debugging
- anti-VM
- timing checks
- sandbox checks
- integrity checks
- exception-driven control flow

For Pass 2, distinguish:
- checks belonging to the original unpack stub;
- checks still present in the recovered payload;
- checks that were bypassed or forced during recovery.

Document whether each mechanism is confirmed reachable from the post-unpack path.

## 5. Decryption, Configuration, and Payload Analysis (delegate to subagent)

Locate:
- residual decrypt/decompress routines
- configuration decoders
- embedded keys/constants
- payload buffers
- validation digests
- runtime API tables or reconstructed imports

For Pass 2, prioritize the questions listed in `03-unpack.json` under **Static Pass-2 Handoff**.
If the recovered artifact is still packed or reveals a later-stage loader, mark `Additional unpack round recommended` and identify the next recovery target.

## 6. Pass Comparison

Pass 1 records the baseline.
Pass 2 must compare against `02-static-pass1.json` using at least:

| Metric | Pass 1 | Pass 2 | Interpretation |
|---|---:|---:|---|
| Meaningful strings | | | |
| Imports / resolved APIs | | | |
| Recognized functions | | | |
| Capability findings | | | |
| Executable code coverage | | | |
| Packing/self-decoding indicators | | | |

Also classify Pass-1 findings as:
- `Confirmed after unpack`
- `Refined after unpack`
- `Rejected after unpack`
- `Still unresolved`

Do not claim improvement unless the comparison supplies evidence.

## 7. Breakpoint and Dynamic Validation Planning

### Pass 1

Prepare runtime targets for unpack/recovery:
- gate return
- allocation/mapping
- protection change
- decode completion
- relocation/import fixup completion
- candidate handoff/OEP

### Pass 2

Prepare runtime targets for behavior validation:
- validated/candidate payload entry
- configuration decode completion
- process, file, registry, network, persistence, and injection routines that are reachable from the post-unpack graph
- unresolved handoff or next unpack stage

Record each breakpoint with:
- RVA
- expected rebased address rule
- source artifact/module
- expected evidence
- success/failure interpretation

# Pass-2 Decision Outcomes

End Pass 2 with exactly one outcome:

- `Recovered payload analyzable`
- `Recovered loader requires another unpack round`
- `Artifact useful but incomplete`
- `Candidate handoff rejected`
- `Pass 2 blocked`

# Rules

- Do not execute the sample or recovered artifact.
- Pass 1 may run independently.
- Pass 2 must consume `02-static-pass1.json`, `03-unpack.json`, and the recommended artifact.
- Do not choose a different recovered artifact unless the unpack report lists it as an accepted alternative; document the choice.
- Do not treat a raw memory region as a reconstructed PE.
- Do not invent imports, entry points, or image bases.
- Keep original-sample evidence separate from recovered-artifact evidence.
- If upstream reports conflict, preserve the conflict for deepdive/reconciliation instead of forcing a conclusion.

# Strict JSON Rules

The stage output is a machine-readable contract consumed by downstream stages.

- Output exactly one JSON document to the required path.
- Do not create a Markdown report in this stage.
- The JSON must validate against `schema.json` in this skill directory.
- Never rename, remove, or add top-level keys not permitted by the schema.
- Use `null` only for unknown scalar values. Use `[]` for unknown or empty collections.
- Confidence values must be numbers from `0.0` to `1.0`.
- Status and enum values must exactly match the values allowed by the schema.
- Every finding must have a unique stable `id`, at least one provenance source, and at least one evidence item unless its status is `unknown`.
- Evidence must describe what was observed and where it came from; never use a conclusion as its own evidence.
- Paths must be concrete paths or `null`; never leave angle-bracket placeholders in final output.
- Preserve unsupported or conflicting claims as explicit uncertainty rather than forcing a conclusion.
- Before finishing, parse the generated file and validate it. If parsing or validation fails, regenerate it.

# Mandatory Output Validation

After writing `02-static-pass1.json` or `04-static-pass2.json`, validate it with the native `validate_json_output` tool using the resolved schema path and the concrete output path already provided by the runtime prompt.

Do not write temporary host-side helper scripts just to call the validator. Do not rediscover schema or validator locations manually. If validation fails, inspect the returned error, repair only the invalid fields, write the JSON again, and rerun `validate_json_output` until it returns `VALID`.

Do not complete this pass or invoke the next stage until the tool returns `VALID`.
