---
type: reference
title: REST API Endpoints
description: HTTP API for file analysis via POST /analyze/path and POST /analyze/upload.
tags: [api, rest, integration]
---

# REST API Endpoints

## Overview

HyperAgent exposes a FastAPI application (`api.py`) that provides two primary endpoints for initiating analysis via HTTP.

## Endpoints

### POST /analyze/path

Analyze a file from a filesystem path.

**Request**:
```http
POST /analyze/path HTTP/1.1
Content-Type: application/json

{
  "file_path": "/absolute/path/to/sample.exe"
}
```

**Parameters**:
- `file_path` (string, required): Absolute path to file to analyze. File must be accessible to the API process.

**Response** (200 OK):
```json
{
  "file_path": "/absolute/path/to/sample.exe",
  "detected_type": "NATIVE",
  "die": {
    "file_class": "PE64",
    "packer": "UPX",
    "compiler": "Microsoft Visual C++",
    "language": "C++",
    "malware": null
  },
  "result": {
    "success": true,
    "payload": "..."
  }
}
```

**Errors**:
- 404: File not found at specified path
- 500: Analysis error (see detail message for cause)

**Flow**:
1. Validate file exists and is readable
2. Invoke HyperAgentOrchestrator.analyze(file_path)
3. Return orchestrator result

### POST /analyze/upload

Upload and analyze a file.

**Request**:
```http
POST /analyze/upload HTTP/1.1
Content-Type: multipart/form-data

file: <binary file content>
keep_file: false
```

**Parameters**:
- `file` (binary, required): Uploaded file content
- `keep_file` (boolean, optional, default=false): If true, persist uploaded file to HYPERAGENT_UPLOAD_DIR; if false, use temporary file

**Response** (200 OK):
```json
{
  "file_path": "/tmp/xyz123.exe",
  "detected_type": "NATIVE",
  "die": { ... },
  "result": { ... },
  "upload_id": "a0b1c2d3e4f5...",
  "saved_path": null  // null if keep_file=false; absolute path if keep_file=true
}
```

**Errors**:
- 400: No file uploaded
- 404: File error during analysis
- 500: Analysis error

**Flow**:
1. Validate file was uploaded
2. If `keep_file=true`:
   - Create HYPERAGENT_UPLOAD_DIR if missing
   - Persist to `{HYPERAGENT_UPLOAD_DIR}/{upload_id}_{original_name}`
   - Use persisted path for analysis
3. If `keep_file=false`:
   - Create temporary file with original extension
   - Use temp path for analysis
   - Delete temp file after analysis completes
4. Invoke HyperAgentOrchestrator.analyze(analysis_target)
5. Return result with upload_id and saved_path

## Configuration

### Upload Directory

**Env Var**: `HYPERAGENT_UPLOAD_DIR`  
**Default**: `./uploads`  
**Usage**: Directory where uploaded files are persisted (when `keep_file=true`)

### Orchestrator Integration

The API delegates all analysis to `HyperAgentOrchestrator` (from `main.py`):

```python
from main import HyperAgentOrchestrator

app = FastAPI(title="HyperAgent API", version="0.1.0")
orchestrator = HyperAgentOrchestrator()

@app.post("/analyze/path")
async def analyze_path(body: AnalyzePathRequest):
    return await orchestrator.analyze(body.file_path)

@app.post("/analyze/upload")
async def analyze_upload(file: UploadFile = File(...), keep_file: bool = False):
    # ... file handling ...
    return await orchestrator.analyze(analysis_target)
```

The orchestrator invokes the full 9-stage pipeline via claude_spawn.py.

## Response Schema

Both endpoints return the same response structure:

```json
{
  "file_path": "string",
  "detected_type": "NATIVE | DOTNET | PYTHON_SCRIPT | UNKNOWN",
  "die": {
    "file_class": "string | null",
    "packer": "string | null",
    "compiler": "string | null",
    "language": "string | null",
    "library": "string | null",
    "tool": "string | null",
    "malware": "string | null"
  },
  "result": {
    "success": boolean,
    "payload": "any",
    "findings": [Finding],
    "artifacts": [ArtifactNode],
    "iocs": [IOC],
    "next_stage_recommendations": [string]
  }
}
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `file_path` | string | Path to analyzed file |
| `detected_type` | string | File type detected by orchestrator (NATIVE, DOTNET, PYTHON_SCRIPT, or UNKNOWN) |
| `die` | object | DIE (Detect It Easy) output; includes file class, packer, compiler, language, malware signature |
| `result` | object | Orchestrator result; structure varies by analysis type |
| `result.success` | boolean | Whether analysis completed successfully |
| `result.payload` | any | Coarse agent payload (internal format varies) |
| `result.findings` | array | Normalized findings (behavior, config, IOC, capability, etc.) |
| `result.artifacts` | array | Discovered artifacts with lineage |
| `result.iocs` | array | Indicators of compromise extracted |
| `result.next_stage_recommendations` | array | Recommended next analysis stages |

## Planned Future Endpoints

The following endpoints are documented in architecture notes but not yet implemented:

- **GET /runs/{run_id}**: Retrieve run snapshot (legacy compatibility)
- **GET /runs/{run_id}/tasks**: Retrieve task snapshot (live observability)
- **GET /runs**: List all runs with status

These endpoints will provide:
- Run state queries and filtering
- Task-level observability for dashboards
- Ability to query ongoing or completed analyses

## Running the API Server

```bash
# Development
uvicorn api:app --reload --host 0.0.0.0 --port 8000

# Production
gunicorn -w 4 -k uvicorn.workers.UvicornWorker api:app --bind 0.0.0.0:8000
```

## Example Usage

### Analyze Local File

```bash
curl -X POST http://localhost:8000/analyze/path \
  -H "Content-Type: application/json" \
  -d '{"file_path": "/tmp/sample.exe"}'
```

### Upload and Analyze

```bash
curl -X POST http://localhost:8000/analyze/upload \
  -F "file=@/path/to/sample.exe" \
  -F "keep_file=true"
```

### Python Client

```python
import requests

# Analyze from path
response = requests.post(
    "http://localhost:8000/analyze/path",
    json={"file_path": "/tmp/sample.exe"}
)
result = response.json()
print(f"Verdict: {result.get('result', {}).get('verdict')}")

# Analyze via upload
with open("/path/to/sample.exe", "rb") as f:
    response = requests.post(
        "http://localhost:8000/analyze/upload",
        files={"file": f},
        data={"keep_file": True}
    )
result = response.json()
print(f"Saved to: {result.get('saved_path')}")
```

## Error Handling

All endpoints return errors in this format:

```json
{
  "detail": "Human-readable error message"
}
```

Common status codes:
- **200**: Success
- **400**: Bad request (malformed JSON, missing required fields)
- **404**: File not found
- **500**: Server error during analysis

## Concurrency and State

- API processes requests sequentially (one at a time)
- Each request spawns a full 9-stage pipeline
- Stage state is persisted to STATE.json under HYPERAGENT_ANALYSIS_DIR
- Multiple API instances would require shared STATE storage (not currently implemented)

## Related Documentation

- [Orchestrator](../orchestration/launcher.md) — How analysis pipeline works
- [Architecture Overview](../architecture/overview.md) — System design
- [Response Contract](../data/response-contract.md) — Full response envelope schema

