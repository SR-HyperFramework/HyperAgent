---
type: "Reference"
title: "HyperAgent Wiki Coverage Analysis"
openwiki_generated: true
---

# HyperAgent Wiki Coverage Analysis

This document analyzes which architectural areas the OpenWiki currently documents well, and where gaps exist based on source code inspection.

## Coverage Summary

| Area | Questions | Current Coverage | Status |
|------|-----------|-----------------|--------|
| Orchestration & Pipeline | 6 | Launcher, State Mgmt, Execution Model docs exist | ✓ Good |
| State Management | 3 | state-management.md covers basics | ⚠ Needs depth |
| Injection Safety | 1 | Mentioned in quickstart | ⚠ Incomplete |
| File Detection & Routing | 2 | agents/overview.md and routing-and-dispatch.md exist | ⚠ Missing DIE details |
| Coarse Agents | 2 | agents/coarse-agents.md exists | ⚠ Missing MCP integration |
| Skill System | 2 | skills/overview.md exists; SKILL.md structure docs | ✓ Good |
| Error Recovery | 1 | error-recovery.md exists | ✓ Good |
| Data Models | 2 | data-models.md and findings.md exist | ✓ Good |
| Dynamic Analysis | 1 | 05-dynamic-analysis.md exists | ⚠ x64dbg MCP needs detail |
| Stage Decisions | 1 | stage-dependencies.md covers some | ⚠ Unpack/Static-Pass2 logic missing |
| Configuration | 1 | setup/configuration.md exists | ⚠ Incomplete bootstrap details |
| Report Synthesis | 1 | 08-report.md and claim precedence coverage | ✓ Good |
| REST API | 1 | api/rest-api.md exists | ✓ Good |
| Validation | 1 | testing/validation.md exists | ✓ Good |
| Testing | 1 | testing/strategy.md exists | ⚠ Missing agent test details |

**Overall**: ~65% of critical areas well-documented; gaps in MCP protocols, DIE integration, and cross-stage logic.

---

## Detailed Gap Analysis

### [Q-001] 9-Stage Pipeline and STATE.json Contract

**What the Wiki Documents**:
- `/openwiki/orchestration/launcher.md` — stage sequencing, STAGES tuple structure
- `/openwiki/orchestration/state-management.md` — STATE.json structure, basic status flow
- `/openwiki/quickstart.md` — stage table overview

**What's Missing**:
- ✗ MAX_STAGE_ATTEMPTS exact purpose and value (20)
- ✗ Complete pipeline_state.py API reference (read/checkpoint/complete/fail methods)
- ✗ Exact environment variable injection for each stage (HYPERAGENT_ANALYSIS_DIR, HYPERAGENT_STATE_PATH, HYPERAGENT_STAGE_ID, HYPERAGENT_STAGE_OUTPUT_PATH)
- ✗ Pass 1 vs. Pass 2 distinction for hyperagent-static stage

**Recommendation**: Create `/openwiki/orchestration/pipeline-state-api.md` documenting pipeline_state.py commands and resumption semantics.

---

### [Q-002] Injection Guard and Sample-Content Hazards

**What the Wiki Documents**:
- `/openwiki/quickstart.md` — brief mention of injection guard in architecture patterns
- `/openwiki/architecture/pipeline.md` — defensive scope principle

**What's Missing**:
- ✗ Exact INJECTION_GUARD text verbatim
- ✗ Which stages are marked reads_sample_content (stages 02, 03, 04, 05, 06, 07)
- ✗ How --append-system-prompt flag is applied
- ✗ Security rationale: why sample strings could be misinterpreted as prompts

**Recommendation**: Expand `/openwiki/orchestration/launcher.md` with injection guard details and security model.

---

### [Q-003] Context Checkpointing and Resume Mechanics

**What the Wiki Documents**:
- `/openwiki/orchestration/state-management.md` — checkpoint concept and 80% threshold
- `/openwiki/architecture/pipeline.md` — checkpointing overview

**What's Missing**:
- ✗ Progress-file Markdown format (done/evidence/remaining/resume point structure)
- ✗ Example showing a stage checkpointing at 80% and launcher resuming it
- ✗ Exact launcher behavior when status='running' (lines 244–250 in claude_spawn.py)
- ✗ How progress_path is stored and used

**Recommendation**: Add a "Checkpoint Example" section to state-management.md showing end-to-end checkpoint/resume flow.

---

### [Q-004] File Type Detection via DIE (Detect It Easy)

**What the Wiki Documents**:
- `/openwiki/architecture/overview.md` — brief artifact-graph mention
- `/openwiki/integration/die.md` — expected to exist, but DIE documentation may be sparse

**What's Missing**:
- ✗ Complete DIE command-line interface (-b -p -u flags)
- ✗ DIE output parsing logic (file_class, packer, compiler, language extraction)
- ✗ AnalysisType enum (NATIVE, DOTNET, PYTHON_SCRIPT, UNKNOWN)
- ✗ Routing logic: how die_handler.identify() result selects NativeAgent, ScriptAgent, or DotNetAgent

**Recommendation**: Create or expand `/openwiki/integration/die.md` with full DIE parsing and routing logic.

---

### [Q-005] Coarse Agent Invocation and MCP Protocol Integration

**What the Wiki Documents**:
- `/openwiki/agents/coarse-agents.md` — agent overview
- `/openwiki/agents/routing-and-dispatch.md` — routing logic

**What's Missing**:
- ✗ Async entry points for each agent (NativeAgent.analyze(), ScriptAgent.analyze(), DotNetAgent.analyze())
- ✗ MCP protocol communication contract (run_claude_code async function, subprocess model)
- ✗ Claude Code command structure: `-p` flag, `--dangerously-skip-permissions`, instruction string
- ✗ MCP tools expected by each agent (ida-pro-mcp for NativeAgent, etc.)
- ✗ config.yaml MCP settings structure

**Recommendation**: Expand `/openwiki/agents/coarse-agents.md` with complete agent invocation and MCP protocol details. Create `/openwiki/integration/mcp-protocol.md` if not present.

---

### [Q-006] Skill System and SKILL.md Orchestration Model

**What the Wiki Documents**:
- `/openwiki/skills/overview.md` — Skill definition and SKILL.md structure
- `/openwiki/quickstart.md` — Skill concept definition

**What's Missing**:
- ✗ Detailed SKILL.md sections and their purposes (Runtime Path Contract, State/Resume, Role, Required Inputs, Output Contract, Tasks)
- ✗ Example walkthrough showing how a skill reads state, works, checkpoints, and completes
- ✗ Environment variable injection details (how launcher sets HYPERAGENT_ANALYSIS_DIR, HYPERAGENT_STAGE_ID, etc.)
- ✗ Default-output-path convention (01-prepare-env.json, 02-static-pass1.json, etc.)

**Recommendation**: Create `/openwiki/skills/skill-md-reference.md` with detailed SKILL.md structure and example implementation.

---

### [Q-007] Error Recovery and Failure States

**What the Wiki Documents**:
- `/openwiki/orchestration/error-recovery.md` — comprehensive failure taxonomy

**Coverage**: **✓ Good** — error-recovery.md covers:
- Exit code failures
- Artifact validation failures
- State drift detection
- MAX_STAGE_ATTEMPTS exhaustion
- Recovery strategies for each failure type

**Minor Gaps**:
- ⚠ Could add code examples showing state mutations for manual recovery
- ⚠ Could clarify artifact_is_valid subprocess model

**Recommendation**: Minor — consider adding manual recovery examples to error-recovery.md.

---

### [Q-008] Core Data Models and Artifact Graph Lineage

**What the Wiki Documents**:
- `/openwiki/architecture/data-models.md` — TaskSession, RunContext, ArtifactNode, Finding, etc.
- `/openwiki/data/findings.md` — Finding structure and categorization

**Coverage**: **✓ Good** — comprehensive model documentation.

**Minor Gaps**:
- ⚠ Could provide example artifact graphs showing parent/child relationships from real reports
- ⚠ ArtifactRegistry and FindingStore implementation details sparse

**Recommendation**: Add examples from `/reports/000d1bab5fa789f2d3b120bccb5452c7c3fe52073bd88d7d651b27dc68eb5423/` showing artifact lineage.

---

### [Q-009] End-to-End Execution Flow and Public Response

**What the Wiki Documents**:
- `/openwiki/quickstart.md` — high-level system overview
- `/openwiki/architecture/pipeline.md` — stage breakdown

**What's Missing**:
- ✗ Detailed end-to-end walkthrough from sample input to 09-summary output
- ✗ SHA256 becoming report-directory key explained
- ✗ Public response structure (compatibility mode vs. task observability)
- ✗ 09-summary.json schema (verdict, confidence, risk_level, executive_summary fields)

**Recommendation**: Create `/openwiki/workflows/end-to-end-flow.md` showing complete execution with example JSON.

---

### [Q-010] Stage Decision Points and Cross-Stage Validation

**What the Wiki Documents**:
- `/openwiki/architecture/stage-dependencies.md` — conditional execution and handoffs

**What's Missing**:
- ✗ Stage 03 (unpack) decision logic: when to return "Not needed" vs. attempt recovery
- ✗ Unpack indicators (packer, entropy, allocation patterns) from SKILL.md not documented
- ✗ Stage 04 (static-pass2) Pass 2 selection logic and artifact validation
- ✗ Inter-stage handoff contract: how 03 recommends artifact to 04

**Recommendation**: Expand `/openwiki/skills/stages/03-unpack.md` with decision policy. Create cross-reference from 04-static-pass2.md.

---

### [Q-011] Configuration Schema and Bootstrap Prerequisites

**What the Wiki Documents**:
- `/openwiki/setup/configuration.md` — config.yaml sections
- `/openwiki/setup/environment-setup.md` — bootstrap steps

**What's Missing**:
- ✗ Complete config.yaml schema with all sections (tools, mcp, llm)
- ✗ All environment variables listed with descriptions (HYPERAGENT_SKILLS_ROOT, HYPERAGENT_IDA_ROOT, HYPERAGENT_IDALIB_ACTIVATE, HYPERAGENT_CLAUDE_HOME)
- ✗ bootstrap.ps1 detailed walkthrough (Node.js, npm, Claude CLI, uv, idalib installation)
- ✗ MCP server bootstrap: idalib-mcp startup and x64dbg-mcp readiness check

**Recommendation**: Expand `/openwiki/setup/configuration.md` with complete config schema and environment variables reference.

---

### [Q-012] Dynamic Analysis Execution and x64dbg MCP Protocol

**What the Wiki Documents**:
- `/openwiki/skills/stages/05-dynamic-analysis.md` — dynamic stage overview

**What's Missing**:
- ✗ Complete x64dbg workflow: VM revert, sample copy, x64dbg launch, breakpoint deployment
- ✗ x64dbg MCP tool reference (debug_init, module_get_main, disassembly_at, memory_read, stack_get_trace)
- ✗ Subagent delegation pattern: when/how to delegate, what state to preserve
- ✗ x64dbg MCP endpoint and readiness probe (http://192.168.248.169:3000)
- ✗ Runtime state preservation between main session and subagents

**Recommendation**: Create or expand `/openwiki/integration/x64dbg-mcp.md` with complete protocol reference and workflow.

---

### [Q-013] Findings Schema and Evidence Provenance

**What the Wiki Documents**:
- `/openwiki/data/findings.md` — Finding structure and categorization
- `/openwiki/architecture/data-models.md` — Evidence array structure

**Coverage**: **✓ Good** — comprehensive finding schema documentation.

**Minor Gaps**:
- ⚠ Could add more real example findings from reports
- ⚠ Confidence scale (0.0–1.0) could be clarified further

**Recommendation**: Minor — add 2–3 real finding examples from /reports/ to findings.md.

---

### [Q-014] Report Synthesis and Claim Precedence

**What the Wiki Documents**:
- `/openwiki/skills/stages/08-report.md` — report synthesis
- `/openwiki/data/findings.md` — claim precedence rules

**Coverage**: **✓ Good** — claim precedence hierarchy documented.

**Minor Gaps**:
- ⚠ template.md structure not fully documented
- ⚠ prohibited_claims and caveated_claims usage could be clarified

**Recommendation**: Minor — reference template.md from 08-report.md documentation.

---

### [Q-015] REST API Integration and Programmatic Access

**What the Wiki Documents**:
- `/openwiki/api/rest-api.md` — endpoint overview and request/response models

**Coverage**: **✓ Good** — REST API documentation exists.

**Minor Gaps**:
- ⚠ Could add more example payloads
- ⚠ keep_file flag semantics could be clearer

**Recommendation**: Minor — add 2–3 example request/response payloads to rest-api.md.

---

### [Q-016] Skills Installation and Runtime Path Resolution

**What the Wiki Documents**:
- `/openwiki/setup/environment-setup.md` — bootstrap and installation

**What's Missing**:
- ✗ Default skills root path and HYPERAGENT_SKILLS_ROOT behavior
- ✗ Skills directory structure: SKILL.md, schema.json, scripts layout
- ✗ bootstrap.ps1 skill-copying logic (Install-ClaudeSkill function)
- ✗ _hyperagent-common subdirectory and shared scripts
- ✗ Path-resolution algorithm for SKILL.md, schema.json, helpers

**Recommendation**: Create `/openwiki/setup/skills-installation.md` with directory structure and path-resolution details.

---

### [Q-017] Validation Pipeline and Schema Contracts

**What the Wiki Documents**:
- `/openwiki/testing/validation.md` — validate_output.py and schema validation

**Coverage**: **✓ Good** — validation documentation exists.

**Minor Gaps**:
- ⚠ Could add more example schema.json files
- ⚠ validate_pipeline.py usage could be more detailed

**Recommendation**: Minor — add example schema.json and output pairs to validation.md.

---

### [Q-018] Batch Processing and Parallel Analysis

**What the Wiki Documents**:
- `/openwiki/orchestration/launcher.md` — batch flag overview

**What's Missing**:
- ✗ --batch flag detailed semantics (directory vs. file list)
- ✗ File-list parsing rules (blank lines, comments, relative path expansion)
- ✗ --continue-on-error semantics (sequential processing, failure handling)
- ✗ Batch completion report structure (succeeded/failed samples with exit codes)

**Recommendation**: Expand `/openwiki/orchestration/launcher.md` with detailed batch processing section.

---

### [Q-019] Launcher Command-Line Interface and Arguments

**What the Wiki Documents**:
- `/openwiki/orchestration/launcher.md` — argument overview

**What's Missing**:
- ✗ Complete argument reference (input_filepath, --batch, --continue-on-error, --claude)
- ✗ Mutual exclusivity rule (exactly one of input_filepath or --batch)
- ✗ --claude resolution logic (PATH search, npm global, absolute path)
- ✗ Exit codes explained (0, 1, 2, 127, 130)

**Recommendation**: Create `/openwiki/orchestration/launcher-cli-reference.md` with complete argument and exit-code documentation.

---

### [Q-020] Test Coverage and Integration Tests

**What the Wiki Documents**:
- `/openwiki/testing/strategy.md` — testing approach overview

**What's Missing**:
- ✗ Test class and method names (ScriptAgentRunnerIntegrationTests, etc.)
- ✗ What each test validates (prompt construction, tool invocation, output filtering)
- ✗ Mocking strategy for claude_code_runner, file extraction, disassembly
- ✗ Example showing full agent→prompt→analysis flow
- ✗ How to run test suite and pass/fail criteria

**Recommendation**: Expand `/openwiki/testing/strategy.md` with specific test examples and running instructions.

---

## Summary of Gaps

### High Priority (Missing Content)
1. **DIE Integration**: Full DIE command-line interface and parsing (Q-004)
2. **MCP Protocol Details**: x64dbg MCP tools, idalib-mcp startup, MCP server contracts (Q-005, Q-012)
3. **Skill System Detail**: SKILL.md sections, environment variable injection, example walkthrough (Q-006)
4. **Stage Decision Logic**: Unpack decision policy, Static Pass-2 selection logic (Q-010)
5. **Configuration Reference**: Complete config.yaml schema, environment variables (Q-011)
6. **Coarse Agent Integration**: Async entry points, agent selection logic, MCP protocol (Q-005)

### Medium Priority (Incomplete Documentation)
1. **Checkpoint/Resume Examples**: Working through a checkpoint scenario end-to-end (Q-003)
2. **End-to-End Flow**: Complete sample→run→findings walkthrough (Q-009)
3. **Test Details**: Specific test classes, mocking patterns, running instructions (Q-020)
4. **Batch Processing**: Detailed --batch and --continue-on-error semantics (Q-018)
5. **CLI Reference**: Complete launcher argument and exit-code documentation (Q-019)

### Low Priority (Minor Enhancements)
1. **Real Examples**: More examples from actual report files (Q-008, Q-013)
2. **Schema Examples**: More example schema.json and conforming outputs (Q-017)
3. **API Payloads**: More example request/response pairs (Q-015)

---

## Recommendations for Wiki Updates

### Phase 1: Critical Gaps (1–2 weeks)
1. Create `/openwiki/integration/die.md` — DIE command-line and parsing logic
2. Expand `/openwiki/integration/x64dbg-mcp.md` — x64dbg protocol and workflow
3. Expand `/openwiki/agents/coarse-agents.md` — agent invocation and MCP integration
4. Create `/openwiki/skills/skill-md-reference.md` — detailed SKILL.md structure

### Phase 2: Missing Workflows (1 week)
1. Create `/openwiki/workflows/end-to-end-flow.md` — complete sample→verdict walkthrough
2. Expand `/openwiki/skills/stages/03-unpack.md` — unpack decision policy
3. Create `/openwiki/setup/skills-installation.md` — skills directory structure and paths

### Phase 3: Configuration & CLI Reference (1 week)
1. Expand `/openwiki/setup/configuration.md` — complete config schema and environment variables
2. Create `/openwiki/orchestration/launcher-cli-reference.md` — CLI arguments and exit codes
3. Expand `/openwiki/orchestration/launcher.md` — batch processing details

### Phase 4: Testing & Examples (1 week)
1. Expand `/openwiki/testing/strategy.md` — specific test classes and running instructions
2. Enhance `/openwiki/data/findings.md` — real finding examples from reports
3. Enhance `/openwiki/testing/validation.md` — example schemas and outputs

---

**Total Estimated Effort**: 4–5 weeks to close all identified gaps.

**Current Wiki Quality**: 65% complete; well-documented architecture, sparse on implementation details and MCP protocol.

---

*This analysis was generated by analyzing the HyperAgent source code and comparing it against the existing OpenWiki documentation.*
