---
type: guide
title: Environment Setup and Bootstrap
description: Complete workflow for bootstrapping HyperAgent development environment, installing prerequisites, configuring tools, and validating readiness.
tags: [setup, bootstrap, environment]
---

# Environment Setup and Bootstrap

## Overview

This guide covers the complete setup workflow for HyperAgent development and deployment environments.

## Prerequisites

### System Requirements

- **OS**: Windows 10+ (primary), Linux/macOS supported
- **Python**: 3.9+
- **Node.js**: 14+ (for Claude Code CLI)
- **Tools**: diec (DIE), IDA Pro (optional, for native analysis), x64dbg (optional, for dynamic analysis), VMware (optional, for guest execution)

### Required Software

| Tool | Purpose | Recommended Version | Optional? |
|------|---------|-------------------|-----------|
| Python | Runtime | 3.11+ | No |
| pip/uv | Package manager | Latest | No |
| Claude Code CLI | Skill invocation | Latest | No |
| DIE (diec.exe) | File type detection | Latest | No |
| IDA Pro | Binary disassembly (native analysis) | 8.0+ | Yes (required for native agent) |
| x64dbg | Debugger (dynamic analysis) | Latest | Yes (required for dynamic) |
| VMware | Guest execution | Player/Fusion | Yes (required for dynamic) |
| Git | Version control | Latest | No |

## Bootstrap Workflow (Windows)

### 1. Run bootstrap.ps1

```powershell
cd C:\path\to\HyperAgent
powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1
```

**What it does**:
- Creates Python virtual environment (.venv)
- Installs Claude Code CLI via npm
- Creates skills directory structure
- Sets up environment variables
- Searches for IDA Pro installation
- Validates tool availability

### 2. Activate Virtual Environment

```powershell
.\.venv\Scripts\Activate.ps1
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

Dependencies typically include:
- fastapi (REST API)
- pydantic (data validation)
- pyyaml (config files)
- subprocess/asyncio (orchestration)

### 4. Configure Environment Variables

Edit `.env` file (or set in system):

```bash
# Required
HYPERAGENT_SKILLS_ROOT=~/.claude/skills
HYPERAGENT_ANALYSIS_DIR=./reports

# Optional
HYPERAGENT_UPLOAD_DIR=./uploads
HYPERAGENT_IDA_ROOT=C:/Program Files/IDA Pro 8.0
HYPERAGENT_IDALIB_ACTIVATE=C:/Program Files/IDA Pro 8.0/idalib/python/py-activate-idalib.py
VIRUSTOTAL_API_KEY=<your-vt-api-key>
```

### 5. Install Claude Code CLI

If bootstrap.ps1 did not automatically install:

```powershell
npm install -g @anthropic-ai/claude-code
```

Verify installation:

```bash
claude --version
```

### 6. Install Skills

Skills must be installed in the Claude skills directory:

```bash
# Copy skills from /skill/backup/hyperagent-malware-analyze/v3/* to ~/.claude/skills/
# Or use bootstrap.ps1 to do this automatically
```

Expected structure:
```
~/.claude/skills/
├── hyperagent-prepare-env/
│   ├── SKILL.md
│   ├── schema.json
│   └── ENVIRONMENT.md
├── hyperagent-static/
├── hyperagent-unpack/
├── hyperagent-dynamic/
├── hyperagent-intel/
├── hyperagent-deepdive/
├── hyperagent-report/
├── hyperagent-summary/
└── hyperagent-progress/
```

## Tool Setup

### DIE (Detect It Easy)

DIE is required for file type detection.

**Windows**:
1. Download diec from https://github.com/horsicq/Detect-It-Easy
2. Extract to `C:\tools\DIE\` or similar
3. Configure path in config.yaml:

```yaml
tools:
  diec: C:\tools\DIE\diec.exe
```

**Verification**:
```bash
diec.exe --version
diec.exe -b -p -u C:\path\to\sample.exe  # Test run
```

### IDA Pro Integration

IDA Pro is optional but required for native binary analysis (NativeAgent).

**Setup**:
1. Install IDA Pro (8.0+) to default location (Program Files)
2. Install IDA Python plugin (idalib)
3. bootstrap.ps1 will auto-detect installation
4. Configure env vars:

```bash
HYPERAGENT_IDA_ROOT=C:/Program Files/IDA Pro 8.0
HYPERAGENT_IDALIB_ACTIVATE=C:/Program Files/IDA Pro 8.0/idalib/python/py-activate-idalib.py
```

**MCP Server**:
IDA integration uses MCP (Model Context Protocol). The Claude Code skill invokes:
```bash
claude -p '/{skill_name} @{sample_path}' --mcp-server ida-pro-mcp
```

**Verification**:
```bash
python "C:/Program Files/IDA Pro 8.0/idalib/python/py-activate-idalib.py"
```

### x64dbg Integration (Dynamic Analysis)

x64dbg is optional but required for dynamic behavior analysis.

**Setup**:
1. Download x64dbg from https://x64dbg.com/
2. Extract to `C:\tools\x64dbg\` or similar
3. Configure env vars (or let bootstrap.ps1 auto-detect):

```bash
HYPERAGENT_X64DBG_ROOT=C:\tools\x64dbg
```

**MCP Server**:
x64dbg is accessed via x64dbg-mcp MCP server:
```bash
uv run x64dbg-mcp  # Starts MCP server
```

The dynamic analysis skill connects to this server on startup.

**Verification**:
```bash
C:\tools\x64dbg\x64dbg.exe  # Launches GUI (verify it works)
```

### VMware Integration (Dynamic Analysis)

VMware is optional but required for sandboxed dynamic analysis.

**Setup**:
1. Install VMware Player or Fusion
2. Create or import guest VM image with analysis tools
3. Configure vmrun path:

```bash
HYPERAGENT_VMWARE_VMRUN=C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe
```

**Guest VM Requirements**:
- Windows 10 or 11 with:
  - Process monitoring tools (sysmon, Procmon)
  - Network capture (Wireshark, tcpdump)
  - Sandbox isolation (no data exfiltration to host)
  - Clean snapshot for analysis reset

**Verification**:
```bash
vmrun list  # Lists available VMs
vmrun getVersion  # Prints vmrun version
```

### VirusTotal API (Optional)

VirusTotal API enables reputation queries and IOC enrichment (stage 06-intel).

**Setup**:
1. Sign up at https://www.virustotal.com/
2. Get API key from settings
3. Set environment variable:

```bash
VIRUSTOTAL_API_KEY=your-api-key-here
```

**Verification**:
```bash
curl https://www.virustotal.com/api/v3/files/{file_hash} \
  -H "x-apikey: $VIRUSTOTAL_API_KEY"
```

If VirusTotal API key is not configured, stage 06-intel is skipped gracefully.

## Configuration File

### config.yaml

Located in repository root. Template: config.yaml.template

```yaml
# Tool Paths
tools:
  diec: C:\tools\DIE\diec.exe
  ida_root: C:\Program Files\IDA Pro 8.0

# MCP Servers
mcp:
  ida_startup_timeout_s: 180
  ida_probe_interval_s: 0.5
  x64dbg_startup_timeout_s: 60
  vmware_vmrun_path: C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe

# Analysis
analysis:
  max_stage_attempts: 20
  context_checkpoint_threshold: 0.80  # 80% of context limit
  
# API
api:
  host: 0.0.0.0
  port: 8000
  upload_dir: ./uploads
```

### Environment Variables

Precedence (highest to lowest):
1. Command-line override
2. .env file
3. System environment variables
4. config.yaml defaults

**Key Variables**:

| Variable | Purpose | Default |
|----------|---------|---------|
| `HYPERAGENT_ANALYSIS_DIR` | Reports/artifacts output directory | `./reports` |
| `HYPERAGENT_SKILLS_ROOT` | Claude skills directory | `~/.claude/skills` |
| `HYPERAGENT_UPLOAD_DIR` | Uploaded file storage | `./uploads` |
| `HYPERAGENT_STATE_PATH` | Current STATE.json path | Auto-determined |
| `HYPERAGENT_STAGE_ID` | Current stage being executed | Auto-set by orchestrator |
| `HYPERAGENT_IDA_ROOT` | IDA Pro installation path | Auto-detected |
| `HYPERAGENT_IDALIB_ACTIVATE` | IDA Python activation script | Auto-detected |
| `VIRUSTOTAL_API_KEY` | VirusTotal API key | Optional |
| `HYPERAGENT_CLAUDE_HOME` | Claude Code home directory | `~/.claude` |

## Validation Checklist

Before running analyses, validate your setup:

```bash
# 1. Python environment
python --version  # Should be 3.9+
pip list | grep -i fastapi  # Should be installed

# 2. Claude Code CLI
claude --version  # Should print version

# 3. DIE
diec.exe --version  # Should print version

# 4. Skills installed
ls ~/.claude/skills/hyperagent-*  # Should list all skills

# 5. IDA Pro (if using native analysis)
python "$HYPERAGENT_IDALIB_ACTIVATE"  # Should activate without error

# 6. Environment variables
echo $HYPERAGENT_SKILLS_ROOT
echo $HYPERAGENT_ANALYSIS_DIR

# 7. File permissions
touch ./reports/test.txt && rm ./reports/test.txt  # Test write access
```

## Running the System

### Command-Line Analysis

```bash
# Single file
python claude_spawn.py /path/to/sample.exe

# Batch processing
python claude_spawn.py --batch /path/to/file_list.txt

# Resume interrupted analysis
python claude_spawn.py --resume /path/to/reports/sha256/STATE.json
```

### API Server

```bash
# Development
uvicorn api:app --reload --host 0.0.0.0 --port 8000

# Production
gunicorn -w 4 -k uvicorn.workers.UvicornWorker api:app
```

### Pipeline Controller

```bash
# Discover runs and auto-resume most-recent
claude -p '/hyperagent-progress'
```

## Troubleshooting

### Claude CLI not found

```bash
# Verify installation
which claude  # Linux/macOS
where claude  # Windows

# Reinstall if missing
npm install -g @anthropic-ai/claude-code
```

### DIE not found

```bash
# Configure path in config.yaml or environment
HYPERAGENT_DIE_PATH=/path/to/diec.exe

# Verify executable
diec --version
```

### Skills not found

```bash
# Check skills directory
ls ~/.claude/skills/

# Copy skills from repo if missing
cp -r skill/backup/hyperagent-malware-analyze/v3/* ~/.claude/skills/

# Set HYPERAGENT_SKILLS_ROOT if using custom location
export HYPERAGENT_SKILLS_ROOT=/custom/skills/path
```

### Permission errors

```bash
# Verify directory permissions
ls -la ./reports/
chmod 755 ./reports/

# Verify file access
touch ./reports/test.txt && rm ./reports/test.txt
```

### IDA Pro not starting

```bash
# Verify IDA installation
ls "C:\Program Files\IDA Pro 8.0\ida.exe"

# Activate idalib
python "C:/Program Files/IDA Pro 8.0/idalib/python/py-activate-idalib.py"

# Check IDA logs
type "C:\Program Files\IDA Pro 8.0\ida.log"
```

## Next Steps

After setup validation:

1. **Test with Sample**: Analyze a known-clean sample to verify pipeline
2. **Review Artifacts**: Inspect reports/{sha256}/ directory structure
3. **Check Findings**: Verify findings are extracted correctly
4. **Read Quickstart**: Review [Quickstart Guide](../quickstart.md) for usage patterns
5. **Explore API**: Test REST endpoints with curl or Postman

## Related Documentation

- [Quickstart](../quickstart.md) — Usage patterns and common tasks
<!-- openwiki: broken internal link [./configuration.md] file "./configuration.md" does not exist. Fix the href or restore the target, then delete this comment. -->
- [Configuration](./configuration.md) — Detailed config.yaml options
- [Launcher](../orchestration/launcher.md) — Pipeline orchestrator
- [Bootstrap Script](../../bootstrap.ps1) — Automated setup script

