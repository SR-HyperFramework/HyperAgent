---
type: reference
title: Agent System Overview
description: Agent taxonomy, coarse vs specialist, routing logic, and execution within pipeline.
tags: [agents, orchestration, routing]
---

# Agent System Overview

## Agent Taxonomy

HyperAgent uses two classes of agents:

### 1. Coarse Agents

**Purpose**: Perform type-specific initial analysis on the primary sample.

**Execution**: Local + Claude-backed child session
- Local phase: File type detection, feature extraction, workspace preparation
- Claude phase: Reasoning-heavy analysis (disassembly interpretation, code patterns)

**Types**:
- **NativeAgent**: x86/x64 PE binaries (native_agent.py)
- **ScriptAgent**: Python bytecode, PyInstaller, shell scripts (script_agent.py)
- **DotNetAgent**: .NET assemblies and CLR payloads (dotnet_agent.py)

**Invoked**: Stage 02-static-pass1, via routing logic in DIE handler

### 2. Specialist Reasoning

**Purpose**: Perform domain-specific analysis across multiple stages.

**Execution**: Claude-backed, integrated into skills

**Techniques** (not separate classes, but reasoning tasks within skills):
- Behavioral analysis (stage 05)
- Obfuscation characterization (stages 04, 07)
- Config extraction (stage 04)
- IOC enrichment (stage 06)
- Capability mapping (stages 07, 08)
- Evidence reconciliation (stage 07)
- Report synthesis (stage 08)
- Verdict assignment (stage 09)

## Routing Logic

### File Type Detection

Coarse agents are selected based on file type detection via DIE (Detect It Easy):

```python
def route_to_agent(die_output: dict) -> str:
    """Route sample to appropriate coarse agent."""
    file_class = die_output.get("file_class")
    
    if file_class in ["PE32", "PE64"]:
        return "native"      # → NativeAgent
    
    if file_class == ".NET":
        return "dotnet"      # → DotNetAgent
    
    if file_class in ["PYINSTALLER", "PYTHON_BYTECODE"]:
        return "script"      # → ScriptAgent
    
    # Fallback: Try all agents
    return "auto"            # → Try script, then native, then dotnet
```

### Invocation Pattern

```python
# In stage 02-static-pass1

# 1. Load sample
sample = load_file(sample_path)

# 2. Run DIE
die_output = run_die(sample_path)

# 3. Route
agent_type = route_to_agent(die_output)

# 4. Invoke coarse agent
if agent_type == "native":
    agent = NativeAgent(config_path)
    result = await agent.analyze(sample_path)
elif agent_type == "dotnet":
    agent = DotNetAgent()
    result = await agent.analyze(sample_path)
elif agent_type == "script":
    agent = ScriptAgent()
    result = await agent.analyze(sample_path)

# 5. Emit findings
emit_findings(result)
```

## Coarse Agent Details

### NativeAgent

**Input**: PE binary path  
**Local Phase**:
- Read PE headers
- Extract sections and imports
- Identify strings (via stripping tools)
- Detect packing (UPX, ASPack, Themida)
- Extract rich header and debug info

**Claude Phase**:
- Interpret disassembly via IDA Pro MCP
- Identify API call patterns
- Detect anti-analysis techniques
- Extract suspicious code sequences

**Output Schema**:
```json
{
  "success": true,
  "file_class": "PE64",
  "arch": "x86_64",
  "sections": [
    {"name": ".text", "size": "...", "entropy": "..."}
  ],
  "imports": ["kernel32.dll", "ntdll.dll"],
  "suspected_packer": "UPX",
  "strings": [/* extracted strings */],
  "findings": [Finding],
  "iocs": [IOC]
}
```

**Dependencies**: IDA Pro (for disassembly); ida-pro-mcp MCP server

### ScriptAgent

**Input**: Python bytecode (.pyc), PyInstaller executable, shell script  
**Local Phase**:
- Detect script type (PyInstaller, Python bytecode, shell)
- Extract bytecode using PyInstaller tools
- Decompile using uncompyle6 or similar

**Claude Phase**:
- Analyze decompiled Python code
- Identify suspicious imports (os, subprocess, ctypes for injections)
- Detect encrypted strings
- Map capabilities

**Output Schema**:
```json
{
  "success": true,
  "script_type": "pyinstaller | python_bytecode | shell",
  "decompiled_code": "...",
  "imports": ["os", "ctypes", "socket"],
  "findings": [Finding],
  "iocs": [IOC]
}
```

**Dependencies**: uncompyle6, pyinstxtractor; Python runtime

### DotNetAgent

**Input**: .NET assembly (.exe, .dll)  
**Local Phase**:
- Read .NET metadata
- Detect obfuscation (dnSpy)
- Extract embedded resources
- Identify imported namespaces

**Claude Phase**:
- Analyze IL (Intermediate Language)
- Identify suspicious method calls
- Detect reflective loading
- Extract hard-coded strings

**Output Schema**:
```json
{
  "success": true,
  "dotnet_version": "4.0.30319",
  "namespaces": ["System.Reflection", "System.Net"],
  "decompiled_methods": [/* key methods */],
  "findings": [Finding],
  "iocs": [IOC]
}
```

**Dependencies**: dnSpy, .NET runtime

## Agent Composition

### Local Preparation

Before invoking Claude:

```python
class NativeAgent:
    async def analyze(self, file_path: str):
        # 1. Local preparation
        self.read_headers(file_path)
        self.extract_strings(file_path)
        self.identify_packing(file_path)
        
        # 2. Prepare Claude context
        context = {
            "file_path": file_path,
            "local_analysis": {
                "headers": self.headers,
                "strings": self.strings[:100],  # Top 100
                "packer": self.packer
            }
        }
        
        # 3. Invoke Claude-backed analysis
        claude_result = await self.run_claude_analysis(context)
        
        # 4. Consolidate results
        return self.consolidate_results(context, claude_result)
```

### Claude-Backed Child Session

Each agent spawns a Claude-backed child session:

```python
async def run_claude_analysis(self, context: dict):
    """Spawn Claude child session for reasoning-heavy analysis."""
    
    # Inject the IDA MCP server for binary analysis
    claude_run = spawn_claude_skill(
        skill_name="hyperagent-native-analysis",
        context=context,
        mcp_servers=["ida-pro-mcp"],  # IDA available via MCP
        system_prompt=ANALYSIS_PROMPT + INJECTION_GUARD
    )
    
    return await claude_run.complete()
```

The child session:
- Has access to IDA Pro via ida-pro-mcp MCP server
- Can run arbitrary analysis and reasoning
- Returns structured findings
- Is separate from the main pipeline (parent-child task relationship)

## Specialist Reasoning (Not Separate Agents)

Specialist analysis capabilities are **not separate agent classes** but rather **reasoning techniques within skills**:

| Technique | Implemented In | Stage | Reasoning Type |
|-----------|-----------------|-------|-----------------|
| Behavioral analysis | hyperagent-dynamic | 05 | Process/network analysis interpretation |
| Obfuscation characterization | hyperagent-static, hyperagent-deepdive | 04, 07 | Pattern recognition (packing, encryption) |
| Config extraction | hyperagent-static | 04 | String analysis, structure inference |
| IOC enrichment | hyperagent-intel | 06 | External API querying and normalization |
| Capability mapping | hyperagent-deepdive | 07 | Evidence-based capability attribution |
| Evidence reconciliation | hyperagent-deepdive | 07 | Multi-source claim resolution |
| Report synthesis | hyperagent-report | 08 | Narrative generation |
| Verdict assignment | hyperagent-summary | 09 | Risk scoring and classification |

These are implemented as Claude reasoning tasks within each skill's SKILL.md, not as separate agent classes.

## Execution Flow Diagram

```
Sample File
    ↓
[02: Static Pass 1]
    ↓
[DIE Detection]
    ↓
[Routing Decision] → NATIVE | DOTNET | SCRIPT
    ├─→ NativeAgent
    │   ├─ Local: Headers, strings, packing
    │   ├─ Claude: IDA disassembly, API patterns
    │   └─ Output: Findings, IOCs
    ├─→ DotNetAgent
    │   ├─ Local: Metadata, namespaces
    │   ├─ Claude: IL analysis, reflection
    │   └─ Output: Findings, IOCs
    └─→ ScriptAgent
        ├─ Local: Decompilation
        ├─ Claude: Code analysis, imports
        └─ Output: Findings, IOCs
    ↓
[Consolidate Findings]
    ↓
[Next-Stage Recommendations]
    ↓
[Decision: Unpack? Dynamic?]
```

## Integration with Pipeline

Agents are invoked **only during stage 02-static-pass1**. Their findings feed into:

- **Stage 03** (unpack): If packing detected
- **Stage 04** (static-pass2): Refinement and cross-artifact analysis
- **Stage 05** (dynamic): Behavior hypothesis testing
- **Stages 06-09**: Evidence consolidation and verdict

## Related Documentation

- [Routing & Dispatch](./routing-and-dispatch.md) — DIE integration and agent selection
- [Coarse Agents](./coarse-agents.md) — Detailed NativeAgent, ScriptAgent, DotNetAgent
- [Architecture Overview](../architecture/overview.md) — System design
- [Pipeline Details](../architecture/pipeline.md) — Stage-by-stage execution

