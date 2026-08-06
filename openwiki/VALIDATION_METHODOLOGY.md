---
type: "Reference"
title: "Wiki Validation Methodology"
openwiki_generated: true
---

# Wiki Validation Methodology

This document describes how the HyperAgent OpenWiki is validated for completeness and accuracy against the source codebase.

## Overview

The validation questions in `/openwiki/wiki-validation-questions.md` test whether the wiki adequately documents the HyperAgent architecture, implementation, and operational requirements. These are **not** questions to ask users; they are verification criteria for wiki completeness.

## Approach

Each validation question follows this structure:

1. **Question**: A clear, specific query that a developer should be able to answer using ONLY the OpenWiki (no source code reading).
2. **Acceptance Criteria**: 3–5 concrete requirements showing what the wiki must document to pass.
3. **Source Evidence**: Specific file paths, class/function names, and line ranges that motivated the question.

## Coverage Areas

The 20 questions span 8 major architectural domains:

### 1. Orchestration & Pipeline Execution (6 questions)
- Q-001: 9-stage sequencing and STATE.json contract
- Q-003: Context checkpointing and resumption mechanics
- Q-007: Error recovery and failure states
- Q-009: End-to-end execution flow and public response
- Q-018: Batch processing and failure handling
- Q-019: Launcher command-line interface

### 2. State Management & Resumption (3 questions)
- Q-001: STATE.json structure and usage
- Q-003: Checkpoint file format and launch
- Q-006: Skill system and SKILL.md contract

### 3. Sample Safety & Injection Prevention (1 question)
- Q-002: Injection guard mechanism and application

### 4. File Identification & Routing (2 questions)
- Q-004: DIE-based file type detection
- Q-005: Coarse agent invocation and MCP protocol

### 5. Skills & Stage Execution (2 questions)
- Q-006: Skill system and SKILL.md orchestration
- Q-016: Skills installation and runtime path resolution

### 6. Data Models & Architecture (2 questions)
- Q-008: Core data entities and artifact graph
- Q-013: Findings schema and evidence structure

### 7. Analysis Stages & Logic (3 questions)
- Q-010: Stage decision points and cross-stage validation
- Q-012: Dynamic analysis and x64dbg MCP protocol
- Q-014: Report synthesis and claim precedence

### 8. Configuration, Validation & Testing (4 questions)
- Q-011: Configuration schema and bootstrap prerequisites
- Q-015: REST API integration and contracts
- Q-017: Validation pipeline and schema contracts
- Q-020: Test coverage and integration tests

## Key Principles

### Source-Grounded
Every question is motivated by specific implementation details found in the source code. The "Source Evidence" section cites exact file paths, functions, classes, and line numbers. This ensures questions reflect the actual architecture, not assumed or theoretical behavior.

### Actionable Acceptance Criteria
Each criterion is specific and testable:
- "Name all 9 stages with stage_id and skill" — objective and verifiable.
- "Explain the three STATUS values and resumption logic" — demonstrates understanding of a key contract.
- "Provide the exact checkpoint call signature" — prevents vague documentation.

### Not Requiring Source Code
A developer armed with the OpenWiki should be able to answer each question without consulting the source. If they can't, the wiki has a gap.

## Validation Process

To validate the wiki:

1. **Read** each question and acceptance criteria.
2. **Search** the OpenWiki pages for documentation covering the criteria.
3. **Score** against each criterion: ✓ (documented), ✗ (missing), ⚠ (incomplete/unclear).
4. **Prioritize** fixes: address ✗ items first, then ⚠.
5. **Re-validate** after wiki updates.

## Example: Q-001 Validation

**Question**: "Explain the exact sequence of the 9 pipeline stages..."

**Acceptance Criteria**:
1. Name all 9 stages with stage_id and skill.
2. Explain the PURPOSE of STATE.json and Pass 1/Pass 2 distinction.
3. Describe the three STATUS values (running, completed, failed).
4. Provide exact pipeline_state.py commands.
5. Explain MAX_STAGE_ATTEMPTS and its purpose.

**Validation Checklist**:
- ✓ /openwiki/orchestration/launcher.md mentions 9 stages?
- ✓ /openwiki/architecture/pipeline.md defines STATE.json?
- ✓ /openwiki/orchestration/state-management.md explains status values?
- ✗ /openwiki/ documents pipeline_state.py command reference?
- ✓ /openwiki/orchestration/error-recovery.md explains MAX_STAGE_ATTEMPTS?

**Result**: Criterion 4 is missing; the wiki should add a pipeline_state.py reference guide.

## When to Update Questions

The validation questions should be updated when:

1. **Architecture changes**: A new stage is added, or state contract changes.
2. **API changes**: Command-line arguments, environment variables, or MCP protocols change.
3. **Coverage gaps**: A new feature (e.g., new failure state, new agent) appears in source but not in questions.

To update:

1. Identify the changed source file(s) and functions.
2. Write a new question or update an existing one to reflect the change.
3. Add specific line numbers and code citations.
4. Ensure acceptance criteria are testable and source-grounded.

## Related Documentation

- [OpenWiki Quickstart](./quickstart.md) — User-facing quick reference.
- [Launcher Documentation](./orchestration/launcher.md) — Covers Q-001, Q-003, Q-007, Q-018, Q-019.
- [State Management](./orchestration/state-management.md) — Covers Q-001, Q-003.
- [Skill System](./skills/overview.md) — Covers Q-006, Q-016.
- [Data Models](./architecture/data-models.md) — Covers Q-008, Q-013.

## Maintenance

The validation questions are living documentation. They should be reviewed:

1. **After major releases** to ensure the wiki documents all significant changes.
2. **During architectural refactoring** to ensure questions reflect the new structure.
3. **Quarterly** to spot-check wiki accuracy against source.

---

**Last Updated**: 2025 (Generated from source analysis)
**Validation Status**: Initial generation; awaiting wiki updates and re-validation.
