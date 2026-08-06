---
type: reference
title: Skills System and Orchestration
description: Claude Code skills architecture, SKILL.md orchestration, compatibility model, and skill tree hierarchy.
tags: [skills, orchestration, system]
---

# Skills System and Orchestration

## Overview

HyperAgent's analysis pipeline is powered by **Claude Code skills**—Claude-aware directories with structured orchestration, schema validation, and failure handling. Each of the 9 stages is backed by exactly one skill.

## Skill Structure

Each skill follows a standard directory layout:

```
/skill/backup/hyperagent-malware-analyze/v3/hyperagent-{name}/
├── SKILL.md                  # Orchestration file (main entrypoint)
├── schema.json               # Output schema validation
├── ENVIRONMENT.md            # External tool prerequisites
├── template.json             # Output structure template
├── example.json              # Example valid output
├── {substeps}/
│   ├── identify.md          # Sub-workflow (if applicable)
│   ├── agent-invoke.md      # Sub-workflow
│   └── ...
└── playbooks/               # Additional playbook files
```

## SKILL.md: The Orchestration File

SKILL.md is the primary interface to each skill. It defines:

1. **Workflow Steps**: What the skill does, in order
2. **Playbook Integration**: Calls to sub-tasks and MCP servers
3. **Failure Handling**: Error detection and recovery
4. **State Management**: Reading/writing STATE.json
5. **Output Validation**: Generating schema-compliant artifacts

### Example SKILL.md Structure

```markdown
# hyperagent-static

Perform static file analysis and route to appropriate coarse agent.

## Workflow

### Phase 1: Identify
- Run DIE on sample
- Extract file class, packer, compiler
- Set initial artifact record

### Phase 2: Route
- Determine file type (NATIVE, DOTNET, PYTHON_SCRIPT)
- Select appropriate coarse agent
- Emit routing decision

### Phase 3: Agent Execution
- Invoke coarse agent (NativeAgent, ScriptAgent, or DotNetAgent)
- Collect findings
- Consolidate artifacts

### Phase 4: Next-Stage Recommendation
- Evaluate findings
- Recommend unpack (if packing detected)
- Recommend dynamic (if high-value behavior indicators)
- Emit recommend_next_stage

## Error Handling

### Packing Detection Failure
- Tag: `[STATIC-PARSE-ERR]`
- Action: Assume no packing, continue

### Agent Timeout
- Tag: `[AGENT-TIMEOUT-ERR]`
- Action: Retry with timeout extension, or skip agent

### Findings Consolidation Failure
- Tag: `[FINDINGS-MERGE-ERR]`
- Action: Keep separate findings, note conflict

## State Management

- Read: HYPERAGENT_STATE_PATH (stage index, prior findings)
- Write: HYPERAGENT_STAGE_OUTPUT_PATH ({STAGE_ID}.json)
- Update: recommend_next_stage in output artifact
```

## The 9 Pipeline Skills

| Stage | Skill | Purpose | Input | Output |
|-------|-------|---------|-------|--------|
| 01 | hyperagent-prepare-env | Environment readiness | STATE.json | 01-prepare-env.json |
| 02 | hyperagent-static | Identify, route, initial analysis | Sample | 02-static-pass1.json |
| 03 | hyperagent-unpack | Extract payloads | Pass1 findings | 03-unpack.json |
| 04 | hyperagent-static | Analyze unpacked artifacts | Unpacked artifacts | 04-static-pass2.json |
| 05 | hyperagent-dynamic | Runtime behavior capture | Artifacts | 05-dynamic.json |
| 06 | hyperagent-intel | Reputation enrichment | Artifacts, findings | 06-intel.json |
| 07 | hyperagent-deepdive | Evidence reconciliation | All prior findings | 07-deepdive.json |
| 08 | hyperagent-report | Markdown synthesis | All findings | 08-report.md |
| 09 | hyperagent-summary | Verdict assignment | Report, findings | 09-summary.json |

## Backward Compatibility Model

The skill system maintains backward compatibility through an **alias layer**:

### Top-Level Dispatcher

**Skill**: `/hyperagent-malware-analyze`  
**Role**: Stable public entrypoint; acts as dispatcher

```bash
claude -p '/hyperagent-malware-analyze @sample.exe'
# This skill invokes the appropriate stage skills (01-09)
# and manages the overall pipeline
```

**Compatibility Guarantee**: Legacy callers that invoke `/hyperagent-malware-analyze` continue to work unchanged.

### Specialist Skills Layer

Underlying specialist skills (`hyperagent-prepare-env`, `hyperagent-static`, etc.) are implementation details.

The dispatcher handles:
- Stage sequencing
- State management
- Error recovery
- Backward-compatible response projection

## Skill Invocation

### Via Claude Code CLI

```bash
claude -p '/{skill_name} @{input_path}' < context_stdin
```

**Example**:
```bash
claude -p '/hyperagent-static @/path/to/sample.exe' \
  --mcp-server ida-pro-mcp \
  --dangerously-skip-permissions < stage_context.json
```

### Environment Variables

Orchestrator injects:
- `HYPERAGENT_ANALYSIS_DIR`: Reports directory
- `HYPERAGENT_STATE_PATH`: Current STATE.json
- `HYPERAGENT_STAGE_ID`: Current stage (01-prepare-env, etc.)
- `HYPERAGENT_STAGE_OUTPUT_PATH`: Expected output path

### MCP Server Integration

Skills request MCP servers as needed:

```bash
# Static analysis requires IDA Pro disassembly
claude -p '/hyperagent-static ...' --mcp-server ida-pro-mcp

# Dynamic analysis requires x64dbg debugger
claude -p '/hyperagent-dynamic ...' --mcp-server x64dbg-mcp
```

**MCP Servers Used**:
- `ida-pro-mcp`: Binary disassembly and analysis
- `x64dbg-mcp`: Debugger control and memory inspection
- `virustotal-mcp` (planned): External reputation queries

## Skill Tree Hierarchy

The full skill tree under `/skill/backup/hyperagent-malware-analyze/v3/`:

```
hyperagent-malware-analyze/           (top-level dispatcher)
├── hyperagent-prepare-env/           (01-prepare-env stage)
├── hyperagent-static/                (02, 04 stages)
├── hyperagent-unpack/                (03-unpack stage)
├── hyperagent-dynamic/               (05-dynamic stage)
├── hyperagent-intel/                 (06-intel stage)
├── hyperagent-deepdive/              (07-deepdive stage)
├── hyperagent-report/                (08-report stage)
├── hyperagent-summary/               (09-summary stage)
├── hyperagent-progress/              (operator tool; not a stage)
└── _hyperagent-common/               (shared utilities)
    ├── scripts/
    │   ├── pipeline_state.py         (STATE.json contract)
    │   ├── validate_output.py        (schema validation)
    │   ├── validate_pipeline.py      (end-to-end validation)
    │   └── ...
    └── schemas/
        ├── state.schema.json         (STATE.json schema)
        ├── 01-prepare-env.schema.json
        ├── 02-static-pass1.schema.json
        ├── ...
        └── 09-summary.schema.json
```

## Schema Validation

Each skill's output is validated against `schema.json`:

```python
# In orchestrator (claude_spawn.py)
schema = load_json(f"~/.claude/skills/{skill_name}/schema.json")
artifact = load_json(stage_output_path)

if not validate_json_schema(artifact, schema):
    raise ValidationError(f"Stage {stage_id} artifact invalid")
```

**Schema.json Format** (JSON Schema standard):
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["status", "findings"],
  "properties": {
    "status": {
      "type": "string",
      "enum": ["success", "failed", "partial"]
    },
    "findings": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["finding_id", "category"],
        "properties": {
          "finding_id": { "type": "string" },
          "category": { "type": "string" },
          "severity": { "type": "string", "enum": ["critical", "high", "medium", "low", "info"] }
        }
      }
    }
  }
}
```

## Error Tagging Convention

Skills use error tags in output to communicate failure modes:

| Tag | Meaning | Example Stage | Recovery |
|-----|---------|---------------|----------|
| `[STATIC-ENV-ERR]` | Static analysis environment issue | 02, 04 | Skip stage or retry |
| `[DYN-ENV-ERR]` | Dynamic analysis environment missing | 05 | Skip to intel (06) |
| `[PACKING-ERR]` | Unpacking failed | 03 | Mark as failed, investigate |
| `[TIMEOUT-ERR]` | Stage exceeded context limit | Any | Checkpoint and resume |
| `[SCHEMA-ERR]` | Output doesn't match schema | Any | Retry or fail |

## Skill Extensibility

### Adding a New Skill

1. Create directory: `~/.claude/skills/hyperagent-{name}/`
2. Write SKILL.md with workflow definition
3. Write schema.json for output validation
4. Register in pipeline_state.py (if adding new stage)
5. Test with validate_pipeline.py

### Example: Adding IOC Extraction Specialist

```bash
mkdir ~/.claude/skills/hyperagent-ioc-expert/
cat > ~/.claude/skills/hyperagent-ioc-expert/SKILL.md << EOF
# hyperagent-ioc-expert

Extract and normalize indicators of compromise from findings.

## Workflow

### Phase 1: Parse Findings
- Read all prior findings
- Identify IOC-bearing fields (domains, IPs, URLs, file hashes)

### Phase 2: Normalize
- Validate IP addresses (CIDR, geolocation)
- Resolve domains (DNS, subdomain structure)
- Classify URLs (phishing, malware delivery, C&C)

### Phase 3: Consolidate
- Merge duplicates
- Rank by severity
- Add context (source finding, occurrence count)

## Output
- IOC list with normalization metadata
- Confidence scores
- Source references
EOF

cat > ~/.claude/skills/hyperagent-ioc-expert/schema.json << EOF
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["iocs"],
  "properties": {
    "iocs": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["type", "value", "confidence"],
        "properties": {
          "type": { "type": "string", "enum": ["ip", "domain", "url", "hash"] },
          "value": { "type": "string" },
          "confidence": { "type": "number", "minimum": 0, "maximum": 1 }
        }
      }
    }
  }
}
EOF
```

## Operator Entry Points

### Main Dispatcher

```bash
claude -p '/hyperagent-malware-analyze @sample.exe'
```

Automatically sequences stages 01-09.

### Pipeline Controller

```bash
claude -p '/hyperagent-progress'
```

Discover runs, classify status, resume interrupted analyses.

## Related Documentation

- [Pipeline Details](../architecture/pipeline.md) — Stage-by-stage breakdown
- [Launcher](../orchestration/launcher.md) — Stage invocation via CLI
<!-- openwiki: broken internal link [./stages/01-prepare-env.md] file "./stages/01-prepare-env.md" does not exist. Fix the href or restore the target, then delete this comment. -->
- [Stage 01: Prepare Env](./stages/01-prepare-env.md) — Environment validation
- [Stage 02/04: Static](./stages/02-04-static-analysis.md) — File analysis and routing
- [Stage 03: Unpack](./stages/02-04-static-analysis.md) — Payload extraction
- [Stage 05: Dynamic](./stages/05-dynamic-analysis.md) — Behavior capture
<!-- openwiki: broken internal link [./stages/06-intel.md] file "./stages/06-intel.md" does not exist. Fix the href or restore the target, then delete this comment. -->
- [Stage 06: Intel](./stages/06-intel.md) — Reputation enrichment
<!-- openwiki: broken internal link [./stages/07-deepdive.md] file "./stages/07-deepdive.md" does not exist. Fix the href or restore the target, then delete this comment. -->
- [Stage 07: Deepdive](./stages/07-deepdive.md) — Evidence reconciliation
<!-- openwiki: broken internal link [./stages/08-report.md] file "./stages/08-report.md" does not exist. Fix the href or restore the target, then delete this comment. -->
- [Stage 08: Report](./stages/08-report.md) — Report synthesis
<!-- openwiki: broken internal link [./stages/09-summary.md] file "./stages/09-summary.md" does not exist. Fix the href or restore the target, then delete this comment. -->
- [Stage 09: Summary](./stages/09-summary.md) — Verdict assignment

