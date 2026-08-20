---
name: hyperagent-summary
description: Convert validated HyperAgent malware-analysis outputs into a compact, non-expert-friendly JSON summary for web UI or dashboard consumption.
---

# Runtime Path Contract

Do not assume the current working directory is the skill directory. Resolve paths as follows:

```bash
HYPERAGENT_SKILLS_ROOT="${HYPERAGENT_SKILLS_ROOT:-<repo>/skill}"
COMMON_ROOT="$HYPERAGENT_SKILLS_ROOT/_hyperagent-common"
SKILL_ROOT="$HYPERAGENT_SKILLS_ROOT/hyperagent-summary"
```

On Windows PowerShell:

```powershell
if (-not $env:HYPERAGENT_SKILLS_ROOT) {
  throw "HYPERAGENT_SKILLS_ROOT must point at the repo skill directory."
}
$CommonRoot = Join-Path $env:HYPERAGENT_SKILLS_ROOT "_hyperagent-common"
$SkillRoot = Join-Path $env:HYPERAGENT_SKILLS_ROOT "hyperagent-summary"
```

All analysis outputs are relative to the current project workspace. Schemas and helper scripts are relative to `HYPERAGENT_SKILLS_ROOT`. Never use a bare helper filename and never depend on `cwd`.

# State / Resume Contract

This stage's id in the pipeline-wide `STATE.json` checkpoint contract is `09-summary`. Use the shared helper for every read or write; never hand-edit `STATE.json`.

```bash
STATE_HELPER="$COMMON_ROOT/scripts/pipeline_state.py"
REPORT_DIR="${HYPERAGENT_ANALYSIS_DIR:-reports/<sha256>}"
STAGE_ID="${HYPERAGENT_STAGE_ID:-09-summary}"
```

- Before starting work, read this stage's entry: `python "$STATE_HELPER" --report-dir "$REPORT_DIR" read --stage-id "$STAGE_ID"`.
- If the entry's `status` is `running`, do not restart from zero: open the file at its recorded `progress_path`, resume from the documented next step, and reuse the work already captured there.
- If the entry's `status` is `completed`, treat the stage as already finished and stop instead of re-running it.
- If `STATE.json` does not exist yet, initialize it: `python "$STATE_HELPER" --report-dir "$REPORT_DIR" init --sample-sha256 "<sha256>" --input-path "<original-sample-path>"`.
- If context usage reaches `>= 80%` before the final artifact is complete: stop immediately, write a concise Markdown progress summary to `$REPORT_DIR/_state/09-summary.progress.md` (what is done, key evidence already reviewed, remaining tasks, exact resume point), then checkpoint: `python "$STATE_HELPER" --report-dir "$REPORT_DIR" checkpoint --stage-id "$STAGE_ID" --progress-path "$REPORT_DIR/_state/09-summary.progress.md" --recommend-reason "Resume 09-summary from the saved summary checkpoint and finish the validated summary JSON."`. Exit without claiming completion.
- Only call `complete` once `09-summary.json` exists, has passed the Mandatory Output Validation below, and there is no follow-up problem left for this stage: `python "$STATE_HELPER" --report-dir "$REPORT_DIR" complete --stage-id "$STAGE_ID" --output-path "<concrete-output-path>" --recommend-reason "All HyperAgent pipeline stages are complete; no additional stage needs to run."`.
- Never mark `completed` merely because the stage ran; it requires a validated final artifact and no outstanding issue for this stage specifically.

# Role

Render a machine-readable, layperson-friendly summary JSON for product or web UI consumption.

This stage is a presentation and simplification layer, not an investigation or verdict stage. Do not create new findings, do not widen claims, and do not override Deepdive.

# Required Inputs

Read available artifacts for the same original SHA256:

- `reports/<sha256>/07-deepdive.json` (required and authoritative)
- `reports/<sha256>/01-prepare-env.json` when present
- `reports/<sha256>/02-static-pass1.json` when present
- `reports/<sha256>/03-unpack.json` when present
- `reports/<sha256>/04-static-pass2.json` when present
- `reports/<sha256>/05-dynamic.json` when present
- `reports/<sha256>/06-intel.json` when present
- `reports/<sha256>/08-report.md` when present, but only for wording alignment

Treat `07-deepdive.json` as the source of truth for verdict, confidence, claim boundaries, unresolved points, and defender follow-up. `08-report.md` may help with plain-language phrasing, but it must never introduce or strengthen claims beyond Deepdive.

If `07-deepdive.json` is missing or invalid, still write a structured `blocked` or `failed` summary whenever the sample identity can be determined. Do not invent replacement findings.
- Keep unresolved items explicit in `limitations` and `recommended_actions`; do not collapse overlay/classification or contradiction follow-ups into generic prose.
- Use the same blocker vocabulary as Deepdive and Report so unresolved items remain searchable across stages.

# Output Contract

Derive or reuse the original sample SHA256 and write exactly:

`reports/<sha256>/09-summary.json`

Do not emit Markdown. The output must validate against `schema.json` in this directory. Create the report directory when needed.

# Tasks

## 1. Identity and authority check

Before writing the summary:

- confirm that all consulted upstream artifacts refer to the same original SHA256;
- extract stable sample metadata such as file name, absolute path, architecture, and packing/protection when available;
- record every upstream artifact consulted;
- reject mismatched or ambiguous inputs rather than silently merging them.

When multiple stages disagree, Deepdive wins.

## 2. Build the executive summary card

Produce a short, non-expert-friendly summary from authoritative inputs:

- mirror `verdict` and numeric `confidence` from Deepdive exactly;
- assign a conservative `confidence_label` consistent with the numeric confidence;
- assign a conservative `risk_level` only when supported by the reconciled findings; otherwise use `unknown`;
- write one short sentence for the headline summary;
- write one short paragraph for the plain-language assessment.

Do not turn technical uncertainty into certainty just to make the summary sound cleaner.

## 3. Split findings into explicit buckets

Map findings into three clear UI buckets:

- `confirmed_findings`
- `findings_with_caveats`
- `not_supported_claims`

Use Deepdive claim policy and finding review disposition as the decision boundary.

Rules:

- items derived from allowed or clearly confirmed findings belong in `confirmed_findings`;
- items that remain unresolved, partial, or caveated belong in `findings_with_caveats`;
- prohibited, rejected, or contradicted claims belong in `not_supported_claims`.

Keep each item short, concrete, and safe for non-experts.

## 4. Present classification and confirmed IOCs safely

For `classification`:

- keep family attribution unconfirmed unless Deepdive clearly supports it;
- do not promote public-label-only family names into confirmed truth;
- summarize malware type or overall behavior conservatively.

For `confirmed_iocs`:

- include only locally observed or Deepdive-approved indicators;
- group them into `network`, `host`, and `persistence`;
- keep public-only or external-only indicators out of the confirmed IOC sets.

## 5. Recommend actions and preserve limitations

Use Deepdive investigation targets, remaining decision points, and report-safe conclusions to derive short defender-facing follow-up actions.

Also preserve explicit limitations in plain language so the UI can show uncertainty without re-reading technical JSON.

# Rules

- Do not create a new verdict.
- Do not change Deepdive confidence.
- Do not create new findings or IOCs.
- Do not present public-only enrichment as locally confirmed behavior.
- Do not let `08-report.md` override, widen, or strengthen `07-deepdive.json`.
- Do not hide caveats or unsupported claims for the sake of readability.
- Keep wording short, direct, and safe for a non-expert audience.
- Use empty arrays for empty collections; do not replace them with prose.

# Strict JSON Rules

The stage output is a machine-readable contract consumed by UI code.

- Output exactly one JSON document to the required path.
- Do not create Markdown in this stage.
- The JSON must validate against `schema.json` in this skill directory.
- Never rename, remove, or add top-level keys not permitted by the schema.
- Use `null` only for unknown scalar values. Use `[]` for empty collections.
- Confidence values must be numbers from `0.0` to `1.0` when the schema requires them.
- Status and enum values must exactly match the values allowed by the schema.
- `source_refs` entries must point to real upstream stage names, claim-policy locations, or finding IDs already present in the consulted artifacts.
- Paths, hashes, and stage references must be concrete values or `null`; never leave angle-bracket placeholders in final output.
- Before finishing, parse the generated file and validate it. If parsing or validation fails, regenerate it.

# Mandatory Output Validation

After writing `09-summary.json`, validate the concrete output path with the shared validator:

```bash
python "$COMMON_ROOT/scripts/validate_output.py" \
  "$SKILL_ROOT/schema.json" \
  "<concrete-output-path>.json"
```

PowerShell:

```powershell
python `
  (Join-Path $CommonRoot "scripts\validate_output.py") `
  (Join-Path $SkillRoot "schema.json") `
  "<concrete-output-path>.json"
```

The placeholder must be replaced before execution. If validation fails, read the validator error, repair only the invalid fields, write the file again, and rerun validation. Do not complete this stage until the validator prints `VALID`.
