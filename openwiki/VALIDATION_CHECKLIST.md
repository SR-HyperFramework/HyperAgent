---
type: "Reference"
title: "Wiki Validation Quick Checklist"
openwiki_generated: true
---

# Wiki Validation Quick Checklist

Use this checklist to quickly assess wiki coverage for each validation question. Mark each criterion as ✓ (documented), ⚠ (incomplete), or ✗ (missing).

---

## Q-001: 9-Stage Pipeline and STATE.json Contract

- [ ] All 9 stages named with stage_id and skill name
- [ ] STATE.json purpose explained
- [ ] Pass 1 vs. Pass 2 distinction (hyperagent-static) documented
- [ ] Three STATUS values (running, completed, failed) and resumption logic explained
- [ ] pipeline_state.py commands documented (read, checkpoint, complete, fail)
- [ ] MAX_STAGE_ATTEMPTS and its purpose explained

**Wiki files to check**: 
  - `/openwiki/orchestration/launcher.md`
  - `/openwiki/orchestration/state-management.md`
  - `/openwiki/architecture/pipeline.md`

---

## Q-002: Injection Guard and Sample-Content Hazards

- [ ] When stages are marked `reads_sample_content: True` documented
- [ ] INJECTION_GUARD text verbatim provided
- [ ] Security rationale explained (why sample strings could be misinterpreted as prompts)
- [ ] `--append-system-prompt` flag and launcher orchestration documented
- [ ] Which stages (02, 03, 04, 05, 06, 07) apply the guard identified

**Wiki files to check**:
  - `/openwiki/orchestration/launcher.md`
  - `/openwiki/architecture/pipeline.md`

---

## Q-003: Context Checkpointing and Resume Mechanics

- [ ] >80% context threshold and its purpose explained
- [ ] Progress-file format (Markdown structure) documented
- [ ] pipeline_state.py checkpoint call signature and parameters shown
- [ ] Launcher behavior on resumption (status='running' handling) explained
- [ ] End-to-end checkpoint/resume example provided

**Wiki files to check**:
  - `/openwiki/orchestration/state-management.md`
  - `/openwiki/orchestration/launcher.md`

---

## Q-004: File Type Detection via DIE (Detect It Easy)

- [ ] DIE command-line tool and flags documented (diec.exe -b -p -u)
- [ ] DIE output parsing logic explained (file_class, packer, compiler, language extraction)
- [ ] AnalysisType enum values documented (NATIVE, DOTNET, PYTHON_SCRIPT, UNKNOWN)
- [ ] Coarse agents and their file types listed (NativeAgent → PE, etc.)
- [ ] Routing decision logic explained

**Wiki files to check**:
  - `/openwiki/integration/die.md`
  - `/openwiki/agents/routing-and-dispatch.md`

---

## Q-005: Coarse Agent Invocation and MCP Protocol Integration

- [ ] Async entry points for each agent (NativeAgent.analyze(), ScriptAgent.analyze(), DotNetAgent.analyze()) documented
- [ ] run_claude_code async function and subprocess model explained
- [ ] Claude Code command structure documented (`-p`, `--dangerously-skip-permissions`, instruction)
- [ ] MCP tools expected by each agent named (ida-pro-mcp, x64dbg-mcp, etc.)
- [ ] config.yaml MCP settings structure shown

**Wiki files to check**:
  - `/openwiki/agents/coarse-agents.md`
  - `/openwiki/agents/routing-and-dispatch.md`
  - `/openwiki/integration/mcp-protocol.md`

---

## Q-006: Skill System and SKILL.md Orchestration Model

- [ ] Skill definition and relationship to pipeline stages explained
- [ ] SKILL.md sections documented (Runtime Path Contract, State/Resume, Role, etc.)
- [ ] Environment variables injected by launcher documented
- [ ] Default-output-path convention explained (01-prepare-env.json, etc.)
- [ ] Concrete example showing skill read/work/checkpoint/complete cycle provided

**Wiki files to check**:
  - `/openwiki/skills/overview.md`
  - `/openwiki/skills/skill-md-reference.md` (may need creation)

---

## Q-007: Error Recovery and Failure States

- [ ] Fatal failure conditions listed (exit code != 0, missing artifact, etc.)
- [ ] Artifact validation (validate_output.py) role explained
- [ ] State drift detection explained
- [ ] MAX_STAGE_ATTEMPTS exhaustion behavior described
- [ ] Recovery strategy for each failure type provided

**Wiki files to check**:
  - `/openwiki/orchestration/error-recovery.md`

---

## Q-008: Core Data Models and Artifact Graph Lineage

- [ ] TaskSession fields documented (task_id, session_id, parent_task_id, status, etc.)
- [ ] RunContext definition and role explained
- [ ] ArtifactNode structure documented (id, path, sha256, parent/child relationships)
- [ ] Finding structure documented (id, artifact_id, category, status, confidence, evidence)
- [ ] Artifact graph structure and multi-level analysis explained

**Wiki files to check**:
  - `/openwiki/architecture/data-models.md`
  - `/openwiki/data/artifacts.md`

---

## Q-009: End-to-End Execution Flow and Public Response

- [ ] Entry points (launcher, API, interactive) documented
- [ ] SHA256 becoming report-directory key explained
- [ ] For each stage: inputs, work, artifacts, decision points described
- [ ] Public response structure explained (compatibility mode vs. task observability)
- [ ] 09-summary.json schema documented (verdict, confidence, risk_level, executive_summary)

**Wiki files to check**:
  - `/openwiki/quickstart.md`
  - `/openwiki/architecture/pipeline.md`
  - `/openwiki/workflows/end-to-end-flow.md` (may need creation)

---

## Q-010: Stage Decision Points and Cross-Stage Validation

- [ ] Stage 03 (unpack) decision policy documented (when to return "Not needed")
- [ ] Unpack indicators (packer, entropy, allocation patterns) explained
- [ ] Stage 04 (static-pass2) Pass 2 selection logic documented
- [ ] Artifact validation for Pass 2 explained
- [ ] Inter-stage handoff contract (03 → 04) documented

**Wiki files to check**:
  - `/openwiki/skills/stages/03-unpack.md`
  - `/openwiki/skills/stages/04-static-pass2.md`
  - `/openwiki/architecture/stage-dependencies.md`

---

## Q-011: Configuration Schema and Bootstrap Prerequisites

- [ ] config.yaml sections documented (tools, mcp, llm)
- [ ] All environment variables listed with descriptions
- [ ] bootstrap.ps1 script walkthrough provided
- [ ] MCP server bootstrap (idalib-mcp, x64dbg-mcp) explained
- [ ] Minimum tools and paths for static+dynamic workflow documented

**Wiki files to check**:
  - `/openwiki/setup/configuration.md`
  - `/openwiki/setup/environment-setup.md`

---

## Q-012: Dynamic Analysis Execution and x64dbg MCP Protocol

- [ ] x64dbg workflow documented (VM revert, sample copy, launch, breakpoints)
- [ ] x64dbg MCP tools documented (debug_init, module_get_main, disassembly_at, memory_read, stack_get_trace)
- [ ] Subagent delegation pattern explained (when/how to delegate, state preservation)
- [ ] x64dbg MCP endpoint and readiness probe documented
- [ ] Runtime state preservation between sessions explained

**Wiki files to check**:
  - `/openwiki/skills/stages/05-dynamic-analysis.md`
  - `/openwiki/integration/x64dbg-mcp.md`

---

## Q-013: Findings Schema and Evidence Provenance

- [ ] Finding categories listed
- [ ] Confidence scale explained (0.0–1.0 or named levels)
- [ ] Evidence array structure documented (kind, source, observation, address, confidence)
- [ ] Artifact linkage for findings explained
- [ ] Real example findings provided from reports

**Wiki files to check**:
  - `/openwiki/data/findings.md`
  - `/openwiki/architecture/data-models.md`

---

## Q-014: Report Synthesis and Claim Precedence

- [ ] Report stage inputs documented (01–07 JSON files)
- [ ] Claim-precedence hierarchy fully explained
- [ ] prohibited_claims and caveated_claims usage documented
- [ ] Markdown report structure described
- [ ] template.md structure referenced or documented

**Wiki files to check**:
  - `/openwiki/skills/stages/08-report.md`
  - `/openwiki/data/findings.md`

---

## Q-015: REST API Integration and Programmatic Access

- [ ] Endpoints documented (POST /analyze/path, POST /analyze/upload)
- [ ] AnalyzePathRequest model explained
- [ ] File-handling for /analyze/upload documented (keep_file, upload_id, temp vs. persistent)
- [ ] Error handling explained (404, 400, 500)
- [ ] Example request/response payloads provided

**Wiki files to check**:
  - `/openwiki/api/rest-api.md`

---

## Q-016: Skills Installation and Runtime Path Resolution

- [ ] Default skills root path documented (~/.claude/skills)
- [ ] HYPERAGENT_SKILLS_ROOT behavior explained
- [ ] Skills directory structure documented (SKILL.md, schema.json, scripts)
- [ ] bootstrap.ps1 skill-copying logic explained
- [ ] _hyperagent-common subdirectory and shared scripts documented

**Wiki files to check**:
  - `/openwiki/setup/environment-setup.md`
  - `/openwiki/setup/skills-installation.md` (may need creation)

---

## Q-017: Validation Pipeline and Schema Contracts

- [ ] validate_output.py purpose and usage documented
- [ ] When validation occurs (artifact_is_valid, state drift) explained
- [ ] validate_pipeline.py functionality documented
- [ ] schema.json structure shown
- [ ] Example schema and conforming output provided

**Wiki files to check**:
  - `/openwiki/testing/validation.md`

---

## Q-018: Batch Processing and Parallel Analysis

- [ ] --batch flag documented (directory vs. file list)
- [ ] File-list parsing rules explained (blank lines, comments, path expansion)
- [ ] --continue-on-error semantics explained
- [ ] Sequential processing model documented
- [ ] Batch completion report format explained

**Wiki files to check**:
  - `/openwiki/orchestration/launcher.md`

---

## Q-019: Launcher Command-Line Interface and Arguments

- [ ] All arguments documented (input_filepath, --batch, --continue-on-error, --claude)
- [ ] Mutual exclusivity rule explained
- [ ] --claude resolution logic documented (PATH, npm, absolute path)
- [ ] Exit codes explained (0, 1, 2, 127, 130)
- [ ] Usage examples provided

**Wiki files to check**:
  - `/openwiki/orchestration/launcher.md`
  - `/openwiki/orchestration/launcher-cli-reference.md` (may need creation)

---

## Q-020: Test Coverage and Integration Tests

- [ ] Test classes and methods documented
- [ ] What each test validates explained
- [ ] Mocking strategy documented (claude_code_runner, extraction, disassembly)
- [ ] Full agent→prompt→analysis flow example shown
- [ ] How to run tests and pass/fail criteria explained

**Wiki files to check**:
  - `/openwiki/testing/strategy.md`

---

## Scoring Your Validation

After checking each question:

**Count your marks**:
- ✓ = well-documented
- ⚠ = incomplete or needs clarification
- ✗ = missing entirely

**Calculate coverage**:
- `(✓ count / 100) * 100%` = overall documentation quality

**Score interpretation**:
- **90–100%**: Excellent — wiki comprehensively covers the question
- **70–89%**: Good — wiki covers most criteria; minor gaps
- **50–69%**: Partial — wiki covers half; significant gaps
- **<50%**: Poor — wiki missing key information; needs major work

---

## Using This Checklist

1. **For quick audits**: Check 2–3 questions per day
2. **For targeted improvements**: Focus on questions scoring <70%
3. **For high-impact fixes**: Prioritize questions in COVERAGE_ANALYSIS.md "High Priority" section
4. **For tracking progress**: Update checklist as wiki improves

---

## Next Steps

After validation:

1. **Compile results** → Which questions scored ✓, ⚠, ✗?
2. **Prioritize gaps** → Use COVERAGE_ANALYSIS.md recommendations
3. **Assign work** → Allocate wiki updates by topic
4. **Track progress** → Re-validate after updates to confirm fixes
5. **Iterate** → Repeat until all questions score ✓

---

**Target**: Get all 20 questions to ✓ (well-documented) status.

**Estimated time to 100%**: 4–5 weeks based on COVERAGE_ANALYSIS.md.

---

*For detailed question descriptions and source citations, see [`wiki-validation-questions.md`](./wiki-validation-questions.md).*
*For gap analysis and recommendations, see [`COVERAGE_ANALYSIS.md`](./COVERAGE_ANALYSIS.md).*
