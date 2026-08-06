---
type: reference
title: Artifact Model and Lineage
description: ArtifactNode structure, parent/child relationships, artifact types, and registry indexing.
tags: [data, artifacts, model]
---

# Artifact Model and Lineage

## ArtifactNode Structure

An artifact represents a file, directory, memory region, or behavioral observation discovered during analysis:

```json
{
  "artifact_id": "art_0001",
  "path": "/analysis/reports/sha256/primary.exe",
  "type": "file",
  "sha256": "abcd1234ef5678...",
  "parent_artifact_id": null,
  "size_bytes": 524288,
  "description": "Primary sample submitted for analysis",
  "source_stage": "request",
  "created_at": "2026-01-15T10:30:00Z"
}
```

## Field Reference

| Field | Type | Description |
|-------|------|-------------|
| `artifact_id` | string | Unique identifier (art_0001, art_0002, etc.) |
| `path` | string | Absolute or relative path to artifact |
| `type` | string | file &#124; directory &#124; memory &#124; network &#124; behavioral |
| `sha256` | string &#124; null | SHA256 hash (for files) |
| `parent_artifact_id` | string &#124; null | ID of parent artifact (if extracted/derived) |
| `size_bytes` | integer &#124; null | File size in bytes |
| `description` | string | Human-readable description |
| `source_stage` | string | Which stage discovered it (request, identify, unpack, etc.) |
| `created_at` | ISO8601 | When artifact was discovered |

## Artifact Types

### file

- **Example**: PE executable, DLL, Python bytecode, .NET assembly
- **Fields**: path, sha256, size_bytes
- **Used For**: Binary analysis, unpacking, extraction

### directory

- **Example**: Extracted archive contents
- **Fields**: path, description
- **Used For**: Organizing extracted artifacts

### memory

- **Example**: Process memory dump
- **Fields**: path, sha256, size_bytes, process_name, address_range
- **Used For**: Behavioral analysis, secret detection

### network

- **Example**: Captured network traffic
- **Fields**: path, size_bytes, description ("TCP traffic to 192.168.1.1:8080")
- **Used For**: IOC extraction, C&C detection

### behavioral

- **Example**: Recorded behaviors (process creation, registry write)
- **Fields**: description ("Process CreateRemoteThread into svchost.exe")
- **Used For**: Capability mapping, verdict assignment

## Artifact Lineage

Artifacts form a directed acyclic graph (DAG) where edges represent derivation:

```
art_0000 (primary sample)
├── art_0001 (unpacked DLL via UPX)
│   ├── art_0002 (memory dump of DLL process)
│   └── art_0003 (injected code from memory)
├── art_0004 (extracted config strings)
└── art_0005 (network capture during execution)
```

Parent/child relationships enable:
- **Traceability**: Follow artifact origin
- **Scope Limitation**: Findings for art_0003 are scoped to injected code, not primary sample
- **Consistency**: Remove parent → cascade cleanup of children

## ArtifactRegistry

The registry is a multi-indexed store for artifact lookups:

```python
class ArtifactRegistry:
    def __init__(self):
        self.by_id = {}           # artifact_id → ArtifactNode
        self.by_path = {}         # path → artifact_id
        self.by_hash = {}         # sha256 → artifact_id
        self.by_parent = {}       # parent_artifact_id → [child_ids]
    
    def register(self, artifact: ArtifactNode):
        """Add artifact to registry."""
        self.by_id[artifact.artifact_id] = artifact
        self.by_path[artifact.path] = artifact.artifact_id
        if artifact.sha256:
            self.by_hash[artifact.sha256] = artifact.artifact_id
        if artifact.parent_artifact_id:
            if artifact.parent_artifact_id not in self.by_parent:
                self.by_parent[artifact.parent_artifact_id] = []
            self.by_parent[artifact.parent_artifact_id].append(artifact.artifact_id)
    
    def get_children(self, parent_id: str) -> List[ArtifactNode]:
        """Get all direct children of an artifact."""
        child_ids = self.by_parent.get(parent_id, [])
        return [self.by_id[cid] for cid in child_ids]
    
    def get_descendants(self, parent_id: str) -> List[ArtifactNode]:
        """Get all descendants (recursive) of an artifact."""
        descendants = []
        for child_id in self.by_parent.get(parent_id, []):
            child = self.by_id[child_id]
            descendants.append(child)
            descendants.extend(self.get_descendants(child_id))
        return descendants
```

## Artifact Lifecycle

### 1. Creation (request stage)

```python
primary_artifact = ArtifactNode(
    artifact_id="art_0000",
    path="/tmp/sample.exe",
    type="file",
    sha256=sha256_of("/tmp/sample.exe"),
    parent_artifact_id=None,
    description="Primary sample submitted by user",
    source_stage="request"
)
registry.register(primary_artifact)
```

### 2. Discovery (identify stage)

DIE identifies the sample type and may discover embedded artifacts.

### 3. Extraction (unpack stage)

Unpacking yields new artifacts (unpacked DLLs, extracted configs):

```python
unpacked_artifact = ArtifactNode(
    artifact_id="art_0001",
    path="/analysis/extracted/payload.dll",
    type="file",
    sha256=sha256_of("/analysis/extracted/payload.dll"),
    parent_artifact_id="art_0000",  # Linked to primary
    description="Unpacked DLL via UPX extraction",
    source_stage="unpack"
)
registry.register(unpacked_artifact)
```

### 4. Finding Association (all analysis stages)

Findings reference artifacts:

```python
finding = Finding(
    finding_id="find_001",
    artifact_id="art_0001",  # Applies to unpacked artifact
    category="behavior",
    severity="high",
    title="Process Injection Detected",
    description="Unpacked DLL injects code into svchost.exe"
)
```

### 5. Report Synthesis (report stage)

Report groups findings by artifact and lineage:

```markdown
# Artifacts

## art_0000: Primary Sample
- Type: file (PE64 executable)
- Hash: abcd1234...
- Size: 524 KB

### Findings
- Finding 1: Suspicious imports (kernel32, ntdll)
- Finding 2: Anti-analysis code detected

## art_0001: Unpacked Payload (from art_0000)
- Type: file (PE64 DLL)
- Hash: efgh5678...
- Extraction: UPX
- Parent: art_0000

### Findings
- Finding 3: Process injection attempt
- Finding 4: Network communication to C&C
```

## Artifact Deduplication

Identical files (same SHA256) are deduplicated:

```python
def register_with_dedup(self, artifact: ArtifactNode):
    """Register artifact, deduplicating by hash if present."""
    if artifact.sha256 and artifact.sha256 in self.by_hash:
        # Artifact already exists
        existing_id = self.by_hash[artifact.sha256]
        existing = self.by_id[existing_id]
        
        # Don't create duplicate; note the new path
        existing.alternate_paths.append(artifact.path)
        
        # Still record parent relationship if this is a new linkage
        if artifact.parent_artifact_id and existing.artifact_id not in self.by_parent.get(artifact.parent_artifact_id, []):
            self.register_lineage(artifact.parent_artifact_id, existing.artifact_id)
        
        return existing.artifact_id
    else:
        # New artifact
        self.register(artifact)
        return artifact.artifact_id
```

## Artifact Validation

Artifacts must satisfy:

1. **ID Uniqueness**: No duplicate artifact_id in registry
2. **Path Validity**: Path exists and is readable (for file/directory types)
3. **Hash Validity**: SHA256 is 64 hex characters (if present)
4. **Parent Validity**: parent_artifact_id points to existing artifact
5. **Lineage Acyclicity**: No circular parent-child relationships

```python
def validate_artifact(self, artifact: ArtifactNode) -> bool:
    """Validate artifact structure and references."""
    
    # 1. ID uniqueness
    if artifact.artifact_id in self.by_id:
        raise ValueError(f"Duplicate artifact_id: {artifact.artifact_id}")
    
    # 2. Path validity
    if artifact.type in ["file", "directory"]:
        if not os.path.exists(artifact.path):
            raise ValueError(f"Path does not exist: {artifact.path}")
    
    # 3. Hash validity
    if artifact.sha256:
        if not re.match(r'^[a-f0-9]{64}$', artifact.sha256):
            raise ValueError(f"Invalid SHA256: {artifact.sha256}")
    
    # 4. Parent validity
    if artifact.parent_artifact_id:
        if artifact.parent_artifact_id not in self.by_id:
            raise ValueError(f"Parent artifact not found: {artifact.parent_artifact_id}")
    
    # 5. Lineage acyclicity
    if self._has_cycle(artifact.artifact_id):
        raise ValueError(f"Circular lineage detected for: {artifact.artifact_id}")
    
    return True
```

## Artifact Graph Traversal

### Get lineage path (root to artifact)

```python
def get_lineage_path(self, artifact_id: str) -> List[str]:
    """Get path from root artifact to specified artifact."""
    path = []
    current_id = artifact_id
    while current_id:
        path.insert(0, current_id)
        current = self.by_id.get(current_id)
        current_id = current.parent_artifact_id if current else None
    return path
```

### Get impact scope (all descendants affected by finding on root)

```python
def get_impact_scope(self, artifact_id: str) -> List[str]:
    """Get all descendants affected by finding on artifact."""
    return [artifact_id] + [d.artifact_id for d in self.get_descendants(artifact_id)]
```

## Integration with Findings

Findings always reference an artifact:

```python
finding = Finding(
    finding_id="find_001",
    artifact_id="art_0001",    # REQUIRED: Which artifact does this apply to?
    category="behavior",
    severity="high",
    title="Process Injection",
    description="...",
    evidence=[...]
)
```

During report generation, findings are grouped by artifact and presented in lineage context.

## Related Documentation

- [Findings](./findings.md) — Finding model and linking to artifacts
- [Response Contract](./response-contract.md) — Public artifact envelope
- [Data Models](../architecture/data-models.md) — Complete model reference
- [Stage Dependencies](../architecture/stage-dependencies.md) — Lineage across stages

