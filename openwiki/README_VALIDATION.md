---
type: "Reference"
title: "HyperAgent Wiki Validation Suite"
openwiki_generated: true
---

# HyperAgent Wiki Validation Suite

This directory contains a comprehensive validation suite for ensuring the HyperAgent OpenWiki accurately and completely documents the codebase.

## Quick Reference

| Document | Purpose |
|----------|---------|
| [`wiki-validation-questions.md`](./wiki-validation-questions.md) | **20 source-grounded questions** testing wiki completeness (Q-001 to Q-020) |
| [`VALIDATION_METHODOLOGY.md`](./VALIDATION_METHODOLOGY.md) | **How to use** the validation questions and interpret results |
| [`COVERAGE_ANALYSIS.md`](./COVERAGE_ANALYSIS.md) | **Gap analysis** showing which topics are well-documented and where improvements are needed |
| [`README_VALIDATION.md`](./README_VALIDATION.md) | This file — navigation and summary |

## What Are These Documents?

### Wiki Validation Questions
A set of **20 detailed questions** that a developer should be able to answer using **only the OpenWiki** (without reading source code). Each question:

- **Tests a specific architectural concept** (pipeline sequencing, state management, agent routing, etc.)
- **Has 3–5 concrete acceptance criteria** showing exactly what the wiki must document
- **Cites source evidence** with exact file paths, class names, and line numbers

These are **not** questions to ask users. They are **verification criteria** for wiki completeness.

### Validation Methodology
Explains:
- How the questions were generated (source-grounded approach)
- How to use them to validate the wiki
- Coverage areas and principles
- When and how to update questions

### Coverage Analysis
A detailed audit showing:
- Which topics are **well-documented** (✓)
- Which topics are **incomplete** (⚠)
- Which topics are **missing** (✗)
- Specific recommendations for each gap
- Estimated effort to close gaps (4–5 weeks)

---

## The 20 Validation Questions at a Glance

| # | Question | Topic | Status |
|----|----------|-------|--------|
| Q-001 | 9-stage pipeline and STATE.json contract | Orchestration | ⚠ Partial |
| Q-002 | Injection guard mechanism | Safety | ⚠ Incomplete |
| Q-003 | Context checkpointing and resumption | State Mgmt | ⚠ Partial |
| Q-004 | File type detection via DIE | Routing | ✗ Missing DIE details |
| Q-005 | Coarse agent invocation and MCP | Agents | ⚠ Incomplete MCP |
| Q-006 | Skill system and SKILL.md contract | Skills | ✓ Good |
| Q-007 | Error recovery and failure states | Error Handling | ✓ Good |
| Q-008 | Core data models and artifact graph | Data Models | ✓ Good |
| Q-009 | End-to-end execution flow | Workflow | ✗ Missing |
| Q-010 | Stage decision points (unpack, static-pass2) | Logic | ⚠ Incomplete |
| Q-011 | Configuration schema and bootstrap | Setup | ⚠ Incomplete |
| Q-012 | Dynamic analysis and x64dbg MCP | Analysis | ✗ x64dbg MCP sparse |
| Q-013 | Findings schema and evidence | Data Models | ✓ Good |
| Q-014 | Report synthesis and claim precedence | Report | ✓ Good |
| Q-015 | REST API integration | API | ✓ Good |
| Q-016 | Skills installation and path resolution | Setup | ✗ Missing |
| Q-017 | Validation pipeline and schema contracts | Testing | ✓ Good |
| Q-018 | Batch processing and failure handling | Orchestration | ⚠ Incomplete |
| Q-019 | Launcher CLI arguments | Orchestration | ⚠ Incomplete |
| Q-020 | Test coverage and integration tests | Testing | ⚠ Sparse |

**Summary**: ~65% of topics well-documented; 35% have gaps or missing details (mostly MCP protocols and implementation details).

---

## How to Use These Documents

### For Wiki Validation (Reviewers)
1. Open [`wiki-validation-questions.md`](./wiki-validation-questions.md)
2. For each question, search the wiki for documentation of the acceptance criteria
3. Mark each criterion: ✓ (documented), ⚠ (incomplete), ✗ (missing)
4. Use [`COVERAGE_ANALYSIS.md`](./COVERAGE_ANALYSIS.md) to prioritize which gaps to fix
5. Plan wiki updates using the "Recommendations" section in COVERAGE_ANALYSIS

### For Wiki Authors (Documentation)
1. Read [`COVERAGE_ANALYSIS.md`](./COVERAGE_ANALYSIS.md) to see which topics need work
2. Start with "High Priority" gaps (DIE integration, MCP protocols, skill system details)
3. Reference the "Source Evidence" sections in validation questions to see what source code documents the topic
4. Add documentation to the wiki, ensuring it satisfies the acceptance criteria
5. Validate updates by re-checking the corresponding questions

### For Developers (Learning)
1. If you need to understand a topic, find the corresponding validation question (e.g., Q-006 for skills)
2. Check if the wiki has the acceptance criteria documented
3. If not, read the "Source Evidence" section to find the source code to study
4. This gives you both wiki documentation AND exact code locations

---

## High-Priority Gaps (Start Here)

Based on the coverage analysis, these topics need immediate documentation:

1. **DIE (Detect It Easy) Integration** (Q-004)
   - Missing: DIE command-line interface, output parsing, routing logic
   - Wiki location: `/openwiki/integration/die.md` (may be sparse)
   - Estimated effort: 1–2 days

2. **x64dbg MCP Protocol** (Q-012)
   - Missing: x64dbg MCP tools, workflow, subagent delegation, readiness probe
   - Wiki location: `/openwiki/integration/x64dbg-mcp.md` (needs expansion)
   - Estimated effort: 2–3 days

3. **Coarse Agent Invocation and MCP** (Q-005)
   - Missing: Async entry points, agent selection, MCP communication
   - Wiki location: `/openwiki/agents/coarse-agents.md` (incomplete)
   - Estimated effort: 1–2 days

4. **Skill System and SKILL.md Structure** (Q-006)
   - Missing: Detailed SKILL.md sections, environment variable injection, examples
   - Wiki location: Needs new `/openwiki/skills/skill-md-reference.md`
   - Estimated effort: 1–2 days

5. **Configuration and Bootstrap** (Q-011)
   - Missing: Complete config.yaml schema, all environment variables, bootstrap walkthrough
   - Wiki location: `/openwiki/setup/configuration.md` (incomplete)
   - Estimated effort: 1 day

**Total for high-priority gaps**: ~1 week

---

## How Questions Are Source-Grounded

Every validation question cites specific source code evidence. For example, Q-001 cites:

```
/claude_spawn.py:STAGES (lines 28-38)
/claude_spawn.py:MAX_STAGE_ATTEMPTS (line 43)
/skill/backup/hyperagent-malware-analyze/v3/hyperagent-static/SKILL.md
  (State / Resume Contract section)
```

This ensures:
- Questions reflect **actual** architecture, not assumptions
- Answers can be **verified** against source code
- Gaps are **actionable** (specific wiki files and topics to update)

---

## Validation Workflow

```
1. Start → Review wiki-validation-questions.md
2. For each question:
   - Search OpenWiki for acceptance criteria
   - Mark coverage (✓ / ⚠ / ✗)
3. Consult COVERAGE_ANALYSIS.md
4. Prioritize high-impact gaps
5. Update wiki to satisfy acceptance criteria
6. Re-validate to confirm fix
7. Repeat until all gaps closed
```

---

## Key Principles

### Source-Grounded
Questions are motivated by specific code findings, ensuring relevance and accuracy.

### Testable Acceptance Criteria
Each criterion is concrete and verifiable, preventing vague documentation.

### No Source Code Required
A developer armed with the wiki should answer each question without consulting source.

### Living Documentation
Questions and coverage analysis should be updated as the codebase evolves.

---

## Related Documentation

- **Quickstart**: [`/openwiki/quickstart.md`](./quickstart.md) — User-facing introduction
- **Architecture**: [`/openwiki/architecture/`](./architecture/) — Core system design
- **Orchestration**: [`/openwiki/orchestration/`](./orchestration/) — Pipeline execution and state
- **Skills & Stages**: [`/openwiki/skills/`](./skills/) — Stage implementation
- **Integration**: [`/openwiki/integration/`](./integration/) — External tool integration (DIE, IDA, x64dbg)
- **Setup**: [`/openwiki/setup/`](./setup/) — Installation and configuration

---

## Questions or Updates?

If you find:
- **New gaps** in the wiki → Add a validation question (follow the format in wiki-validation-questions.md)
- **Architecture changes** in source → Update corresponding validation questions and coverage analysis
- **Completed documentation** → Mark as ✓ in COVERAGE_ANALYSIS.md

---

**Generated**: 2025 (Based on source code analysis)
**Scope**: 20 questions across 8 architectural domains
**Current Wiki Quality**: 65% complete; well-documented architecture, sparse on implementation details

For detailed information, see:
- 📋 [`wiki-validation-questions.md`](./wiki-validation-questions.md) — All 20 questions with acceptance criteria
- 📊 [`COVERAGE_ANALYSIS.md`](./COVERAGE_ANALYSIS.md) — Gap analysis and recommendations
- 🔍 [`VALIDATION_METHODOLOGY.md`](./VALIDATION_METHODOLOGY.md) — How to use these documents
