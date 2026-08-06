---
type: reference
title: Data Models and Entity Definitions
description: TaskSession, RunContext, ArtifactNode, Finding, AgentResult, and supporting data structures.
tags: [data, models, entities]
---

# Data Models and Entity Definitions

## Core Entities

### TaskSession

Represents a single traceable work unit within a run.

```python
@dataclass
class TaskSession:
    task_id: str                           # Unique identifier (UUID)
    session_id: str                        # Session/transaction ID
    run_id: str                            # Parent run ID
    parent_task_id: Optional[str]          # Enables task hierarchies
    
    stage_key: str                         # identify|route|agent|next_stage|report|...
    title: str                             # Human-readable name
    description: str                       # Detailed description
    summary: str                           # Outcome summary
    
    status: str                            # pending|processing|completed
    terminal_state: Optional[str]          # success|failed|skipped|cancelled
    executor_kind: str                     # local|claude
    
    artifact_id: Optional[str]             # Associated artifact (if any)
    
    created_at: datetime                   # When task was created
    started_at: Optional[datetime]         # When execution started
    finished_at: Optional[datetime]        # When execution ended
    
    def is_terminal(self) -> bool:
        return self.status == "completed"
```

**Example**:
```json
{
  "task_id": "task_abc123",
  "session_id": "session_xyz789",
  "run_id": "run_001",
  "parent_task_id": null,
  "stage_key": "identify",
  "title": "File Type Identification",
  "description": "Run DIE to identify file type and properties",
  "summary": "Identified as PE64 native executable",
  "status": "completed",
  "terminal_state": "success",
  "executor_kind": "local",
  "artifact_id": "art_0000",
  "created_at": "2026-01-15T10:35:00Z",
  "started_at": "2026-01-15T10:35:01Z",
  "finished_at": "2026-01-15T10:35:05Z"
}
```

### RunContext

Context object passed through the pipeline.

```python
@dataclass
class RunContext:
    run_id: str                            # Unique run identifier
    session_id: str                        # Current session ID
    task_id: str                           # Current task ID
    
    file_path: str                         # Original sample path
    file_hash: str                         # SHA256 of sample
    
    analysis_type: str                     # NATIVE|DOTNET|PYTHON_SCRIPT|UNKNOWN
    
    analysis_dir: str                      # ~/reports/{run_id}/
    state_path: str                        # ~/reports/{run_id}/STATE.json
    progress_path: Optional[str]           # ~/reports/{run_id}/_state/{stage_id}.progress.md
    
    stage_id: str                          # Current stage ID (01-prepare-env, etc)
    stage_output_path: str                 # ~/reports/{run_id}/{stage_id}.json
    
    # Optional: MCP servers needed
    mcp_servers: List[str]                 # [ida-pro-mcp, x64dbg-mcp, ...]
    
    def to_env_dict(self) -> dict:
        """Convert to environment variables for subprocess."""
        return {
            "HYPERAGENT_RUN_ID": self.run_id,
            "HYPERAGENT_SESSION_ID": self.session_id,
            "HYPERAGENT_TASK_ID": self.task_id,
            "HYPERAGENT_ANALYSIS_DIR": self.analysis_dir,
            "HYPERAGENT_STATE_PATH": self.state_path,
            "HYPERAGENT_STAGE_ID": self.stage_id,
            "HYPERAGENT_STAGE_OUTPUT_PATH": self.stage_output_path,
        }
```

### ArtifactNode

Represents a file or directory in the artifact graph.

```python
@dataclass
class ArtifactNode:
    artifact_id: str                       # Unique identifier
    path: str                              # Absolute filesystem path
    type: str                              # file|directory|memory|network|behavioral
    
    sha256: Optional[str]                  # Content hash
    size_bytes: Optional[int]              # File size
    
    parent_artifact_id: Optional[str]      # Parent in lineage (for unpacked items)
    source_stage: str                      # Stage that created this artifact
    
    # Metadata
    description: Optional[str]             # Human-readable description
    extracted_from: Optional[str]          # e.g., "UPX packing", "PyInstaller archive"
    
    def is_child_of(self, other_id: str) -> bool:
        return self.parent_artifact_id == other_id
```

**Example: Unpacked artifact**:
```json
{
  "artifact_id": "art_0001",
  "path": "/reports/abc123/unpacked/sample_unpacked.bin",
  "type": "file",
  "sha256": "def456...",
  "size_bytes": 65536,
  "parent_artifact_id": "art_0000",
  "source_stage": "unpack",
  "description": "Unpacked executable (original was UPX-packed)",
  "extracted_from": "UPX 3.96"
}
```

### Finding

Normalized analysis result bound to an artifact.

```python
@dataclass
class Finding:
    finding_id: str                        # Unique identifier
    artifact_id: str                       # Associated artifact
    
    category: str                          # behavior|obfuscation|config|ioc|capability|anomaly
    severity: str                          # critical|high|medium|low|info
    confidence: Optional[float]            # 0.0-1.0 confidence in finding
    
    title: str                             # Brief title
    description: str                       # Full description
    
    source_stage: str                      # Stage that produced finding
    source_agent: Optional[str]            # Agent type (native|script|dotnet)
    
    # Evidence chain
    evidence: List[Dict[str, Any]]         # Supporting evidence
    
    created_at: datetime                   # When finding was created
    
    def __init__(self, ...):
        self.confidence = confidence if confidence is not None else 0.5
```

**Example: Process injection finding**:
```json
{
  "finding_id": "find_003",
  "artifact_id": "art_0001",
  "category": "behavior",
  "severity": "high",
  "confidence": 0.95,
  "title": "Code Injection via CreateRemoteThread",
  "description": "Binary contains calls to CreateRemoteThread and WriteProcessMemory, indicating process injection capability.",
  "source_stage": "static-pass2",
  "source_agent": "native",
  "evidence": [
    {
      "type": "static",
      "source": "IDA Pro disassembly",
      "data": "0x401234: call kernel32!CreateRemoteThread"
    },
    {
      "type": "behavioral",
      "source": "API extraction",
      "data": "Calls: kernel32.CreateRemoteThread, kernel32.WriteProcessMemory, kernel32.GetProcAddress"
    }
  ],
  "created_at": "2026-01-15T10:37:00Z"
}
```

### Stage

Represents a pipeline stage configuration.

```python
@dataclass(frozen=True)
class Stage:
    stage_id: str                          # Unique stage ID (01-prepare-env, etc)
    skill: str                             # Skill name (hyperagent-prepare-env, etc)
    reads_sample_content: bool             # If True, inject INJECTION_GUARD
    
    def __repr__(self) -> str:
        return f"Stage({self.stage_id}, {self.skill})"

# Canonical stage table from claude_spawn.py
STAGES = (
    Stage("01-prepare-env", "hyperagent-prepare-env", reads_sample_content=False),
    Stage("02-static-pass1", "hyperagent-static", reads_sample_content=True),
    Stage("03-unpack", "hyperagent-unpack", reads_sample_content=True),
    Stage("04-static-pass2", "hyperagent-static", reads_sample_content=True),
    Stage("05-dynamic", "hyperagent-dynamic", reads_sample_content=True),
    Stage("06-intel", "hyperagent-intel", reads_sample_content=True),
    Stage("07-deepdive", "hyperagent-deepdive", reads_sample_content=True),
    Stage("08-report", "hyperagent-report", reads_sample_content=False),
    Stage("09-summary", "hyperagent-summary", reads_sample_content=False),
)
```

## Support Structures

### ArtifactRegistry

Index for artifact lookups.

```python
class ArtifactRegistry:
    def __init__(self):
        self.by_id: Dict[str, ArtifactNode] = {}
        self.by_path: Dict[str, str] = {}  # path → artifact_id
        self.by_hash: Dict[str, str] = {}  # sha256 → artifact_id
        self.by_parent: Dict[str, List[str]] = {}  # parent_id → [child_ids]
    
    def register(self, artifact: ArtifactNode):
        """Register artifact in all indexes."""
        self.by_id[artifact.artifact_id] = artifact
        self.by_path[artifact.path] = artifact.artifact_id
        
        if artifact.sha256:
            self.by_hash[artifact.sha256] = artifact.artifact_id
        
        if artifact.parent_artifact_id:
            if artifact.parent_artifact_id not in self.by_parent:
                self.by_parent[artifact.parent_artifact_id] = []
            self.by_parent[artifact.parent_artifact_id].append(artifact.artifact_id)
    
    def get_by_id(self, artifact_id: str) -> Optional[ArtifactNode]:
        return self.by_id.get(artifact_id)
    
    def get_children(self, parent_id: str) -> List[ArtifactNode]:
        child_ids = self.by_parent.get(parent_id, [])
        return [self.by_id[cid] for cid in child_ids if cid in self.by_id]
    
    def get_by_hash(self, sha256: str) -> Optional[ArtifactNode]:
        artifact_id = self.by_hash.get(sha256)
        return self.by_id.get(artifact_id) if artifact_id else None
```

### FindingStore

Findings keyed by artifact.

```python
class FindingStore:
    def __init__(self):
        self.by_artifact: Dict[str, List[Finding]] = {}
        self.by_category: Dict[str, List[Finding]] = {}
        self.by_severity: Dict[str, List[Finding]] = {}
    
    def add(self, finding: Finding):
        """Register finding in all indexes."""
        
        # By artifact
        if finding.artifact_id not in self.by_artifact:
            self.by_artifact[finding.artifact_id] = []
        self.by_artifact[finding.artifact_id].append(finding)
        
        # By category
        if finding.category not in self.by_category:
            self.by_category[finding.category] = []
        self.by_category[finding.category].append(finding)
        
        # By severity
        if finding.severity not in self.by_severity:
            self.by_severity[finding.severity] = []
        self.by_severity[finding.severity].append(finding)
    
    def get_for_artifact(self, artifact_id: str) -> List[Finding]:
        return self.by_artifact.get(artifact_id, [])
    
    def get_by_category(self, category: str) -> List[Finding]:
        return self.by_category.get(category, [])
    
    def get_critical() -> List[Finding]:
        return self.by_severity.get("critical", [])
```

### WorkQueue

Priority queue for next-stage analysis.

```python
@dataclass(order=True)
class WorkItem:
    priority: int                          # Numeric priority score
    artifact_id: str = field(compare=False)
    stage_key: str = field(compare=False)  # 03-unpack|05-dynamic|06-intel|07-deepdive
    reason: str = field(compare=False)     # Why is this stage recommended

class WorkQueue:
    def __init__(self):
        self.queue: List[WorkItem] = []
    
    def enqueue(self, artifact_id: str, stage_key: str, reason: str, priority: int):
        """Add work item to queue."""
        item = WorkItem(priority=priority, artifact_id=artifact_id, stage_key=stage_key, reason=reason)
        heapq.heappush(self.queue, item)
    
    def dequeue(self) -> Optional[WorkItem]:
        """Remove and return highest-priority item."""
        return heapq.heappop(self.queue) if self.queue else None
    
    def is_empty(self) -> bool:
        return len(self.queue) == 0

# Priority scoring
def calculate_priority(finding: Finding, stage_key: str) -> int:
    """Calculate priority for work item."""
    
    severity_scores = {
        "critical": 100,
        "high": 80,
        "medium": 60,
        "low": 40,
        "info": 20
    }
    
    category_scores = {
        "obfuscation": 10,  # +10 if unpack needed
        "behavior": 20,     # +20 if dynamic needed
        "capability": 15,   # +15 if deepdive needed
    }
    
    base_score = severity_scores.get(finding.severity, 0)
    category_bonus = category_scores.get(finding.category, 0)
    confidence_bonus = int(finding.confidence * 20) if finding.confidence else 10
    
    return base_score + category_bonus + confidence_bonus
```

## Agent Result Structure

```python
@dataclass
class AgentResult:
    success: bool                          # Did agent complete?
    agent_type: str                        # native|script|dotnet
    
    findings: List[Finding]                # Structured findings
    artifacts: List[ArtifactNode]          # Discovered artifacts
    iocs: List[Dict[str, str]]             # IOC extractions
    
    # Legacy payload (optional)
    payload: Optional[Dict[str, Any]]      # Original agent output format
    
    raw_output: Optional[str]              # Raw agent stdout
    error: Optional[str]                   # If success=False
```

## Response Envelopes

### RunSnapshot (Compatibility Projection)

```python
@dataclass
class RunSnapshot:
    run_id: str
    file_path: str
    detected_type: str
    
    die: Dict[str, Any]                   # DIE output
    result: Dict[str, Any]                # Coarse agent result
    
    next_stage_results: List[Dict[str, Any]]
    pipeline_log: List[str]
    
    artifacts: List[Dict[str, Any]]
    findings: List[Dict[str, Any]]
    iocs: List[Dict[str, Any]]
    
    verdict: Optional[str]                # benign|suspicious|malicious|unknown
    final_report_markdown: Optional[str]
    
    created_at: datetime
    completed_at: Optional[datetime]
```

### TaskSnapshot (Live Observability)

```python
@dataclass
class TaskSnapshot:
    tasks: List[TaskSession]
    
    # Derived fields for UI
    pending_count: int
    processing_count: int
    completed_count: int
    
    by_stage: Dict[str, List[TaskSession]]  # Grouped by stage_key
    timeline: List[TaskSession]             # Chronologically ordered
```

## Related Documentation

- [Architecture Overview](./overview.md) — How these models fit in the system
- [Response Contract](../data/response-contract.md) — Public response formats
- [Artifacts](../data/artifacts.md) — Artifact graph and lineage
- [Findings](../data/findings.md) — Finding categories and severity

