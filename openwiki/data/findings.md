---
type: reference
title: Finding Model and Discovery Lifecycle
description: Finding structure, categories, severity levels, evidence linking, and storage.
tags: [data, findings, model]
---

# Finding Model and Discovery Lifecycle

## Finding Structure

A finding is a normalized analysis result bound to a specific artifact:

```json
{
  "finding_id": "find_001",
  "artifact_id": "art_0001",
  "category": "behavior",
  "severity": "high",
  "title": "Process Injection Detected",
  "description": "The unpacked DLL injects code into a system process (svchost.exe). This is a strong indicator of malicious intent.",
  "evidence": [
    {
      "type": "dynamic",
      "source": "x64dbg breakpoint",
      "data": "CreateRemoteThread called with target process: svchost.exe (PID 4012)"
    },
    {
      "type": "static",
      "source": "IDA disassembly",
      "data": "Calls to kernel32!CreateRemoteThread and kernel32!WriteProcessMemory in sequence"
    }
  ],
  "confidence": 0.95,
  "mitigations": [],
  "references": [],
  "created_at": "2026-01-15T10:35:00Z",
  "source_stage": "dynamic"
}
```

## Field Reference

| Field | Type | Description |
|-------|------|-------------|
| `finding_id` | string | Unique identifier (find_001, find_002, etc.) |
| `artifact_id` | string | Which artifact this finding applies to |
| `category` | string | behavior &#124; obfuscation &#124; config &#124; ioc &#124; capability &#124; anomaly |
| `severity` | string | critical &#124; high &#124; medium &#124; low &#124; info |
| `title` | string | Concise finding description |
| `description` | string | Detailed explanation |
| `evidence` | array | Supporting data with source and type |
| `confidence` | float | 0.0-1.0; operator confidence in finding |
| `mitigations` | array | Suggested responses or control measures |
| `references` | array | External references (CVEs, MITRE ATT&CK, etc.) |
| `created_at` | ISO8601 | When finding was discovered |
| `source_stage` | string | Which stage produced it (identify, unpack, dynamic, etc.) |

## Finding Categories

### behavior

Observed runtime actions (process creation, file writes, network communication):

```json
{
  "finding_id": "find_001",
  "category": "behavior",
  "severity": "high",
  "title": "Network Communication to Suspicious IP",
  "description": "Sample establishes outbound connection to 192.168.1.1:8080",
  "evidence": [
    {
      "type": "dynamic",
      "source": "network traffic capture",
      "data": "TCP connection from 10.0.0.5:54321 to 192.168.1.1:8080"
    }
  ],
  "source_stage": "dynamic"
}
```

### obfuscation

Code or data encryption/obfuscation techniques:

```json
{
  "finding_id": "find_002",
  "category": "obfuscation",
  "severity": "medium",
  "title": "UPX Packing Detected",
  "description": "PE executable is packed with UPX, suggesting intent to hide functionality",
  "evidence": [
    {
      "type": "static",
      "source": "DIE packer detection",
      "data": "UPX 3.96 detected in PE header"
    }
  ],
  "source_stage": "identify"
}
```

### config

Hardcoded configuration, credentials, C&C addresses:

```json
{
  "finding_id": "find_003",
  "category": "config",
  "severity": "critical",
  "title": "Hardcoded C&C Address",
  "description": "PE binary contains hardcoded C&C server URL: http://malware-c2.example.com/beacon",
  "evidence": [
    {
      "type": "static",
      "source": "string extraction",
      "data": "http://malware-c2.example.com/beacon"
    }
  ],
  "source_stage": "static-pass1"
}
```

### ioc

Indicators of compromise (IPs, domains, hashes, file paths):

```json
{
  "finding_id": "find_004",
  "category": "ioc",
  "severity": "high",
  "title": "IOCs Extracted",
  "description": "Multiple indicators extracted for threat hunting",
  "evidence": [
    {
      "type": "extracted",
      "ioc_type": "ip",
      "value": "192.168.1.1"
    },
    {
      "type": "extracted",
      "ioc_type": "domain",
      "value": "malware-c2.example.com"
    }
  ],
  "source_stage": "static-pass1"
}
```

### capability

Malware capabilities (exfiltration, persistence, lateral movement):

```json
{
  "finding_id": "find_005",
  "category": "capability",
  "severity": "critical",
  "title": "Data Exfiltration Capability",
  "description": "Sample exhibits capability to exfiltrate user data via HTTP POST to C&C",
  "evidence": [
    {
      "type": "dynamic",
      "source": "memory strings and network analysis",
      "data": "Constructs HTTP POST requests with compressed file data"
    },
    {
      "type": "static",
      "source": "IDA disassembly",
      "data": "Calls to zlib compression functions followed by HTTP POST"
    }
  ],
  "source_stage": "deepdive"
}
```

### anomaly

Unusual or suspicious patterns:

```json
{
  "finding_id": "find_006",
  "category": "anomaly",
  "severity": "medium",
  "title": "Unusual Entry Point",
  "description": "PE entry point does not align with standard compiler patterns",
  "evidence": [
    {
      "type": "static",
      "source": "IDA analysis",
      "data": "Entry point at offset 0x15000 (unusual; typically 0x1000)"
    }
  ],
  "source_stage": "static-pass1"
}
```

## Severity Levels

| Level | Meaning | Verdict Impact |
|-------|---------|-----------------|
| **critical** | Definitive malicious behavior or capability | Verdict: MALICIOUS |
| **high** | Strong indicator of malicious intent | Verdict: MALICIOUS (with confidence 0.8+) |
| **medium** | Suspicious pattern; requires context | Verdict: SUSPICIOUS (conditional) |
| **low** | Weak indicator; common in benign samples | Verdict: SUSPICIOUS (low confidence) |
| **info** | Informational; not a threat indicator | Verdict: BENIGN (if no critical/high) |

## Evidence Structure

Each finding contains evidence linking to supporting data:

```json
{
  "evidence": [
    {
      "type": "dynamic",
      "source": "x64dbg breakpoint log",
      "timestamp": "2026-01-15T10:35:30Z",
      "data": "Process injection into svchost.exe"
    },
    {
      "type": "static",
      "source": "IDA disassembly annotation",
      "data": "call kernel32!WriteProcessMemory"
    },
    {
      "type": "behavioral",
      "source": "memory analysis",
      "data": "Injected shellcode executes command 'whoami'"
    }
  ]
}
```

## Finding Lifecycle

### 1. Discovery (analysis stages)

Findings are discovered during:
- **02 (static-pass1)**: Initial API calls, imports, strings
- **03 (unpack)**: Packing method and limitations
- **04 (static-pass2)**: Refined static analysis on unpacked artifacts
- **05 (dynamic)**: Observed behaviors during execution
- **06 (intel)**: External reputation data
- **07 (deepdive)**: Reconciled findings and capability mapping

### 2. Consolidation (07-deepdive)

Multiple findings may be merged or reconciled:

```python
def reconcile_conflicting_claims(findings: List[Finding]) -> List[Finding]:
    """Resolve conflicting findings across stages."""
    
    # Group findings by subject
    conflicts = {}
    for finding in findings:
        key = (finding.artifact_id, finding.title)
        if key not in conflicts:
            conflicts[key] = []
        conflicts[key].append(finding)
    
    # Resolve conflicts by confidence and source reliability
    consolidated = []
    for findings_group in conflicts.values():
        if len(findings_group) == 1:
            consolidated.append(findings_group[0])
        else:
            # Multiple findings on same subject
            most_confident = max(findings_group, key=lambda f: f.confidence)
            # Note the conflict
            most_confident.notes = f"Conflict resolved: {len(findings_group)} findings merged"
            consolidated.append(most_confident)
    
    return consolidated
```

### 3. Ranking (07-deepdive)

Findings are ranked by:
1. Severity (critical > high > medium > low > info)
2. Confidence (0.95 > 0.7 > 0.5)
3. Category (behavior > config > obfuscation > ioc > anomaly)

### 4. Report Synthesis (08-report)

Top findings are included in markdown report:

```markdown
## Key Findings

### Critical: Process Injection Detected [HIGH CONFIDENCE: 0.95]
The sample injects code into svchost.exe, a critical system process. This is a strong indicator of malware.

**Evidence**:
- Dynamic: Process injection via CreateRemoteThread (observed in debugger)
- Static: Disassembly shows WriteProcessMemory API calls

### High: Network Communication to Suspicious IP [HIGH CONFIDENCE: 0.92]
Sample connects to 192.168.1.1:8080, an internal IP address used for C&C communication.

**Evidence**:
- Dynamic: Network traffic capture shows TCP connection
- Static: Hardcoded IP address in PE binary
```

### 5. Verdict Assignment (09-summary)

Final verdict is determined by highest-severity findings:

```python
def assign_verdict(findings: List[Finding]) -> tuple[str, float, int]:
    """Assign verdict based on findings."""
    
    critical = [f for f in findings if f.severity == "critical"]
    high = [f for f in findings if f.severity == "high"]
    medium = [f for f in findings if f.severity == "medium"]
    
    if critical or (len(high) >= 3):
        return ("malicious", 0.95, 95)  # verdict, confidence, risk_score
    elif high:
        return ("suspicious", 0.75, 70)
    elif medium:
        return ("suspicious", 0.50, 50)
    else:
        return ("benign", 0.85, 15)
```

## FindingStore

The finding store is a multi-indexed container:

```python
class FindingStore:
    def __init__(self):
        self.by_id = {}            # finding_id → Finding
        self.by_artifact = {}      # artifact_id → [findings]
        self.by_category = {}      # category → [findings]
        self.by_severity = {}      # severity → [findings]
    
    def add(self, finding: Finding):
        """Register finding in all indexes."""
        self.by_id[finding.finding_id] = finding
        
        if finding.artifact_id not in self.by_artifact:
            self.by_artifact[finding.artifact_id] = []
        self.by_artifact[finding.artifact_id].append(finding)
        
        if finding.category not in self.by_category:
            self.by_category[finding.category] = []
        self.by_category[finding.category].append(finding)
        
        if finding.severity not in self.by_severity:
            self.by_severity[finding.severity] = []
        self.by_severity[finding.severity].append(finding)
    
    def get_by_artifact(self, artifact_id: str) -> List[Finding]:
        """Get all findings for an artifact."""
        return self.by_artifact.get(artifact_id, [])
    
    def get_by_category(self, category: str) -> List[Finding]:
        """Get all findings in a category."""
        return self.by_category.get(category, [])
    
    def get_critical_and_high(self) -> List[Finding]:
        """Get all critical and high-severity findings."""
        return self.by_severity.get("critical", []) + self.by_severity.get("high", [])
```

## Related Documentation

- [Artifacts](./artifacts.md) — Artifact model and lineage
- [Response Contract](./response-contract.md) — Finding envelope in public response
- [Architecture Overview](../architecture/overview.md) — System design
- [Stage Dependencies](../architecture/stage-dependencies.md) — How findings flow across stages

