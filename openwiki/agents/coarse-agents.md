---
type: reference
title: Coarse Agents - File Type Analysis
description: NativeAgent, ScriptAgent, and DotNetAgent implementations for binary routing and initial analysis.
tags: [agents, coarse, routing]
---

# Coarse Agents

Coarse agents perform file type detection and initial analysis routing. They are located in `/.claude/worktrees/agent-*/agents/` and are used during the static-pass1 stage (02).

## Agent Taxonomy

| Agent | File Types | Purpose | Location |
|-------|-----------|---------|----------|
| **NativeAgent** | PE, PE+, PE64 (x86/x64) | Disassembly, API call extraction, static behavior analysis | native_agent.py |
| **ScriptAgent** | Python bytecode, PyInstaller, shell scripts | Bytecode decompilation, script execution simulation | script_agent.py |
| **DotNetAgent** | .NET PE, CLR assemblies, .NET executables | IL decompilation, metadata extraction, resource analysis | dotnet_agent.py |

## NativeAgent

### Purpose

Analyzes native binaries using:
- IDA Pro for disassembly (via ida-pro-mcp)
- Signature-based API call extraction
- Behavioral indicator detection

### Key Functions

```python
class NativeAgent:
    def __init__(self, config_path: str = "config.yaml"):
        """Initialize with configuration."""
        self.config = self._load_config(config_path)
        self.ida_mcp_cmd = "uv run idalib-mcp"
    
    async def analyze(self, file_path: str) -> dict:
        """Analyze native binary."""
        # 1. Extract file hash
        file_hash = self._get_file_hash(file_path)
        
        # 2. Start IDA Pro MCP server
        await self._start_ida_mcp_server()
        
        # 3. Invoke IDA disassembly
        disassembly = await self._disassemble_via_ida(file_path)
        
        # 4. Extract APIs and indicators
        apis = self._extract_api_calls(disassembly)
        indicators = self._detect_behavioral_indicators(disassembly)
        
        # 5. Invoke Claude for reasoning
        analysis = await run_claude_code(
            f"""
            Analyze the following x86/x64 disassembly and extracted API calls.
            Identify:
            - Malware families and signatures
            - Behavioral indicators
            - Packing/obfuscation techniques
            - Notable characteristics
            
            Disassembly:
            {disassembly[:10000]}  # First 10K chars
            
            API Calls:
            {json.dumps(apis, indent=2)}
            
            Behavioral Indicators:
            {json.dumps(indicators, indent=2)}
            """
        )
        
        return {
            "success": True,
            "agent_type": "native",
            "file_hash": file_hash,
            "apis": apis,
            "indicators": indicators,
            "claude_analysis": analysis
        }
    
    async def _start_ida_mcp_server(self):
        """Start IDA Pro MCP server via ida-pro-mcp."""
        # Uses ida-pro-mcp to establish IDA Pro connection
        pass
    
    async def _disassemble_via_ida(self, file_path: str) -> str:
        """Get disassembly from IDA Pro."""
        # Uses ida-pro-mcp to retrieve disassembly
        pass
    
    def _extract_api_calls(self, disassembly: str) -> dict:
        """Extract API calls from disassembly."""
        # Signature-based extraction of kernel32, ntdll, etc. calls
        pass
    
    def _detect_behavioral_indicators(self, disassembly: str) -> dict:
        """Detect behavioral indicators in disassembly."""
        # Process creation, file operations, network, etc.
        pass
```

### Integration with Static Pass 1

During 02-static-pass1, the NativeAgent is invoked after file type detection:

```python
# In hyperagent-static SKILL.md
if analysis_type == AnalysisType.NATIVE:
    agent = NativeAgent(config_path)
    analysis_data = await agent.analyze(file_path)
    
    # Project into stage output
    findings = [
        Finding(
            finding_id=f"find_{i:03d}",
            artifact_id="art_0000",
            category="behavior",
            severity=determine_severity(indicator),
            title=indicator,
            description=...,
            evidence=[...]
        )
        for i, indicator in enumerate(analysis_data["indicators"])
    ]
```

## ScriptAgent

### Purpose

Analyzes Python scripts and bytecode using:
- Bytecode decompilation (uncompyle6, decompyle3)
- PyInstaller extraction and analysis
- Shell script parsing

### Key Functions

```python
class ScriptAgent:
    async def analyze(self, file_path: str) -> dict:
        """Analyze Python/shell script."""
        # 1. Detect script type
        script_type = self._detect_script_type(file_path)  # python, shell, pyinstaller
        
        # 2. Extract source if compiled
        if script_type == "pyinstaller":
            source_code = await self._extract_pyinstaller(file_path)
        elif script_type == "python":
            with open(file_path, 'r') as f:
                source_code = f.read()
        else:
            source_code = ...
        
        # 3. Invoke Claude for analysis
        analysis = await run_claude_code(
            f"""
            Analyze the following Python/shell script.
            Identify:
            - Suspicious imports and capabilities
            - Network/file operations
            - Obfuscation or anti-analysis code
            - Malware signatures
            
            Source Code:
            {source_code}
            """
        )
        
        return {
            "success": True,
            "agent_type": "script",
            "script_type": script_type,
            "source_code": source_code[:50000],  # Truncated for output
            "claude_analysis": analysis
        }
    
    def _detect_script_type(self, file_path: str) -> str:
        """Detect if script is PyInstaller, Python bytecode, or shell."""
        pass
    
    async def _extract_pyinstaller(self, file_path: str) -> str:
        """Extract source from PyInstaller executable."""
        pass
```

## DotNetAgent

### Purpose

Analyzes .NET assemblies using:
- IL decompilation (dnSpy, ILSpy)
- Metadata extraction
- Resource unpacking

### Key Functions

```python
class DotNetAgent:
    async def analyze(self, file_path: str) -> dict:
        """Analyze .NET assembly."""
        # 1. Validate .NET PE
        if not self._is_valid_dotnet_pe(file_path):
            return {"success": False, "error": "Not a valid .NET PE"}
        
        # 2. Extract metadata
        metadata = self._extract_metadata(file_path)
        
        # 3. Decompile IL
        il_source = self._decompile_il(file_path)
        
        # 4. Invoke Claude for analysis
        analysis = await run_claude_code(
            f"""
            Analyze the following .NET assembly IL code.
            Identify:
            - Suspicious namespaces and classes
            - P/Invoke calls to native code
            - String obfuscation techniques
            - Embedded resources
            
            Metadata:
            {json.dumps(metadata, indent=2)}
            
            IL Source (first 20KB):
            {il_source[:20000]}
            """
        )
        
        return {
            "success": True,
            "agent_type": "dotnet",
            "metadata": metadata,
            "il_source": il_source[:50000],
            "claude_analysis": analysis
        }
    
    def _is_valid_dotnet_pe(self, file_path: str) -> bool:
        """Check if PE contains .NET CLR header."""
        pass
    
    def _extract_metadata(self, file_path: str) -> dict:
        """Extract .NET metadata (version, assemblyname, etc.)."""
        pass
    
    def _decompile_il(self, file_path: str) -> str:
        """Decompile IL to C#-like source."""
        pass
```

## Agent Result Format

All agents return results in standard format:

```json
{
  "success": true,
  "agent_type": "native|script|dotnet",
  "file_hash": "abc123...",
  "findings": [
    {
      "finding_id": "find_001",
      "category": "behavior",
      "severity": "high",
      "title": "Process Injection API",
      "description": "Calls CreateRemoteThread"
    }
  ],
  "indicators": [],
  "apis": [],
  "claude_analysis": "Raw Claude reasoning output"
}
```

## Configuration

Agents are configured via `config.yaml`:

```yaml
agents:
  native:
    ida_startup_timeout_s: 180
    ida_probe_interval_s: 0.5
  
  script:
    pyinstaller_extractor: "/path/to/PyInstaller_Extractor.py"
  
  dotnet:
    decompiler: "dnspy"  # or ilspy
```

## Relationship to Pipeline

While coarse agents exist in `/.claude/worktrees/`, they are invoked during **Stage 02 (static-pass1)** as part of the routing and analysis process:

```
Stage 02 (hyperagent-static)
├─ Identify: Run DIE → determine file type
├─ Route: Select coarse agent (native/script/dotnet)
├─ Agent: Invoke selected agent
│   └─ NativeAgent/ScriptAgent/DotNetAgent
│       └─ Invoke Claude for reasoning
└─ Next-stage hunting: Emit findings
```

## Related Documentation

- [Routing & Dispatch](./routing-and-dispatch.md) — File type detection and agent selection
- [Stage 02: Static Pass 1](../skills/stages/02-04-static-analysis.md) — Where agents are invoked
- [Overview](./overview.md) — Agent taxonomy

