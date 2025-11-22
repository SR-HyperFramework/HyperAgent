import subprocess
import shutil
import json
from typing import Optional

def run_die(file_path: str) -> dict:
    """
    Runs DIE (Detect It Easy) on the given file.
    Assumes 'diec' is in the PATH.
    """
    die_path = shutil.which("diec")
    
    if not die_path:
        # Fallback/Mock for development if tool is missing
        return {
            "raw": "DIE tool not found in PATH",
            "parsed": {"info": "Mock Result: DIE tool missing"},
            "error": "Tool not found"
        }

    # die_path = "../../resource/diec/diec.exe"
    try:
        # 1. Run for detailed info
        result_info = subprocess.run(
            [die_path, "-b", "-p", "-u", file_path], 
            capture_output=True, 
            text=True, 
            check=False
        )
        
        # 2. Run for entropy
        result_entropy = subprocess.run(
            [die_path, "-p", "-e", file_path], 
            capture_output=True, 
            text=True, 
            check=False
        )
        
        raw_output = result_info.stdout
        parsed = {}
        entropy = None
        
        if result_info.returncode == 0:
            # Parse text output from info run
            parsed = parse_die_text_output(raw_output)
            
            # Parse entropy from entropy run
            if result_entropy.returncode == 0:
                entropy = extract_entropy(result_entropy.stdout)
                # Append entropy output to raw for debugging/completeness if needed
                # raw_output += "\n--- Entropy Run ---\n" + result_entropy.stdout
        else:
            return {
                "raw": result_info.stderr,
                "error": f"DIE exited with code {result_info.returncode}"
            }

        return {
            "raw": raw_output,
            "parsed": parsed,
            "entropy": entropy
        }

    except Exception as e:
        return {
            "raw": "",
            "error": str(e)
        }

def extract_entropy(text: str) -> Optional[float]:
    """
    Extracts the total entropy value from DIE output, which often appears
    in a line starting with "Total".
    """
    for line in text.splitlines():
        line_stripped = line.strip()
        if line_stripped.startswith("Total "):
            try:
                # Example: "Total 7.60693: packed"
                # Extract the part between "Total " and ":"
                parts = line_stripped.split(" ")
                # The entropy value should be the second part (index 1)
                if len(parts) > 1:
                    value_str = parts[1].split(":")[0].strip()
                    return float(value_str)
            except (ValueError, IndexError):
                pass
    return None

def parse_die_text_output(text: str) -> dict:
    """
    Parses the text output from DIE to extract relevant fields.
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
        # Skip empty lines
        if not line.strip():
            continue
            
        # Skip log lines (heuristic scan logs usually start with [)
        if line.strip().startswith("["):
            continue
            
        # Check for File Class (usually a single word at the start of a block, not indented)
        # e.g. "PE64"
        # We assume if it has no indentation and no colon, it's the file class.
        if not line.startswith(" ") and ":" not in line:
            result["file_class"] = line.strip()
            continue
            
        # Parse Key-Value pairs
        if ":" in line:
            parts = line.split(":", 1)
            key = parts[0].strip().lower()
            value = parts[1].strip()
            
            if "compiler" in key:
                result["compiler"] = value
            elif "language" in key:
                result["language"] = value
            elif "packer" in key:
                result["packer"] = value
            elif "linker" in key:
                # Sometimes Linker is relevant if Packer is missing, 
                # but we'll store it in packer if packer is null? 
                # Or just ignore for now unless requested.
                # Let's store it in a separate key if we want, or map to packer?
                # User asked for "hint.packer". 
                # Let's keep it separate or maybe use it as fallback.
                if not result["packer"]:
                    result["packer"] = value # Fallback
            elif "library" in key:
                result["library"] = value
            elif "tool" in key:
                result["tool"] = value
            elif "malware" in key:
                result["malware"] = value
                
    return result
