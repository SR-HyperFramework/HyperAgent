import json
from typing import Dict, Any

class ContextLogger:
    def __init__(self):
        pass

    def format_context(self, analysis_data: Dict[str, Any]) -> str:
        """Formats the analysis dictionary into a markdown prompt."""
        
        # We want to present the data clearly to the LLM
        lines = []
        lines.append("# Malware Analysis Data")
        
        # DIE Data (inferred from routing but not passed explicitly? 
        # Actually analysis_data should ideally contain everything.)
        
        # File Info/Type
        lines.append(f"## Analysis Type: {analysis_data.get('type', 'UNKNOWN')}")
        
        # CAPA
        capa = analysis_data.get("capa", {})
        if capa:
            lines.append("## CAPA Capabilities")
            # Summarize CAPA
            if 'rules' in capa:
                for rule, data in capa['rules'].items():
                     lines.append(f"- **{rule}**: {len(data.get('matches', []))} matches")
            else:
                lines.append(json.dumps(capa, indent=2)) # Fallback if structure varies
        
        # FLOSS
        floss = analysis_data.get("floss", [])
        if floss:
            lines.append("## FLOSS Strings (Top 100)")
            for s in floss[:100]:
                 lines.append(f"- `{s}`")
                 
        # IDA
        ida = analysis_data.get("ida", {})
        if ida:
            lines.append("## IDA Pro Analysis")
            funcs = ida.get("functions", [])
            lines.append(f"### Functions Found: {len(funcs)}")
            
            decompiled = ida.get("decompiled", {})
            if decompiled:
                lines.append("### Decompiled Code Snippets")
                for addr, code in decompiled.items():
                    lines.append(f"#### Address {addr}")
                    lines.append("```c")
                    # Assuming code is a string or result object
                    # mcp TextContent
                    if hasattr(code, 'content') and code.content:
                         lines.append(code.content[0].text)
                    else:
                         lines.append(str(code))
                    lines.append("```")

        # Fallback for DotNET/Script info
        info = analysis_data.get("info")
        if info:
            lines.append(f"## Specific Info: {info}")

        return "\n".join(lines)
