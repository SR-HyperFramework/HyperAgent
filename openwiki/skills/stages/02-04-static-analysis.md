---
type: reference
title: Static Analysis Pipeline (Stages 02 & 04)
description: File identification, routing, coarse agent analysis, and payload extraction across static passes.
tags: [skills, stages, static-analysis]
---

# Static Analysis Pipeline (Stages 02, 03, 04)

## Overview

The static analysis pipeline consists of three stages:

| Stage | Skill | Purpose |
|-------|-------|---------|
| **02** | hyperagent-static | Identify file type, route to coarse agent, extract initial findings |
| **03** | hyperagent-unpack | Extract and decompose payloads (UPX, PyInstaller, .NET) |
| **04** | hyperagent-static | Re-analyze unpacked artifacts, refine findings |

## Stage 02: Static Pass 1

### Execution Flow

```
Input: Sample file
   ↓
[Identify] Run DIE → file_class, compiler, packer, etc.
   ↓
[Route] Select agent based on file type
   ├─ NATIVE → NativeAgent (IDA Pro disassembly)
   ├─ DOTNET → DotNetAgent (IL decompilation)
   └─ PYTHON_SCRIPT → ScriptAgent (bytecode decompilation)
   ↓
[Agent] Execute selected agent
   └─ Extract APIs, strings, imports
   └─ Detect behavioral indicators
   └─ Invoke Claude for reasoning
   ↓
[Next-stage hunting] Recommend unpacking or dynamic
   ↓
Output: findings, artifacts, recommendations
```

### Output Schema

```json
{
  "status": "completed",
  "findings": [
    {
      "finding_id": "find_001",
      "artifact_id": "art_0000",
      "category": "obfuscation",
      "severity": "medium",
      "title": "UPX Packing Detected",
      "description": "PE executable is packed with UPX 3.96",
      "source_stage": "identify"
    }
  ],
  "artifacts": [
    {
      "artifact_id": "art_0000",
      "path": "/absolute/path/to/sample.exe",
      "type": "file",
      "sha256": "abc123...",
      "parent_artifact_id": null,
      "size_bytes": 102400
    }
  ],
  "identified_type": "NATIVE",
  "die_output": {
    "file_class": "PE64",
    "compiler": "Microsoft Visual C++ 14.0",
    "packer": "UPX 3.96"
  },
  "agent_results": {
    "agent_type": "native",
    "apis": [...],
    "indicators": [...]
  },
  "recommend_next_stage": "03-unpack"
}
```

## Stage 03: Unpack

### Purpose

Extracts and decomposes packed payloads:
- **UPX**: UPX unpacking
- **PyInstaller**: Archive extraction and bytecode decompilation
- **.NET assemblies**: IL extraction and obfuscation removal

### Execution Flow

```
Input: Packed sample (from stage 02)
   ↓
[Detect packing method] Check packing headers
   ├─ UPX → run upx -d
   ├─ PyInstaller → run PyInstaller_Extractor
   └─ .NET → extract IL via dnSpy/ILSpy
   ↓
[Extract] Unpack or decompress
   ↓
[Validate] Verify extracted artifact is valid binary/script
   ↓
[Register] Add unpacked artifact to artifact graph (parent: original)
   ↓
Output: extracted_artifacts[], repair_notes
```

### Output Schema

```json
{
  "status": "completed",
  "extracted_artifacts": [
    {
      "artifact_id": "art_0001",
      "path": "/absolute/path/to/unpacked.bin",
      "type": "file",
      "sha256": "def456...",
      "parent_artifact_id": "art_0000",
      "packing_method": "UPX 3.96",
      "extraction_status": "success",
      "repair_notes": "Unpacked at OEP 0x1000; no relocations"
    },
    {
      "artifact_id": "art_0002",
      "path": "/absolute/path/to/extracted.py",
      "type": "file",
      "sha256": "ghi789...",
      "parent_artifact_id": "art_0000",
      "packing_method": "PyInstaller 5.1",
      "extraction_status": "success",
      "repair_notes": "Extracted from archive; bytecode intact"
    }
  ],
  "findings": [
    {
      "finding_id": "find_002",
      "artifact_id": "art_0001",
      "category": "obfuscation",
      "severity": "low",
      "title": "UPX Packing Removed",
      "description": "Successfully unpacked UPX-packed executable. Integrity verified.",
      "source_stage": "unpack"
    }
  ],
  "recommend_next_stage": "04-static-pass2"
}
```

## Stage 04: Static Pass 2

### Purpose

Re-analyzes unpacked artifacts from stage 03 to discover hidden indicators:

- Analysis of unpacked binaries (without packing obfuscation)
- Decompiled source code analysis
- Refined behavioral indicator detection

### Execution Flow

```
Input: Unpacked artifacts (from stage 03)
   ↓
[For each artifact]:
   ├─ Run DIE on unpacked artifact
   ├─ Select agent based on file type
   ├─ Execute agent analysis (IDA, decompiler, etc.)
   ├─ Extract refined findings (now without packing confusion)
   └─ Invoke Claude for reasoning
   ↓
[Findings consolidation]
   ├─ Merge Pass 1 and Pass 2 findings
   ├─ Resolve conflicts (prioritize Pass 2 for unpacked)
   └─ Update severity/confidence based on unpacked analysis
   ↓
[Next-stage hunting] Recommend dynamic or intel
   ↓
Output: consolidated_findings, artifacts, recommendations
```

### Output Schema

```json
{
  "status": "completed",
  "pass_number": 2,
  "analyzed_artifacts": ["art_0001", "art_0002"],
  "findings": [
    {
      "finding_id": "find_003",
      "artifact_id": "art_0001",
      "category": "capability",
      "severity": "high",
      "title": "Code Injection via CreateRemoteThread",
      "description": "Unpacked binary contains calls to CreateRemoteThread and WriteProcessMemory, indicating process injection capability.",
      "confidence": 0.95,
      "source_stage": "static-pass2",
      "evidence": [
        {
          "type": "static",
          "source": "IDA disassembly of unpacked binary",
          "data": "call kernel32!CreateRemoteThread; call kernel32!WriteProcessMemory"
        }
      ]
    },
    {
      "finding_id": "find_004",
      "artifact_id": "art_0002",
      "category": "capability",
      "severity": "high",
      "title": "System Command Execution",
      "description": "Python script imports subprocess and calls subprocess.run() with shell commands.",
      "confidence": 0.92,
      "source_stage": "static-pass2"
    }
  ],
  "consolidated_findings_count": 6,
  "recommend_next_stage": "05-dynamic"
}
```

## Artifact Graph Formation

The three static stages form the artifact graph:

```
Original Sample (art_0000)
├─ Pass 1 findings: [obfuscation, APIs]
├─ Packing detected: UPX
└─ Child: Unpacked Binary (art_0001)
   ├─ Pass 2 findings: [process injection, C&C]
   └─ No children
```

This allows:
- Tracking analysis lineage
- Associating findings with correct artifact
- Deduplication (same file in multiple paths)

## Configuration

Static analysis is configured via `config.yaml`:

```yaml
stages:
  static-pass1:
    timeout_s: 600
    context_limit_s: 180000  # 80% of 200K context window
    max_attempts: 3
  
  unpack:
    supported_methods: [upx, pyinstaller, dotnet]
    timeout_s: 300
  
  static-pass2:
    timeout_s: 600
    context_limit_s: 180000
    max_attempts: 3
    
tools:
  diec: "diec.exe"
  upx: "upx.exe"
  pyinstaller_extractor: "./resource/pyinstxtractor/pyinstxtractor.py"

agents:
  native:
    ida_startup_timeout_s: 180
```

## Related Documentation

- [Agents Overview](../../agents/overview.md) — Coarse agent taxonomy
- [Coarse Agents](../../agents/coarse-agents.md) — NativeAgent, ScriptAgent, DotNetAgent
- [Routing & Dispatch](../../agents/routing-and-dispatch.md) — DIE and agent selection
- [Stage Dependencies](../../architecture/stage-dependencies.md) — Cross-stage data flow
- [Dynamic Analysis (Stage 05)](./05-dynamic-analysis.md) — Next stage after pass 2

