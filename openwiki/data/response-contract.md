---
type: reference
title: Public Response Contract
description: Public response envelope, backward compatibility guarantees, and response structure.
tags: [data, contract, api]
---

# Public Response Contract

## Response Envelope

HyperAgent maintains a backward-compatible public response envelope that ensures legacy callers continue to work:

```json
{
  "run_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "file_path": "/absolute/path/to/sample.exe",
  "detected_type": "NATIVE | DOTNET | PYTHON_SCRIPT | UNKNOWN",
  "die": {
    "file_class": "PE64 | PE32 | .NET | PYINSTALLER | null",
    "packer": "UPX | ASPack | Themida | null",
    "compiler": "Microsoft Visual C++ | GCC | Mono | null",
    "language": "C++ | C | C# | Python | null",
    "library": "kernel32 | msvcrt | null",
    "tool": "IDA | Ghidra | null",
    "malware": "Trojan.Win32.Emotet | null"
  },
  "result": {
    "success": true,
    "payload": { /* varies by agent type */ },
    "findings": [/* Normalized findings */],
    "artifacts": [/* ArtifactNode[] */],
    "iocs": [/* IOC[] */],
    "next_stage_recommendations": [string]
  },
  "artifacts": [
    {
      "artifact_id": "art_0001",
      "path": "/analysis/reports/sha256/extracted/payload.dll",
      "type": "file",
      "sha256": "abcd1234...",
      "parent_artifact_id": null,
      "description": "Primary sample (PE64 native binary)"
    }
  ],
  "findings": [
    {
      "finding_id": "find_001",
      "artifact_id": "art_0001",
      "category": "behavior | obfuscation | config | ioc | capability | anomaly",
      "severity": "critical | high | medium | low | info",
      "title": "Suspicious network connection",
      "description": "Process established outbound TCP connection to 192.168.1.1:8080",
      "evidence": ["network_pcap_excerpt", "behavioral_log_entry"]
    }
  ],
  "iocs": [
    {
      "type": "ip | domain | url | hash | filepath",
      "value": "192.168.1.1 | example.com | http://evil.com/drop | sha256hash | c:\\malware.exe",
      "severity": "high",
      "source": "dynamic_analysis | static_analysis | virustotal"
    }
  ],
  "next_stage_results": [
    {
      "stage": "unpack | dynamic | intel | deepdive",
      "status": "completed | pending | skipped",
      "summary": "Human-readable summary of stage results"
    }
  ],
  "pipeline_log": [
    {
      "timestamp": "2026-01-15T10:30:00Z",
      "stage": "02-static-pass1",
      "event": "Stage completed successfully",
      "details": "..."
    }
  ],
  "verdict": "benign | suspicious | malicious | unknown",
  "risk_score": 75,
  "confidence": 0.95,
  "final_report_markdown": "# Analysis Report\n..."
}
```

## Field Descriptions

### Top-Level Fields

| Field | Type | Description |
|-------|------|-------------|
| `run_id` | UUID | Unique identifier for this analysis run |
| `file_path` | string | Absolute path to analyzed file |
| `detected_type` | string | File type detected (NATIVE, DOTNET, PYTHON_SCRIPT, UNKNOWN) |
| `die` | object | DIE (Detect It Easy) detection output |
| `result` | object | Orchestrator result; structure varies by analysis path |
| `artifacts` | array | Discovered artifacts with metadata |
| `findings` | array | Normalized findings (behavior, config, IOC, etc.) |
| `iocs` | array | Indicators of compromise extracted |
| `next_stage_results` | array | Results from additional stages |
| `pipeline_log` | array | Execution timeline |
| `verdict` | string | Final verdict (benign, suspicious, malicious, unknown) |
| `risk_score` | number | 0-100 risk score |
| `confidence` | number | 0-1 confidence in verdict |
| `final_report_markdown` | string | Synthesized markdown report |

### DIE Object

| Field | Type | Description |
|-------|------|-------------|
| `file_class` | string | PE32, PE64, .NET, PYINSTALLER, etc. |
| `packer` | string | Detected packer (UPX, ASPack, Themida, etc.) |
| `compiler` | string | Detected compiler (MSVC, GCC, Mono, etc.) |
| `language` | string | Primary language (C++, C#, Python, etc.) |
| `library` | string | Notable imported library |
| `tool` | string | Associated tool (IDA, Ghidra, etc.) |
| `malware` | string | Known malware signature (if detected) |

### Finding Object

```json
{
  "finding_id": "find_001",
  "artifact_id": "art_0001",
  "category": "behavior | obfuscation | config | ioc | capability | anomaly",
  "severity": "critical | high | medium | low | info",
  "title": "Brief title",
  "description": "Detailed description",
  "evidence": ["evidence_item_1", "evidence_item_2"]
}
```

**Categories**:
- **behavior**: Runtime action (process creation, file ops, network calls)
- **obfuscation**: Packing, encryption, anti-analysis
- **config**: Embedded credentials, C&C addresses
- **ioc**: Indicators of compromise
- **capability**: Malware capability (exfiltration, evasion, persistence)
- **anomaly**: Unexpected patterns

**Severity Levels**:
- **critical**: Definite malicious behavior
- **high**: Strong indicators of compromise
- **medium**: Suspicious but not conclusive
- **low**: Minor anomalies
- **info**: Informational only

### ArtifactNode Object

```json
{
  "artifact_id": "art_0001",
  "path": "/analysis/reports/sha256/extracted/payload.dll",
  "type": "file | directory | memory | network | behavioral",
  "sha256": "abcd1234...",
  "parent_artifact_id": "art_0000",
  "description": "Unpacked PE64 binary"
}
```

### IOC Object

```json
{
  "type": "ip | domain | url | hash | filepath",
  "value": "192.168.1.1",
  "severity": "critical | high | medium | low",
  "source": "dynamic_analysis | static_analysis | virustotal",
  "context": "Optional context for the IOC"
}
```

## Backward Compatibility

The public envelope is designed to preserve compatibility with existing callers:

1. **Core Fields**: `run_id`, `file_path`, `detected_type`, `die`, `result` are always present
2. **Legacy Format**: `result` object contains coarse-agent payload in original format
3. **Optional Extensions**: New fields (findings, artifacts, iocs, verdict, risk_score) are optional
4. **No Removals**: Existing fields are never removed; only added or extended

### Compatibility Guarantees

- Callers expecting `run_id`, `file_path`, `detected_type` will continue to work
- Callers that parse only the `result` object are unaffected by new top-level fields
- JSON structure is stable; new fields are always additive
- API version remains at 0.1.0 until major breaking changes occur

## Response Examples

### Benign Sample

```json
{
  "run_id": "abc123",
  "file_path": "/tmp/notepad.exe",
  "detected_type": "NATIVE",
  "die": {
    "file_class": "PE64",
    "packer": null,
    "compiler": "Microsoft Visual C++",
    "language": "C++",
    "malware": null
  },
  "result": {
    "success": true,
    "payload": { "verdict": "benign" },
    "findings": []
  },
  "artifacts": [
    {
      "artifact_id": "art_0001",
      "path": "/tmp/notepad.exe",
      "type": "file",
      "sha256": "abc123...",
      "parent_artifact_id": null
    }
  ],
  "findings": [],
  "iocs": [],
  "verdict": "benign",
  "risk_score": 5,
  "confidence": 0.98
}
```

### Malicious Sample

```json
{
  "run_id": "def456",
  "file_path": "/tmp/trojan.exe",
  "detected_type": "NATIVE",
  "die": {
    "file_class": "PE64",
    "packer": "UPX",
    "malware": "Trojan.Win32.Emotet"
  },
  "artifacts": [
    {
      "artifact_id": "art_0001",
      "path": "/tmp/trojan.exe",
      "type": "file",
      "sha256": "def456..."
    },
    {
      "artifact_id": "art_0002",
      "path": "/analysis/unpacked_trojan.exe",
      "type": "file",
      "sha256": "unpacked...",
      "parent_artifact_id": "art_0001"
    }
  ],
  "findings": [
    {
      "finding_id": "find_001",
      "artifact_id": "art_0002",
      "category": "behavior",
      "severity": "critical",
      "title": "Process injection detected",
      "description": "Process injected code into system process (svchost.exe)"
    },
    {
      "finding_id": "find_002",
      "artifact_id": "art_0002",
      "category": "capability",
      "severity": "critical",
      "title": "Botnet capability",
      "description": "Malware communicates with C&C infrastructure"
    }
  ],
  "iocs": [
    {
      "type": "ip",
      "value": "192.168.1.100",
      "severity": "high",
      "source": "dynamic_analysis",
      "context": "C&C communication"
    }
  ],
  "verdict": "malicious",
  "risk_score": 98,
  "confidence": 0.99
}
```

## Versioning Strategy

The contract maintains `api_version: "0.1.0"` at the top level. Changes are classified as:

- **Patch (0.1.1)**: Non-breaking additions to existing fields
- **Minor (0.2.0)**: New optional top-level fields or object extensions
- **Major (1.0.0)**: Breaking changes (removal, reclassification, structural changes)

Current API version 0.1.0 supports unlimited minor/patch additions without breaking existing callers.

## Related Documentation

- [REST API](../api/rest-api.md) — API endpoints that return this envelope
- [Data Models](./artifacts.md) — Artifact and finding details
- [Architecture](../architecture/overview.md) — System design

