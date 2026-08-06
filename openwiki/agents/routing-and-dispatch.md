---
type: reference
title: File Type Detection and Agent Routing
description: DIE integration, file type classification, and dispatch to coarse agents (native/script/.net).
tags: [agents, routing, detection]
---

# File Type Detection and Agent Routing

## Overview

The routing system identifies file types and dispatches to the appropriate coarse agent:

```
Input File
    ↓
[Run DIE (Detect It Easy)]
    ↓
[Parse DIE output: file_class, compiler, language, packer, tool]
    ↓
[Classify to AnalysisType: NATIVE | DOTNET | PYTHON_SCRIPT | UNKNOWN]
    ↓
[Select Agent: NativeAgent | DotNetAgent | ScriptAgent]
    ↓
[Execute Agent Analysis]
```

## DIE Handler

The `DIEHandler` class in `core/die_handler.py` manages file type detection:

```python
class DIEHandler:
    def __init__(self, config_path: str = "config.yaml"):
        self.config = self._load_config(config_path)
        self.die_path = self.config.get("tools", {}).get("diec", "diec.exe")
    
    def identify(self, file_path: str) -> tuple[dict, AnalysisType]:
        """
        Run DIE on file and return parsed output + analysis type.
        
        Returns:
        - die_data: Parsed DIE output (file_class, compiler, language, packer, etc.)
        - analysis_type: Classified type (NATIVE, DOTNET, PYTHON_SCRIPT, UNKNOWN)
        """
        die_output = self.run_die(file_path)  # Run diec.exe -b -p -u
        die_data = self.parse_die_text_output(die_output)
        
        # Classify based on parsed DIE output
        analysis_type = self._classify_from_die_data(die_data)
        
        return die_data, analysis_type
    
    def run_die(self, file_path: str) -> str:
        """Execute diec.exe and return text output."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        # Command: diec.exe -b -p -u "path/to/file"
        # -b: Basic info
        # -p: Packer detection
        # -u: Unknown signatures
        cmd = [self.die_path, "-b", "-p", "-u", file_path]
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        
        if result.returncode != 0:
            print(f"DIE Warning: {result.stderr}")
        
        return result.stdout
    
    def parse_die_text_output(self, text: str) -> dict:
        """
        Parse DIE text output to extract structured fields.
        
        Example DIE output:
        ```
        PE64
        Microsoft Visual C++ 6.0
        Compiler: MSVC
        Language: C++
        Packer: UPX
        ```
        """
        result = {
            "file_class": None,
            "packer": None,
            "compiler": None,
            "language": None,
            "library": None,
            "tool": None,
            "malware": None
        }
        
        lines = text.splitlines()
        for line in lines:
            if not line.strip():
                continue
            
            # Skip log lines (start with [)
            if line.strip().startswith("["):
                continue
            
            # File class (no indentation, no colon)
            if not line.startswith(" ") and ":" not in line:
                result["file_class"] = line.strip()
                continue
            
            # Key-value pairs
            if ":" in line:
                key, value = line.split(":", 1)
                key = key.strip().lower()
                value = value.strip()
                
                if "compiler" in key:
                    result["compiler"] = value
                elif "language" in key:
                    result["language"] = value
                elif "packer" in key:
                    result["packer"] = value
                elif "linker" in key and not result["packer"]:
                    result["packer"] = value
                elif "library" in key:
                    result["library"] = value
                elif "tool" in key:
                    result["tool"] = value
                elif "malware" in key:
                    result["malware"] = value
        
        return result
    
    def _classify_from_die_data(self, die_data: dict) -> AnalysisType:
        """
        Classify file type based on parsed DIE output.
        """
        file_class = die_data.get("file_class", "").upper()
        compiler = die_data.get("compiler", "").upper()
        language = die_data.get("language", "").upper()
        tool = die_data.get("tool", "").upper()
        
        # Native binary detection
        if file_class and file_class.startswith("PE"):
            # Check if it's .NET
            if "CLR" in compiler or ".NET" in compiler or ".NET" in tool:
                return AnalysisType.DOTNET
            # Otherwise native
            return AnalysisType.NATIVE
        
        # Python/script detection
        if "PYTHON" in language or "PYTHON" in tool:
            return AnalysisType.PYTHON_SCRIPT
        
        if "PYINSTALLER" in tool:
            return AnalysisType.PYTHON_SCRIPT
        
        if "SHELL" in tool or "BASH" in tool:
            return AnalysisType.PYTHON_SCRIPT
        
        # Default
        return AnalysisType.UNKNOWN
```

## Classification Logic

### Native (x86/x64 PE)

**Triggers**:
- DIE `file_class`: PE, PE32, PE64, PE+
- `compiler`: Microsoft Visual C++, GCC, Clang
- No CLR indication

**Agent**: `NativeAgent`

**Example DIE Output**:
```
PE64
Microsoft Visual C++ 14.0
Compiler: MSVC v14
Language: C++
```

### .NET (CLR)

**Triggers**:
- DIE `file_class`: PE or PE64
- `compiler`: Contains "CLR", ".NET", or "Visual C#"
- `tool`: Contains ".NET"

**Agent**: `DotNetAgent`

**Example DIE Output**:
```
PE32
.NET Framework 4.0
Compiler: Roslyn
Language: C#
```

### Python/Script

**Triggers**:
- DIE `language`: Python
- `tool`: PyInstaller, Cython, CPython
- Or file extension: .py, .pyc, .pyo
- Or detected shell script magic: #!/bin/bash

**Agent**: `ScriptAgent`

**Example DIE Output**:
```
Python Script
Tool: PyInstaller 5.1
Language: Python 3.9
```

### Unknown

**Triggers**:
- DIE cannot classify
- File extension is not recognized
- Magic bytes don't match known types

**Agent**: `ScriptAgent` (fallback)

## Routing in Static Pass 1

The routing decision is made during **Stage 02 (static-pass1)**:

```python
# In hyperagent-static SKILL.md

class StaticPass1Orchestrator:
    async def execute(self, file_path: str):
        """
        Execute static pass 1 with routing.
        """
        
        # 1. Identify stage: Run DIE
        print("[*] Stage: Identify")
        die_handler = DIEHandler(config_path="config.yaml")
        die_data, analysis_type = die_handler.identify(file_path)
        
        # Log identification
        self.log(f"Identified file type: {analysis_type.name}")
        self.log(f"DIE output: {json.dumps(die_data, indent=2)}")
        
        # 2. Route stage: Select agent
        print("[*] Stage: Route")
        if analysis_type == AnalysisType.NATIVE:
            agent = NativeAgent(config_path="config.yaml")
            print(f"[+] Routing to: NativeAgent (x86/x64 PE analysis)")
        elif analysis_type == AnalysisType.DOTNET:
            agent = DotNetAgent()
            print(f"[+] Routing to: DotNetAgent (.NET CLR analysis)")
        elif analysis_type == AnalysisType.PYTHON_SCRIPT:
            agent = ScriptAgent()
            print(f"[+] Routing to: ScriptAgent (Python/shell script analysis)")
        else:
            agent = ScriptAgent()  # Fallback
            print(f"[+] Routing to: ScriptAgent (fallback for unknown type)")
        
        # 3. Agent stage: Execute selected agent
        print(f"[*] Stage: Agent ({agent.__class__.__name__})")
        analysis_result = await agent.analyze(file_path)
        
        # 4. Next-stage hunting
        print("[*] Stage: Next-stage hunting")
        recommendations = self.hunt_next_stages(analysis_result)
        
        # Return findings
        return {
            "identified_type": analysis_type.name,
            "die": die_data,
            "agent": agent.__class__.__name__,
            "findings": analysis_result.get("findings", []),
            "recommendations": recommendations
        }
    
    def hunt_next_stages(self, analysis_result: dict) -> list[str]:
        """
        Recommend next stages based on findings.
        """
        recommendations = []
        
        # Always unpack if packing detected
        if any(f.get("category") == "obfuscation" for f in analysis_result.get("findings", [])):
            recommendations.append("03-unpack")
        
        # Always run dynamic if behavior indicators found
        if any(f.get("category") == "behavior" for f in analysis_result.get("findings", [])):
            recommendations.append("05-dynamic")
        
        # Always run intel enrichment
        recommendations.append("06-intel")
        
        return recommendations
```

## Configuration

Routing behavior is configured in `config.yaml`:

```yaml
tools:
  diec: "diec.exe"  # Path to DIE executable
  
agents:
  native:
    ida_startup_timeout_s: 180
  script:
    pyinstaller_extractor: "./resource/pyinstxtractor/pyinstxtractor.py"
  dotnet:
    decompiler: "dnspy"
```

## File Type Examples

| File | DIE Output | Classification | Agent |
|------|-----------|-----------------|-------|
| malware.exe | PE64, MSVC | NATIVE | NativeAgent |
| payload.dll | PE64, MSVC | NATIVE | NativeAgent |
| app.exe | PE32, Roslyn, .NET | DOTNET | DotNetAgent |
| script.py | Python 3.9 | PYTHON_SCRIPT | ScriptAgent |
| packed.exe | PE64, UPX | NATIVE | NativeAgent |
| dropper | PyInstaller | PYTHON_SCRIPT | ScriptAgent |

## Related Documentation

- [Coarse Agents](./coarse-agents.md) — NativeAgent, ScriptAgent, DotNetAgent implementations
- [Stage 02: Static Pass 1](../skills/stages/02-04-static-analysis.md) — Where routing occurs
- [Overview](./overview.md) — Agent taxonomy and execution model

