import subprocess
import shutil
import json

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
        # Run diec with json output if possible, or just raw
        # Assuming 'diec -j <file>' gives JSON. 
        # If not, we might need to parse text.
        # For now, let's try to get raw output.
        result = subprocess.run(
            [die_path, "-b", "-p", "-u", file_path], 
            capture_output=True, 
            text=True, 
            check=False
        )
        
        raw_output = result.stdout
        parsed = {}
        
        if result.returncode == 0:
            # Parse text output
            parsed_data = parse_die_text_output(raw_output)
            parsed = parsed_data
        else:
            return {
                "raw": result.stderr,
                "error": f"DIE exited with code {result.returncode}"
            }

        return {
            "raw": raw_output,
            "parsed": parsed
        }

    except Exception as e:
        return {
            "raw": "",
            "error": str(e)
        }

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
        "tool": None
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
                
    return result
