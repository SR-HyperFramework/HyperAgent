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
            [die_path, "-b", "--json", file_path], 
            capture_output=True, 
            text=True, 
            check=False
        )
        
        raw_output = result.stdout
        parsed = {}
        
        if result.returncode == 0:
            try:
                parsed = json.loads(raw_output)
                with open("die_result.json", "w") as f:
                    json.dump(parsed, f, indent=4)
            except json.JSONDecodeError:
                parsed = {"error": "Could not parse JSON output"}
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
