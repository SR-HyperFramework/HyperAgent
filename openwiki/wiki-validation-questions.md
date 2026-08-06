---
type: "Reference"
title: "HyperAgent Wiki Validation Questions"
openwiki_generated: true
---

# HyperAgent Wiki Validation Questions

These questions test whether the OpenWiki documentation adequately captures the architecture and behavior of the HyperAgent codebase.

---

## [Q-001]: 9-Stage Pipeline Sequencing and STATE.json Contract

**Question**: Explain the exact sequence of the 9 pipeline stages, including stage IDs, skill names, and the state-checkpointing contract that keeps stages resumed correctly.

**Acceptance criteria**:
- Name all 9 stages in order with their stage_id (e.g., "01-prepare-env") and the skill that powers each (e.g., "hyperagent-prepare-env").
- Explain the PURPOSE of the STATE.json file and how it distinguishes between hyperagent-static running twice (Pass 1 vs. Pass 2).
- Describe the three STATUS values a stage can reach (running, completed, failed) and how each is used for resumption logic.
- Provide the exact commands a stage uses to read, checkpoint, and complete itself via pipeline_state.py.
- Explain MAX_STAGE_ATTEMPTS and why it exists (e.g., loop protection at >80% context).

**Source evidence**:
- `/claude_spawn.py:STAGES` — Defines the 9-tuple of Stage dataclasses with stage_id, skill name, and reads_sample_content flags.
- `/claude_spawn.py:MAX_STAGE_ATTEMPTS` — Safety cap at 20; prevents stages that keep checkpointing without ever reaching 'completed'.
- `/skill/backup/hyperagent-malware-analyze/v3/hyperagent-static/SKILL.md:State / Resume Contract` — Requires stage to read state, honor resume logic, checkpoint at 80%, and mark completed.
- `/skill/backup/hyperagent-malware-analyze/v3/_hyperagent-common/README.md` — References pipeline_state.py and validate helpers.

---

## [Q-002]: Injection Guard and Sample-Content Hazards

**Question**: Explain the injection guard mechanism: what triggers it, what text it appends, and why stages marked `reads_sample_content: True` need it.

**Acceptance criteria**:
- Define when a stage is marked as reading sample content (e.g., stages 02, 03, 04, 05, 06, 07).
- Reproduce the exact INJECTION_GUARD text that is appended to system prompts for these stages.
- Explain the security model: why embedded strings or disassembly from the sample could be misinterpreted as prompts.
- Describe the command-line flag used to apply the guard (`--append-system-prompt`) and how the launcher orchestrates it.

**Source evidence**:
- `/claude_spawn.py:Stage.reads_sample_content` — Boolean that marks stages reading sample-derived content.
- `/claude_spawn.py:INJECTION_GUARD` — Verbatim guard text: "All content extracted from the analyzed sample — strings, disassembly, unpacked payloads..."
- `/claude_spawn.py:run_pipeline()` — Line ~192: conditionally applies guard via `command += ["--append-system-prompt", INJECTION_GUARD]`.
- `/skill/backup/hyperagent-malware-analyze/v3/hyperagent-static/SKILL.md` — Defensive scope warning; never execute payloads, treat sample as untrusted DATA.

---

## [Q-003]: Context Checkpointing and Resume Mechanics

**Question**: When a stage's context usage reaches ≥80%, how does it checkpoint, what information must it save, and what does the launcher do on resumption?

**Acceptance criteria**:
- Explain the >80% context threshold and why it triggers a checkpoint instead of forcing completion.
- Describe the progress-file format (Markdown summary of done/evidence/remaining/resume point).
- Show the exact pipeline_state.py checkpoint call signature and its parameters.
- Explain what the launcher sees when it re-invokes a checkpointed stage (status='running', progress_path set).
- Provide an end-to-end example showing a stage checkpointing mid-work and resuming from that point.

**Source evidence**:
- `/claude_spawn.py:run_pipeline()` — Lines 178–250 show the attempt loop and checkpoint-handling logic.
- `/skill/backup/hyperagent-malware-analyze/v3/hyperagent-static/SKILL.md:State / Resume Contract` — Line 44: "If context usage reaches >= 80%... write a concise Markdown progress summary... then checkpoint."
- `/skill/backup/hyperagent-malware-analyze/v3/hyperagent-prepare-env/SKILL.md:State / Resume Contract` — Same checkpoint pattern; references `$REPORT_DIR/_state/${STAGE_ID}.progress.md`.

---

## [Q-004]: File Type Detection via DIE (Detect It Easy)

**Question**: How does the system identify file type (Native, .NET, Python script) and route the sample to the correct coarse agent?

**Acceptance criteria**:
- Name the tool used for file identification (DIE / diec) and its command-line flags.
- Explain how DIE output is parsed (packer, compiler, language, file class).
- List the coarse agents and which file types they handle (NativeAgent → PE, DotNetAgent → .NET, ScriptAgent → Python).
- Show the routing decision logic: given DIE output, how is the agent selected?
- Provide the Python class and method where routing occurs.

**Source evidence**:
- `/.claude/worktrees/agent-a0c9420fcff8bac45/core/die_handler.py:DIEHandler` — Wraps diec subprocess; parse_die_text_output extracts file_class, compiler, language, packer.
- `/.claude/worktrees/agent-a0c9420fcff8bac45/core/die_handler.py:run_die()` — Executes `diec.exe -b -p -u <file>` and returns parsed result.
- `/.claude/worktrees/agent-a0c9420fcff8bac45/main.py:HyperAgentOrchestrator.analyze()` — Lines 26–36 show: call die_handler.identify(), match analysis_type, instantiate correct agent.
- `/.claude/worktrees/agent-a0c9420fcff8bac45/core/die_handler.py:AnalysisType` — Enum with NATIVE, DOTNET, PYTHON_SCRIPT, UNKNOWN.

---

## [Q-005]: Coarse Agent Invocation and MCP Protocol Integration

**Question**: How are the three coarse agents (Native, Script, .NET) invoked, and what is the MCP protocol contract they use to communicate with Claude Code?

**Acceptance criteria**:
- Describe the async entry point for each agent (e.g., NativeAgent.analyze(), ScriptAgent.analyze()).
- Explain how each agent spawns Claude Code as a subprocess (the run_claude_code async function).
- Detail the Claude Code command line: `-p` flag, `--dangerously-skip-permissions`, the instruction string.
- Name the MCP tools each agent expects to be available (e.g., ida-pro-mcp for NativeAgent, x64dbg-mcp for dynamic stages).
- Provide the config.yaml structure for MCP settings (e.g., claude_code_command, ida_server_command).

**Source evidence**:
- `/.claude/worktrees/agent-a0c9420fcff8bac45/agents/native_agent.py:NativeAgent.analyze()` — Async method that probes for idalib-mcp, spawns Claude Code with ida-specific prompt.
- `/.claude/worktrees/agent-a0c9420fcff8bac45/agents/script_agent.py:ScriptAgent.analyze()` — Builds pyinstaller extraction and disassembly prompt, spawns Claude Code.
- `/.claude/worktrees/agent-a0c9420fcff8bac45/agents/dotnet_agent.py:DotNetAgent.analyze()` — .NET-specific decompilation and analysis prompt.
- `/.claude/worktrees/agent-a0c9420fcff8bac45/core/claude_code_runner.py:run_claude_code()` — Async subprocess dispatch with `-p` and instruction.
- `/.claude/worktrees/agent-a0c9420fcff8bac45/config.yaml` — Tools and MCP command configuration.

---

## [Q-006]: Skill System and SKILL.md Orchestration Model

**Question**: What is a Skill in the HyperAgent model, and how does the SKILL.md file define the contract between the launcher and each stage?

**Acceptance criteria**:
- Define what a "Skill" is and how it relates to pipeline stages (e.g., one stage per skill, or shared skills like hyperagent-static).
- Explain the SKILL.md sections: Runtime Path Contract, State/Resume Contract, Role, Required Inputs, Output Contract, Tasks.
- Show how environment variables (`HYPERAGENT_SKILLS_ROOT`, `HYPERAGENT_ANALYSIS_DIR`, `HYPERAGENT_STAGE_ID`, `HYPERAGENT_STAGE_OUTPUT_PATH`) are injected by the launcher.
- Describe the default-output-path convention (e.g., `01-prepare-env.json`, `02-static-pass1.json`).
- Provide a concrete example from hyperagent-prepare-env or hyperagent-static showing how a skill reads and writes state.

**Source evidence**:
- `/skill/backup/hyperagent-malware-analyze/v3/hyperagent-prepare-env/SKILL.md` — Complete example of SKILL.md structure and contracts.
- `/skill/backup/hyperagent-malware-analyze/v3/hyperagent-static/SKILL.md` — Pass 1 / Pass 2 example showing shared skill, different stage IDs.
- `/claude_spawn.py:run_pipeline()` — Lines 202–207 show environment variable injection.
- `/claude_spawn.py:stage_schema_path()` — Example of skill-relative schema discovery.

---

## [Q-007]: Error Recovery and Failure States

**Question**: What failure states exist in the pipeline, how are errors classified, and what is the recovery strategy for each type?

**Acceptance criteria**:
- Name all fatal failure conditions: exit code != 0, status='completed' but artifact missing, status neither 'running' nor 'completed' on exit.
- Explain the role of artifact validation (validate_output.py against schema.json).
- Describe state drift detection (marked completed but artifact invalid at recorded path).
- Explain what happens at MAX_STAGE_ATTEMPTS exceeded (hard stop, no further re-invocation).
- Provide recovery guidance for each failure: manual intervention, state mutation, re-invocation rules.

**Source evidence**:
- `/claude_spawn.py:run_pipeline()` — Lines 230–283 show exit-code handling, artifact validation, state drift detection.
- `/claude_spawn.py:artifact_is_valid()` — Validates artifact exists and passes schema check via validate_output.py.
- `/claude_spawn.py:run_pipeline()` — Lines 244–250 show checkpoint recovery (status='running' → resume).
- `/skill/backup/hyperagent-malware-analyze/v3/hyperagent-static/SKILL.md:State / Resume Contract` — Explains failures in the context of a single stage (status='failed').

---

## [Q-008]: Core Data Models and Artifact Graph Lineage

**Question**: What are the core data entities (TaskSession, RunContext, ArtifactNode, Finding, AgentResult) and how do they relate to form the artifact graph?

**Acceptance criteria**:
- Define TaskSession: fields (task_id, session_id, parent_task_id, status, terminal_state, executor_kind, timestamps).
- Define RunContext: how it carries run/task identity through the pipeline.
- Define ArtifactNode: fields (id, path, sha256, parent_artifact_id, child_artifacts, storage).
- Define Finding: fields (id, artifact_id, category, status, confidence, evidence, reasoning).
- Explain the artifact graph structure: how unpacked payloads form parent/child relationships and enable multi-level analysis.

**Source evidence**:
- `/README.md` (Vietnamese section) — Lines 42–49 describe core model: TaskSession, RunContext, ArtifactNode, Finding, ArtifactRegistry, FindingStore, WorkQueue.
- `/reports/000d1bab5fa789f2d3b120bccb5452c7c3fe52073bd88d7d651b27dc68eb5423/02-static-pass1.json` — Example of Finding structure with evidence arrays, sources, confidence fields.
- `/reports/000d1bab5fa789f2d3b120bccb5452c7c3fe52073bd88d7d651b27dc68eb5423/09-summary.json` — Example of final summary with finding references.

---

## [Q-009]: End-to-End Execution Flow and Public Response

**Question**: Walk through a complete end-to-end flow from sample upload, through all 9 stages, to final findings report and verdict.

**Acceptance criteria**:
- Describe the triggering entry point (launcher, API, interactive prompt).
- Show how the sample's SHA256 becomes the report-directory key.
- For each stage, describe: inputs consumed, work performed, artifacts produced, decision points.
- Explain the final public response structure: compatibility mode (GET /runs/{run_id}), task observability (GET /runs/{run_id}/tasks).
- Provide the exact JSON schema for 09-summary stage (verdict, confidence, risk_level, executive_summary).

**Source evidence**:
- `/claude_spawn.py:main()` — Entry point; collects input path or batch; calls run_pipeline.
- `/claude_spawn.py:run_pipeline()` — Lines 143–286 show sequencing through STAGES tuple.
- `/.claude/worktrees/agent-a0c9420fcff8bac45/api.py:analyze_path()` and `analyze_upload()` — HTTP entry points that call orchestrator.analyze().
- `/reports/000d1bab5fa789f2d3b120bccb5452c7c3fe52073bd88d7d651b27dc68eb5423/` — Example reports with all stages from 01 to 09.

---

## [Q-010]: Stage Decision Points and Cross-Stage Validation

**Question**: How do stages make decisions to skip, proceed, or abort based on upstream outputs? Provide the decision logic for stages 03 (unpack) and 04 (static-pass2).

**Acceptance criteria**:
- For stage 03 (unpack): explain when to return "Not needed" vs. when to attempt recovery. Name the indicators (packer, entropy, allocation patterns).
- For stage 04 (static-pass2): explain when to select Pass 2 vs. fallback to analyzing the original sample. Show the artifact validation check.
- Describe inter-stage handoff: how 03 provides recommended artifact path/SHA256 to 04.
- Explain how prior-stage failures (e.g., 02-static-pass1.json missing) affect downstream stages.

**Source evidence**:
- `/skill/backup/hyperagent-malware-analyze/v3/hyperagent-unpack/SKILL.md:Stage Decision Policy` — Lines 77–97 list "Run when" and "Return Not needed when" criteria.
- `/skill/backup/hyperagent-malware-analyze/v3/hyperagent-static/SKILL.md:Pass Selection` — Lines 60–73 show Pass 1 vs. Pass 2 selection logic, artifact validation checks.
- `/reports/000d1bab5fa789f2d3b120bccb5452c7c3fe52073bd88d7d651b27dc68eb5423/03-unpack.json` — Example handoff: "Static Pass-2 Handoff" section identifies recommended artifact.

---

## [Q-011]: Configuration Schema and Bootstrap Prerequisites

**Question**: What configuration files, environment variables, and bootstrap steps are required to run HyperAgent end-to-end?

**Acceptance criteria**:
- Name the config.yaml sections: tools (diec, de4dot, dnspy paths), mcp (server commands), llm (claude_code_command).
- List all environment variables (HYPERAGENT_SKILLS_ROOT, HYPERAGENT_ANALYSIS_DIR, HYPERAGENT_STATE_PATH, HYPERAGENT_STAGE_ID, HYPERAGENT_STAGE_OUTPUT_PATH, HYPERAGENT_IDA_ROOT, HYPERAGENT_IDALIB_ACTIVATE, HYPERAGENT_CLAUDE_HOME).
- Describe the bootstrap.ps1 script: what it installs (Node.js, npm, Claude Code CLI, uv, idalib).
- Explain MCP server bootstrap (e.g., idalib-mcp startup sequence, x64dbg-mcp readiness check).
- Provide the minimum set of tools and paths needed for a functional static+dynamic workflow.

**Source evidence**:
- `/bootstrap.ps1` — Installation script; sets up environment, validates tool paths, installs Claude plugins.
- `/.claude/worktrees/agent-a0c9420fcff8bac45/config.yaml` — Example config with tools and MCP settings.
- `/claude_spawn.py:run_pipeline()` — Lines 201–206 show env variable construction and injection.
- `/skill/backup/hyperagent-malware-analyze/v3/hyperagent-prepare-env/SKILL.md:Routing` — Describes idalib and x64dbg-mcp bootstrap checks.

---

## [Q-012]: Dynamic Analysis Execution and x64dbg MCP Protocol

**Question**: How does the dynamic (stage 05) use x64dbg-mcp to instrument and analyze runtime behavior, and what is the MCP tool reference?

**Acceptance criteria**:
- Explain the complete workflow: VM revert, sample copy to guest, x64dbg launch, breakpoint deployment, runtime tracing.
- Name key x64dbg MCP tools referenced in the skill (debug_init, module_get_main, disassembly_at, memory_read, stack_get_trace, etc.).
- Describe the subagent delegation pattern: when heavy code-reading is delegated, what state must be preserved.
- Explain the MCP endpoint for x64dbg (e.g., http://192.168.248.169:3000) and the readiness probe.
- Show the runtime state that must be saved and passed between the main session and subagents.

**Source evidence**:
- `/skill/backup/hyperagent-malware-analyze/v3/hyperagent-dynamic/SKILL.md:Tasks` — Lines 78–100+ show detailed x64dbg workflow.
- `/skill/backup/hyperagent-malware-analyze/v3/hyperagent-dynamic/SKILL.md:Subagent Delegation` — Lines 60–76 show delegation pattern for heavy analysis.
- `/skill/backup/hyperagent-malware-analyze/v3/hyperagent-dynamic/toolcall_references.md` — Reference guide for x64dbg MCP tool names and signatures.
- `/reports/000d1bab5fa789f2d3b120bccb5452c7c3fe52073bd88d7d651b27dc68eb5423/05-dynamic.json` — Example dynamic stage output with observed behaviors.

---

## [Q-013]: Findings Schema and Evidence Provenance

**Question**: How are findings structured, categorized, and evidenced? Show the complete finding schema including categories, confidence levels, and evidence sources.

**Acceptance criteria**:
- Name all finding categories (sample_identity, loader, capability, anti_analysis, obfuscation, network, ioc, etc.).
- Define confidence scale (0.0–1.0 numeric or named levels like "high", "medium", "low").
- Explain the evidence array: kind (static, dynamic, tool_output), source (stage, artifact, location), observation, address, confidence.
- Show how findings are linked to artifacts (artifact_id or artifact references).
- Provide a complete example finding from a real report (02-static-pass1.json or 06-deepdive.json).

**Source evidence**:
- `/reports/000d1bab5fa789f2d3b120bccb5452c7c3fe52073bd88d7d651b27dc68eb5423/02-static-pass1.json:findings[0]` — Example finding with id, title, category, status, confidence, reasoning, evidence array.
- `/reports/000d1bab5fa789f2d3b120bccb5452c7c3fe52073bd88d7d651b27dc68eb5423/09-summary.json:confirmed_findings` — Summary linking findings to 06-deepdive.json source refs.

---

## [Q-014]: Report Synthesis and Claim Precedence

**Question**: How does the report stage (08) synthesize findings from multiple upstream stages, and what is the claim-precedence hierarchy?

**Acceptance criteria**:
- Name the inputs consumed by the report stage: 01-prepare-env, 02-static-pass1, 03-unpack, 04-static-pass2, 05-dynamic, 06-intel, 07-deepdive.
- Explain the claim-precedence rules: Deepdive > Direct dynamic > Validated recovered artifact > Static Pass-2 > Static Pass-1 > Public-source corroboration.
- Show how prohibited_claims and caveated_claims from 07-deepdive are respected in the report.
- Describe the Markdown report structure: identity, verdict, evidence, IOCs, mitigations, limitations.
- Provide the template.md structure used by hyperagent-report.

**Source evidence**:
- `/skill/backup/hyperagent-malware-analyze/v3/hyperagent-report/SKILL.md:Claim Precedence` — Lines 74–81 enumerate the hierarchy.
- `/skill/backup/hyperagent-malware-analyze/v3/hyperagent-report/SKILL.md:Required Inputs` — Lines 52–62 list all JSON inputs.
- `/skill/backup/hyperagent-malware-analyze/v3/hyperagent-report/SKILL.md:Tasks` — Lines 84–100 describe synthesis workflow.
- `/reports/000d1bab5fa789f2d3b120bccb5452c7c3fe52073bd88d7d651b27dc68eb5423/07-report.md` — Example markdown report.

---

## [Q-015]: REST API Integration and Programmatic Access

**Question**: How does the REST API layer (api.py) integrate with the HyperAgent orchestrator, and what are the request/response contracts?

**Acceptance criteria**:
- Name the endpoints: POST /analyze/path, POST /analyze/upload (and any others).
- Explain the AnalyzePathRequest and response models.
- Describe file-handling for /analyze/upload: keep_file flag, upload_id generation, temp vs. persistent storage.
- Show error handling: 404 (file not found), 400 (no file), 500 (analysis error).
- Provide example request/response payloads for both endpoints.

**Source evidence**:
- `/.claude/worktrees/agent-a0c9420fcff8bac45/api.py:analyze_path()` — Lines 30–41 show endpoint implementation.
- `/.claude/worktrees/agent-a0c9420fcff8bac45/api.py:analyze_upload()` — Lines 44–101 show upload handling, keep_file logic, temp cleanup.
- `/.claude/worktrees/agent-a0c9420fcff8bac45/api.py:AnalyzePathRequest` — Pydantic model for path requests.

---

## [Q-016]: Skills Installation and Runtime Path Resolution

**Question**: How are skills discovered, installed, and loaded at runtime? What is the HYPERAGENT_SKILLS_ROOT contract?

**Acceptance criteria**:
- Explain the default skills root: `~/.claude/skills` when HYPERAGENT_SKILLS_ROOT is unset.
- Describe the skills directory structure: each skill as a subdirectory with SKILL.md, schema.json, scripts.
- Show how bootstrap.ps1 copies skills from `/skill/` repo directory to `~/.claude/skills`.
- Explain the _hyperagent-common subdirectory: shared scripts (pipeline_state.py, validate_output.py, resolve_paths.py).
- Provide the exact path-resolution logic for SKILL.md, schema.json, and helper scripts.

**Source evidence**:
- `/claude_spawn.py:skills_root()` — Lines 74–76 show default and environment-override logic.
- `/bootstrap.ps1:Install-ClaudeSkill()` — Lines 48–58 show skill copying logic.
- `/skill/backup/hyperagent-malware-analyze/v3/hyperagent-prepare-env/SKILL.md:Runtime Path Contract` — Lines 8–27 show path resolution for HYPERAGENT_SKILLS_ROOT, COMMON_ROOT, SKILL_ROOT.

---

## [Q-017]: Validation Pipeline and Schema Contracts

**Question**: How are stage outputs validated against schema, and what is the validate_pipeline mechanism for end-to-end consistency?

**Acceptance criteria**:
- Explain validate_output.py: takes schema.json and a single output JSON, returns exit code 0 (valid) or non-zero (invalid).
- Describe when validation occurs: by the launcher after artifact_is_valid checks, and during resume to detect state drift.
- Explain validate_pipeline.py: validates all stage JSON files present in a report directory against their corresponding schemas.
- Show the schema.json structure: properties, required fields, examples.
- Provide an example schema (e.g., 01-prepare-env.json schema) and show a conforming output.

**Source evidence**:
- `/claude_spawn.py:artifact_is_valid()` — Lines 105–116 call validate_output.py subprocess.
- `/skill/backup/hyperagent-malware-analyze/v3/_hyperagent-common/README.md` — Mentions validate_output.py and validate_pipeline.py.

---

## [Q-018]: Batch Processing and Parallel Analysis

**Question**: How does the launcher support batch processing of multiple samples, and what are the failure-handling rules?

**Acceptance criteria**:
- Describe the --batch flag: accepts a directory or a newline-delimited text file.
- Explain the file-list parsing: skip blank lines, skip comments (#), expand paths relative to list file.
- Show the batch-processing loop: sequential invocation of run_pipeline for each sample.
- Explain the --continue-on-error flag: when present, keep processing despite failures; when absent, stop at first failure.
- Provide the batch-completion report: which samples succeeded, which failed (with exit codes).

**Source evidence**:
- `/claude_spawn.py:main()` — Lines 308–351 show batch argument parsing and loop.
- `/claude_spawn.py:collect_batch_inputs()` — Lines 119–135 show file-list parsing logic.

---

## [Q-019]: Launcher Command-Line Interface and Arguments

**Question**: What are all command-line arguments accepted by claude_spawn.py, and what is the semantics of each?

**Acceptance criteria**:
- Name all positional and optional arguments: input_filepath, --batch, --continue-on-error, --claude.
- Explain the mutual exclusivity: exactly one of input_filepath or --batch must be provided.
- Describe the --claude argument: path to Claude Code executable, with resolution logic (PATH search, npm global, absolute path).
- Show the help text and examples for common use cases.
- Explain exit codes: 0 (success), 1 (stage failed), 2 (input not found), 127 (Claude executable not found), 130 (interrupted).

**Source evidence**:
- `/claude_spawn.py:main()` — Lines 289–351 show argument parser setup.
- `/claude_spawn.py:resolve_claude()` — Lines 59–71 show Claude executable resolution logic.

---

## [Q-020]: Test Coverage and Integration Tests

**Question**: What integration and unit tests validate the agent runner, skills system, and end-to-end pipeline?

**Acceptance criteria**:
- Name the test classes and methods (e.g., ScriptAgentRunnerIntegrationTests.test_script_agent_builds_prompt_from_extraction_and_pyasm_outputs).
- Explain what each test validates: prompt construction, tool invocation, output filtering, error handling.
- Describe the mocking strategy: how claude_code_runner, file extraction, and disassembly are mocked.
- Show an example test that validates the full agent→prompt→analysis flow.
- Explain how to run the test suite and what pass/fail criteria are used.

**Source evidence**:
- `/.claude/worktrees/agent-a0c9420fcff8bac45/test_agent_runner_integration.py` — Integration tests for all three agents.
- `/.claude/worktrees/agent-a0c9420fcff8bac45/test_claude_code_runner.py` — Unit tests for the Claude Code subprocess wrapper.
- Tests demonstrate mocking of run_claude_code, file I/O, and tool subprocess calls.

---

## Summary

These 20 questions cover:

1. **Orchestration & Pipeline** (Q-001, Q-003, Q-007, Q-009, Q-018, Q-019)
2. **State & Resumption** (Q-001, Q-003, Q-006)
3. **Injection Safety** (Q-002)
4. **File Detection & Routing** (Q-004, Q-005)
5. **Coarse Agents** (Q-005)
6. **Skills System** (Q-006, Q-016)
7. **Error Recovery** (Q-007)
8. **Data Models** (Q-008, Q-013)
9. **Dynamic Analysis** (Q-012)
10. **Stage Decisions** (Q-010)
11. **Configuration** (Q-011)
12. **Report Synthesis** (Q-014)
13. **REST API** (Q-015)
14. **Validation** (Q-017)
15. **Testing** (Q-020)

Each question is grounded in specific source files, classes, methods, and line numbers that demonstrate the architectural decisions and implementation details that the wiki should document.
