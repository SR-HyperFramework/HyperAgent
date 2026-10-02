---
name: hyperagent-report
description: Render the final defender-focused Markdown report exclusively from validated HyperAgent JSON stage outputs.
---

# Runtime Path Contract

Do not assume the current working directory is the skill directory. Resolve paths as follows:

```bash
HYPERAGENT_SKILLS_ROOT="${HYPERAGENT_SKILLS_ROOT:-<repo>/skill}"
COMMON_ROOT="$HYPERAGENT_SKILLS_ROOT/_hyperagent-common"
SKILL_ROOT="$HYPERAGENT_SKILLS_ROOT/hyperagent-report"
```

On Windows PowerShell:

```powershell
if (-not $env:HYPERAGENT_SKILLS_ROOT) {
  throw "HYPERAGENT_SKILLS_ROOT must point at the repo skill directory."
}
$CommonRoot = Join-Path $env:HYPERAGENT_SKILLS_ROOT "_hyperagent-common"
$SkillRoot = Join-Path $env:HYPERAGENT_SKILLS_ROOT "hyperagent-report"
```

All analysis outputs are relative to the current project workspace. Schemas and helper scripts are relative to `HYPERAGENT_SKILLS_ROOT`. Never use a bare helper filename and never depend on `cwd`.

# State / Resume Contract

This stage's id in the pipeline-wide `STATE.json` checkpoint contract is `08-report`. Use the shared helper for every read or write; never hand-edit `STATE.json`.

```bash
STATE_HELPER="$COMMON_ROOT/scripts/pipeline_state.py"
REPORT_DIR="${HYPERAGENT_ANALYSIS_DIR:-reports/<sha256>}"
STAGE_ID="${HYPERAGENT_STAGE_ID:-08-report}"
```

- Before starting work, read this stage's entry: `python "$STATE_HELPER" --report-dir "$REPORT_DIR" read --stage-id "$STAGE_ID"`.
- If the entry's `status` is `running`, do not restart from zero: open the file at its recorded `progress_path`, resume from the documented next step, and reuse the work already captured there.
- If the entry's `status` is `completed`, treat the stage as already finished and stop instead of re-running it.
- If `STATE.json` does not exist yet, initialize it: `python "$STATE_HELPER" --report-dir "$REPORT_DIR" init --sample-sha256 "<sha256>" --input-path "<original-sample-path>"`.
- If context usage reaches `>= 80%` before the final artifact is complete: stop immediately, write a concise Markdown progress summary to `$REPORT_DIR/_state/08-report.progress.md` (what is done, key evidence already reviewed, remaining tasks, exact resume point), then checkpoint: `python "$STATE_HELPER" --report-dir "$REPORT_DIR" checkpoint --stage-id "$STAGE_ID" --progress-path "$REPORT_DIR/_state/08-report.progress.md" --recommend-reason "Resume 08-report from the saved report-drafting checkpoint and finish the validated final Markdown report."`. Exit without claiming completion.
- Only call `complete` once `08-report.md` exists, has passed the Pipeline Validation Gate below, and there is no follow-up problem left for this stage: `python "$STATE_HELPER" --report-dir "$REPORT_DIR" complete --stage-id "$STAGE_ID" --output-path "<concrete-output-path>" --recommend-reason "The final Markdown report is rendered; run 09-summary next to build the compact summary JSON."`.
- Never mark `completed` merely because the stage ran; it requires a validated final artifact and no outstanding issue for this stage specifically.

# Role

Render a clear final Markdown report. This is the only stage permitted to produce a Markdown analysis artifact.

You are a presentation and synthesis layer, not an investigation layer. Do not call analysis tools and do not introduce new findings.

# Required Inputs

Build and use a compact report-context artifact for the same original SHA256:

1. Validate the upstream pipeline artifacts that are present:
   ```bash
   python "$COMMON_ROOT/scripts/validate_pipeline.py" "reports/<sha256>"
   ```
2. Call `build_report_context` with the run's `reports/<sha256>` directory.
3. Read the generated compact context file (default: `reports/<sha256>/08-report.context.md`) and render the final Markdown report from that compact briefing.

The compact report context is built from the validated upstream JSON artifacts for:

- `reports/<sha256>/01-prepare-env.json`
- `reports/<sha256>/02-static-pass1.json`
- `reports/<sha256>/03-unpack.json` when present
- `reports/<sha256>/04-static-pass2.json` when present
- `reports/<sha256>/05-dynamic.json`
- `reports/<sha256>/07-deepdive.json` (required and authoritative)
- `reports/<sha256>/06-intel.json` only as enrichment when present; it must not widen claims beyond what Deepdive already carried forward

Do not read large upstream JSON artifacts directly unless the compact context explicitly says a required detail is still missing. Reject or clearly flag invalid inputs. Use `07-deepdive.json.final_claim_policy` as the final boundary for claims.

`06-intel.json` is enrichment-only. Treat it as optional public-source context already filtered through Deepdive and the compact report context; do not pull raw intel JSON into the conversation by default.

# Preferred Workflow

- Validate upstream stage files.
- Build compact report context with `build_report_context`.
- Read `08-report.context.md`.
- Write `08-report.md` from that compact context and the `template.md` structure.
- If a required detail is absent from the compact context, state the limitation in the final report instead of re-reading raw large JSON files.

The report stage is a presentation layer, not a raw artifact exploration stage.

Reject or clearly flag invalid JSON inputs. Use `07-deepdive.json.final_claim_policy` as the final boundary for claims.

# Output Contract

Write exactly:

`reports/<sha256>/08-report.md`

Use the structure in `template.md`. Do not create new JSON findings. Do not alter upstream JSON.

# Claim Precedence

1. Deepdive resolutions and final claim policy.
2. Direct dynamic observations.
3. Validated recovered-artifact and Static Pass-2 evidence.
4. Static Pass-1 evidence.
5. Public-source corroboration or conflict already reconciled by Deepdive, clearly attributed when surfaced.

A newer stage does not automatically override stronger evidence; follow Deepdive resolution.

# Tasks

- Present sample identity and final verdict.
- Explain key behavior in accessible language while preserving technical precision.
- Separate observed, inferred, unconfirmed, and rejected behavior.
- Summarize unpacking and recovered artifacts when relevant.
- Include only IOCs supported by evidence and permitted by the final claim policy.
- Include detection opportunities, mitigations, limitations, and high-priority next actions.
- When Deepdive carries forward public-source corroboration or conflict, keep that attribution explicit without presenting it as direct local observation.
- Preserve evidence provenance in concise source annotations such as finding IDs or stage names.

# Rules

- Never invent a fact, IOC, family, capability, confidence, or causal explanation.
- Never upgrade `not observed` to `absent`.
- Never present an imported or reachable API as executed behavior.
- Claims listed in `prohibited_claims` must not appear as conclusions.
- Claims listed in `caveated_claims` must retain their caveat.
- Do not re-upgrade a claim beyond Deepdive because a public label or third-party sandbox phrased it more strongly.
- If Deepdive is missing or invalid, write an incomplete-report notice instead of producing an authoritative verdict.
- Add a concise `Open Follow-ups / Blockers` section when Deepdive preserves unresolved items, and list each item's priority, cause, and closure criterion instead of burying it in prose.
- Keep follow-up wording aligned with Deepdive `recommended_actions` so overlay/classification and contradiction items remain visible to later runs.
- Markdown is for humans; JSON remains the machine-readable source of truth.

# Pipeline Validation Gate

Before rendering the final Markdown report, validate all upstream JSON files that are present:

```bash
python "$COMMON_ROOT/scripts/validate_pipeline.py" "reports/<sha256>"
```

Do not render from an invalid stage file. If a required upstream artifact is missing or invalid, state the limitation in the final report rather than inventing replacement findings. `hyperagent-report` is the only stage permitted to write Markdown.
