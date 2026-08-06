---
type: "Reference"
title: "OpenWiki Skeleton for HyperAgent"
openwiki_generated: true
---

# OpenWiki Skeleton for HyperAgent

> This is a planning document for the OpenWiki structure. It will be deleted once all wiki pages are created.

## Repository Overview

HyperAgent is a sophisticated multi-stage malware-analysis orchestrator built on an artifact-graph model with task-session observability. It sequences 9 pipeline stages, each backed by Claude Code skills, to perform comprehensive analysis of suspicious samples (native binaries, .NET assemblies, Python bytecode).

## Wiki Structure Plan

### 1. **quickstart.md** — Entrypoint and Navigation
   - High-level repository overview
   - Key concepts (run, task session, artifact, finding)
   - Main systems and workflows
   - Quick reference task-routing table
   - Links to major sections

### 2. **architecture/** — System Architecture

   **architecture/overview.md**
   - Artifact-graph orchestrator model
   - Pipeline stage sequencing (9 stages)
   - State management and checkpointing
   - Task observability layer
   - Runtime execution model (local vs Claude-backed)
   - Data flow from sample → findings → report

   **architecture/pipeline.md**
   - Stage-by-stage breakdown (01-prepare-env through 09-summary)
   - State contract (STATE.json, stage table, status semantics)
   - Context checkpointing logic
   - Stage resumption and MAX_STAGE_ATTEMPTS safety cap
   - Injection guard for sample-content stages
   - Integration with pipeline_state.py module

   **architecture/stage-dependencies.md**
   - Stage decision policies and conditional execution
   - Progress-file checkpoint mechanism
   - Cross-stage validation and consistency checking
   - Explicit handoff contracts between stages (03↔04, 05↔07, 06↔07)
   - Artifact lineage and inheritance across stages
   - Data flow diagram showing dependencies

   **architecture/data-models.md**
   - TaskSession, RunContext, ArtifactNode, Finding
   - AgentResult, ArtifactRegistry, FindingStore
   - WorkQueue and WorkItem
   - Stage model with stage_id/skill/reads_sample_content
   - Entity relationships and lineage
   - Response envelope and snapshot schemas

   **architecture/task-observability.md**
   - Task session model and lifecycle
   - Live task snapshot structure
   - Board projection (pending/processing/completed)
   - Timeline and detail view
   - Task hierarchy (parent_task_id for nested work)
   - Terminal states and outcome badges

### 3. **orchestration/** — Pipeline Execution and Orchestration

   **orchestration/launcher.md**
   - claude_spawn.py: Main entry point and CLI
   - Pipeline orchestration loop
   - Stage sequencing and MAX_STAGE_ATTEMPTS cap
   - resolve_claude(), skills_root(), load_pipeline_state_module()
   - Batch input collection and normalization
   - Integration with Claude Code CLI
   - Injection guard appending for sample-content stages
   - Note: hyperagent-progress is the primary operator entry point

   **orchestration/pipeline-controller.md**
   - hyperagent-progress: Operator-facing run discovery and resumption tool
   - Discovering STATE.json files under reports/ directory
   - Classification logic (finished/resumable/drifted runs)
   - Run table display sorted by recency
   - Auto-resume behavior and delegation to claude_spawn.py
   - Recommend_next_stage summary display
   - Status summaries and triage interface for ongoing runs

   **orchestration/state-management.md**
   - STATE.json contract and structure
   - pipeline_state.py: Canonical state helper
   - Stage table and status semantics
   - Checkpoint/resume logic
   - Atomic state mutations
   - Recommend-next-stage hints for operators
   - Stage artifact validation via schema.json

   **orchestration/execution-model.md**
   - Per-skill execution with environment variables
   - HYPERAGENT_ANALYSIS_DIR, HYPERAGENT_STATE_PATH, HYPERAGENT_STAGE_ID
   - Stage invocation via Claude Code skill
   - Context usage monitoring and checkpointing
   - Error handling and failure recording
   - Artifact validation at stage boundaries

   **orchestration/error-recovery.md**
   - Failure states and meanings (pending, running, completed, failed)
   - Error tagging conventions ([STATIC-ENV-ERR], [DYN-ENV-ERR])
   - MAX_STAGE_ATTEMPTS safety cap and infinite-loop prevention
   - Artifact validation failures and recovery
   - Partial completion and resume semantics
   - Logging and observability for troubleshooting
   - Operator intervention points and manual recovery

### 4. **agents/** — Coarse and Specialist Agents

   **agents/overview.md**
   - Agent taxonomy: coarse vs specialist reasoning
   - Routing logic based on file type detection
   - Agent execution flow within static/dynamic stages
   - Result aggregation and next-stage hunting

   **agents/coarse-agents.md**
   - NativeAgent: x86/x64 PE binaries (in /.claude/worktrees/agent-*/agents/)
   - ScriptAgent: Python bytecode, PyInstaller, shell scripts
   - DotNetAgent: .NET assemblies and CLR payloads
   - Local file type detection and routing
   - Claude-backed child session spawning for analysis
   - Result format and findings projection
   - Note: Relationship to 9-stage pipeline (clarified in routing-and-dispatch.md)

   **agents/routing-and-dispatch.md**
   - File type detection via DIE (Detect It Easy)
   - Routing logic to coarse agents (native/script/.net)
   - Integration with 02-static-pass1 stage
   - Agent composition and invocation patterns

### 5. **skills/** — Claude Skill Pipeline

   **skills/overview.md**
   - Skill system overview and compatibility model
   - hyperagent-malware-analyze: Dispatcher and compatibility alias
   - hyperagent-progress: Operator entry point for run discovery/resumption
   - Specialist skills under skill/ directory
   - SKILL.md orchestration and playbook workflows
   - Skill tree hierarchy
   - Specialist reasoning in stages 06, 07, 08 (not separate classes)

   **skills/stages/01-prepare-env.md**
   - Environment readiness verification
   - Python/CLI tool availability checks
   - Sample path accessibility
   - Staging directory permissions
   - Output: 01-prepare-env.json

   **skills/stages/02-04-static-analysis.md**
   - Static pass 1 (02-static-pass1)
   - Unpack stage (03-unpack)
   - Static pass 2 (04-static-pass2)
   - Identify → route → agent → next_stage_hunter substages
   - Payload extraction and artifact graph expansion
   - DIE integration and file type detection

   **skills/stages/05-dynamic-analysis.md**
   - Runtime behavior capture
   - x64dbg-mcp debugger integration
   - VMware guest execution
   - Process spawning and monitoring
   - Network traffic capture
   - Findings extraction: behavior, network, file operations

   **skills/stages/06-intel.md**
   - External reputation and IOC enrichment
   - VirusTotal API integration (optional)
   - fetch_vt_file_report.py, normalize_vt_to_intel.py
   - Hash reputation queries
   - IOC normalization and consolidation

   **skills/stages/07-deepdive.md**
   - Targeted deep analysis based on confidence
   - Cross-stage finding reconciliation
   - Specialist reasoning and follow-up investigation
   - High-confidence finding expansion

   **skills/stages/08-report.md**
   - Markdown report synthesis
   - Executive summary generation
   - Artifact listing
   - Finding details by category
   - IOC extraction and formatting
   - Capability mapping visualization

   **skills/stages/09-summary.md**
   - Final verdict assignment
   - Risk score calculation (0-100)
   - Confidence assessment
   - Reasoning and justification

### 6. **api/** — HTTP API and Observability

   **api/rest-api.md**
   - FastAPI application structure in api.py
   - POST /analyze/path: Analyze file from path (implemented)
   - POST /analyze/upload: Analyze uploaded file (implemented)
   - Response schemas and orchestrator integration
   - File upload handling and temporary/persistent storage
   - Note: GET /runs endpoints planned but not yet implemented

   **api/dashboard.md**
   - Task board visualization (pending/processing/completed)
   - Timeline and detail view
   - Live task updates during analysis
   - Terminal outcome badges
   - Operator intent and state mutation

### 7. **data/** — Data Schemas and Types

   **data/artifacts.md**
   - ArtifactNode structure and lineage
   - Artifact types: file, directory, memory, network, behavioral
   - Parent/child relationships and graph traversal
   - SHA256 hashing and deduplication
   - Artifact registry indexes

   **data/findings.md**
   - Finding model and lifecycle
   - Categories: behavior, obfuscation, config, ioc, capability, anomaly
   - Severity levels: critical, high, medium, low, info
   - Evidence linking
   - Finding store and querying

   **data/schemas.md**
   - STATE.json schema structure and contract
   - Per-stage output schemas (JSON structure, required fields, enums)
   - Template and example files
   - Schema validation and versioning strategy
   - How to extend schemas without breaking compatibility

   **data/response-contract.md**
   - Public response envelope structure
   - RunSnapshot vs. TaskSnapshot models
   - Backward compatibility guarantees
   - Field descriptions and types
   - Example JSON responses

   **data/models.md**
   - Stage, TaskSession, RunContext
   - ArtifactNode, Finding, AgentResult
   - ArtifactRegistry, FindingStore
   - WorkQueue, WorkItem
   - Type definitions and constraints

### 8. **integration/** — External Tool Integration

   **integration/mcp-protocol.md**
   - MCP (Model Context Protocol) overview
   - How Claude Code skills communicate with MCP servers
   - Tool definitions and calling conventions

   **integration/ida-pro-mcp.md**
   - IDA Pro integration via ida-pro-mcp server
   - Plugin syntax (/ida-pro:idapython)
   - Available tools and functions
   - Binary analysis workflows

   **integration/x64dbg-mcp.md**
   - x64dbg debugger integration via x64dbg-mcp
   - Tool reference: debug_init, module_get_main, debug_get_state, etc.
   - Breakpoint and memory access
   - Register and stack inspection
   - Error handling and recovery

   **integration/vmware.md**
   - VMware guest VM orchestration
   - vmrun command set and workflow
   - Sample staging and process execution
   - Behavior capture and artifact collection

   **integration/die.md**
   - DIE (Detect It Easy) file type detection
   - Command-line options and output format
   - Integration in die_handler.py
   - Parse_die_text_output() and packer detection

   **integration/virustotal.md**
   - VirusTotal API integration
   - File reputation queries
   - Behavior sandbox results
   - Rate limiting and authentication
   - Error handling and fallback strategies

### 9. **utilities/** — Helper Functions and Tools

   **utilities/helpers.md**
   - sha256_of(): File hash computation
   - stage_schema_path(): Schema resolution
   - artifact_is_valid(): JSON Schema validation
   - collect_batch_inputs(): Batch file collection
   - normalize_vt_to_intel(): VT result transformation
   - resolve_paths(): Path normalization
   - validate_pipeline(): End-to-end consistency check
   - validate_output.py: Per-stage artifact validation

   **utilities/error-tags.md**
   - Error tagging conventions ([STATIC-ENV-ERR], [DYN-ENV-ERR])
   - Environment failure detection and reporting
   - Stage-specific error patterns

### 10. **setup/** — Environment and Configuration

   **setup/environment-setup.md**
   - Complete bootstrap workflow (bootstrap.ps1 overview)
   - Required external tools and installation
   - MCP server setup (ida-pro-mcp, x64dbg-mcp)
   - Environment variables and precedence
   - Per-stage environment variable injection
   - Tool discovery and startup (IDA Pro plugin, x64dbg server)
   - Validation checks and troubleshooting
   - Prerequisites from individual skill ENVIRONMENT.md files

   **setup/configuration.md**
   - config.yaml structure, schema, and validation
   - Tool paths (diec, ida-pro-mcp, x64dbg-mcp)
   - MCP server configuration and timeouts
   - Environment variable precedence (HYPERAGENT_SKILLS_ROOT, HYPERAGENT_ANALYSIS_DIR, HYPERAGENT_STATE_PATH, HYPERAGENT_STAGE_ID)
   - Failure modes when required tools are missing

### 11. **testing/** — Validation and Testing

   **testing/strategy.md**
   - Unit tests for individual skills/stages
   - Integration tests for cross-stage data flow
   - End-to-end pipeline validation
   - Test fixtures and sample data
   - Test coverage expectations
   - Continuous integration workflow

   **testing/validation.md**
   - validate_output.py: JSON Schema validator
   - Stage artifact validation
   - Schema.json per-stage
   - Exit codes and error reporting

   **testing/pipeline-validation.md**
   - validate_pipeline.py: End-to-end consistency
   - STATE.json compliance
   - Stage artifact existence and validity
   - Artifact lineage integrity
   - Finding references validation

   **testing/test-fixtures.md**
   - Sample malware test data and provenance
   - How to create and manage test cases
   - Expected outputs for baseline comparison

### 12. **workflows/** — Common Change Recipes

   **workflows/add-skill.md**
   - Creating a new analysis skill
   - SKILL.md orchestration structure
   - Schema.json and output validation
   - Integration into stage pipeline
   - Test coverage requirements

   **workflows/extend-pipeline.md**
   - Adding a new stage to the pipeline
   - Stage ID and skill naming
   - STATE.json registration
   - Schema.json validation
   - Integration with orchestration loop

   **workflows/debug-stage-failure.md**
   - Inspecting STATE.json and artifacts
   - Accessing stage output and logs
   - Checking context usage
   - Resuming failed stages
   - Validating artifact structure
   - MAX_STAGE_ATTEMPTS and infinite-loop prevention

## Document Coverage Status

All TODOs from skeleton critic have been addressed:

- ✅ RQ-01: Specialist analyzers corrected (reasoning in stages 06-08, not separate classes)
- ✅ RQ-02: Stage dependencies documented (stage-dependencies.md)
- ✅ RQ-03: API routes clarified (implemented vs. planned)
- ✅ RQ-04: Coarse agent relationship clarified (routing-and-dispatch.md)
- ✅ RQ-05: Configuration management documented (setup/environment-setup.md)
- ✅ RQ-06: Bootstrap workflow unified (setup/environment-setup.md)
- ✅ RQ-07: Schemas documented (data/schemas.md)
- ✅ RQ-08: External tool integration expanded (integration/ directory)
- ✅ RQ-09: Testing strategy added (testing/strategy.md)
- ✅ RQ-10: Error recovery documented (orchestration/error-recovery.md)
- ✅ RQ-11: hyperagent-progress skill documented (orchestration/pipeline-controller.md)

## Next Steps

Once this skeleton is approved, the main agent will:

1. Create directory structure under /openwiki
2. Write substantive content for each page
3. Ensure all symbols, entrypoints, and workflows are documented
4. Include Mermaid diagrams for complex flows
5. Validate internal links and cross-references
6. Run wiki_question_finder and wiki_answer_verifier for coverage verification
