import subprocess
import json
import os
import yaml
from enum import Enum, auto
from typing import Dict, Any, Optional

class AnalysisType(Enum):
    NATIVE = auto()
    DOTNET = auto()
    PYTHON_SCRIPT = auto()
    UNKNOWN = auto()

class DIEHandler:
    def __init__(self, config_path: str = "config.yaml"):
        self.config = self._load_config(config_path)
        self.die_path = self.config.get("tools", {}).get("diec", "diec.exe")

    def _load_config(self, path: str) -> Dict[str, Any]:
        try:
            with open(path, "r") as f:
                return yaml.safe_load(f)
        except Exception as e:
            print(f"Error loading config: {e}")
            return {}

    def parse_die_text_output(self, text: str) -> dict:
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
                    if not result["packer"]:
                        result["packer"] = value # Fallback
                elif "library" in key:
                    result["library"] = value
                elif "tool" in key:
                    result["tool"] = value
                elif "malware" in key:
                    result["malware"] = value
                    
        return result

    def run_die(self, file_path: str) -> Dict[str, Any]:
        """Runs diec.exe -b -p -u <file> and returns parsed result."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        try:
            # Command: diec.exe -b -p -u "path/to/file"
            # -b: basic info? -p: packer? -u: unknown? (User specific flags)
            # Assuming these flags produce the text output expected by the parser
            cmd = [self.die_path, "-b", "-p", "-u", file_path]
            
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            
            if result.returncode != 0:
                print(f"DIE Error: {result.stderr}")
                # Sometimes DIE returns non-zero even if it found something?
            
            # Use the new parser
            return self.parse_die_text_output(result.stdout)

        except Exception as e:
            print(f"Error running DIE: {e}")
            return {}

    def get_analysis_route(self, file_path: str) -> AnalysisType:
        """Determines the analysis route based on DIE output."""
        _, analysis_type = self.identify(file_path)
        return analysis_type

    def identify(self, file_path: str):
        """Runs DIE once and returns (die_data, AnalysisType)."""
        data = self.run_die(file_path)

        library = (data.get("library") or "").lower()
        compiler = (data.get("compiler") or "").lower()
        language = (data.get("language") or "").lower()
        packer = (data.get("packer") or "").lower()
        file_class = (data.get("file_class") or "").lower()

        is_dotnet = ".net" in library or ".net" in compiler
        is_python = "python" in language or file_path.lower().endswith(".py")

        if is_dotnet:
            return data, AnalysisType.DOTNET
        if is_python:
            return data, AnalysisType.PYTHON_SCRIPT
        if file_class or compiler or packer:
            return data, AnalysisType.NATIVE
        return data, AnalysisType.UNKNOWN

if __name__ == "__main__":
    # Internal test
    handler = DIEHandler()
    # Mock usage:
    # print(handler.get_analysis_route("test_file.exe"))
