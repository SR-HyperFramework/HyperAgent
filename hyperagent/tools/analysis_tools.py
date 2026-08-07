"""Safe, bounded subprocess tools for malware analysis.

Replaces the generic shell_tools.py to prevent Prompt-Injection driven
Remote Code Execution (RCE) and Server-Side Request Forgery (SSRF).
Only explicitly whitelisted binaries and scripts can be executed.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .base import ToolDefinition, ToolResult


def _run_bounded(
    cmd_parts: list[str], cwd: str | None = None, timeout: int = 60
) -> ToolResult:
    """Run a specific command with shell=False to prevent shell injection."""
    try:
        completed = subprocess.run(
            cmd_parts,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            shell=False,
        )
        output = completed.stdout
        if completed.stderr:
            output += f"\n--- stderr ---\n{completed.stderr}"
        if completed.returncode != 0:
            return ToolResult(
                content=output.strip() or f"Error (exit {completed.returncode})",
                is_error=True,
            )
        return ToolResult(content=output.strip() or "Success (no output)")
    except subprocess.TimeoutExpired:
        return ToolResult(content=f"Timed out after {timeout}s", is_error=True)
    except FileNotFoundError as exc:
        return ToolResult(content=f"Command not found: {exc}", is_error=True)
    except Exception as exc:
        return ToolResult(content=f"Execution error: {exc}", is_error=True)


def _get_scripts_dir() -> Path:
    """Resolve the directory containing helper Python scripts."""
    # Fallback to a default skills/scripts path if not specified
    scripts_dir = os.environ.get("HYPERAGENT_SCRIPTS_DIR")
    if scripts_dir:
        return Path(scripts_dir)
    return Path.home() / ".claude" / "skills" / "scripts"


# -- Bounded Wrappers --------------------------------------------------------

def _upx_unpack(input_path: str = "", output_path: str = "", **_kw) -> ToolResult:
    """Run `upx -d -o <output> <input>`."""
    if not input_path or not output_path:
        return ToolResult(content="input_path and output_path required", is_error=True)
    return _run_bounded(["upx", "-d", "-o", output_path, input_path])


def _fetch_vt_report(sha256: str = "", endpoint: str = "", output_path: str = "", **_kw) -> ToolResult:
    """Run fetch_vt_file_report.py."""
    if not sha256 or not endpoint or not output_path:
        return ToolResult(content="sha256, endpoint, output_path required", is_error=True)
    
    script_path = _get_scripts_dir() / "fetch_vt_file_report.py"
    if not script_path.exists():
        return ToolResult(content=f"Script not found: {script_path}", is_error=True)

    return _run_bounded([
        sys.executable, str(script_path),
        "--sha256", sha256,
        "--endpoint", endpoint,
        "--output", output_path
    ])


def _normalize_vt_report(input_json: str = "", output_json: str = "", **_kw) -> ToolResult:
    """Run normalize_vt_to_intel.py."""
    if not input_json or not output_json:
        return ToolResult(content="input_json, output_json required", is_error=True)
        
    script_path = _get_scripts_dir() / "normalize_vt_to_intel.py"
    if not script_path.exists():
        return ToolResult(content=f"Script not found: {script_path}", is_error=True)

    return _run_bounded([
        sys.executable, str(script_path),
        "--input", input_json,
        "--output", output_json
    ])


def _validate_json_output(schema_path: str = "", json_path: str = "", **_kw) -> ToolResult:
    """Run validate_output.py."""
    if not schema_path or not json_path:
        return ToolResult(content="schema_path, json_path required", is_error=True)
        
    script_path = _get_scripts_dir() / "validate_output.py"
    if not script_path.exists():
        return ToolResult(content=f"Script not found: {script_path}", is_error=True)

    return _run_bounded([
        sys.executable, str(script_path),
        "--schema", schema_path,
        "--json", json_path
    ])


def create_analysis_tools() -> list[ToolDefinition]:
    """Return bounded analysis tool definitions."""
    return [
        ToolDefinition(
            name="upx_unpack",
            description="Unpack a UPX-compressed binary.",
            parameters={
                "type": "object",
                "properties": {
                    "input_path": {"type": "string"},
                    "output_path": {"type": "string"},
                },
                "required": ["input_path", "output_path"],
            },
            handler=_upx_unpack,
        ),
        ToolDefinition(
            name="fetch_vt_report",
            description="Fetch a VirusTotal report for a given SHA256.",
            parameters={
                "type": "object",
                "properties": {
                    "sha256": {"type": "string"},
                    "endpoint": {"type": "string"},
                    "output_path": {"type": "string"},
                },
                "required": ["sha256", "endpoint", "output_path"],
            },
            handler=_fetch_vt_report,
        ),
        ToolDefinition(
            name="normalize_vt_report",
            description="Normalize raw VT JSON into Intel format.",
            parameters={
                "type": "object",
                "properties": {
                    "input_json": {"type": "string"},
                    "output_json": {"type": "string"},
                },
                "required": ["input_json", "output_json"],
            },
            handler=_normalize_vt_report,
        ),
        ToolDefinition(
            name="validate_json_output",
            description="Validate a JSON file against a JSON schema.",
            parameters={
                "type": "object",
                "properties": {
                    "schema_path": {"type": "string"},
                    "json_path": {"type": "string"},
                },
                "required": ["schema_path", "json_path"],
            },
            handler=_validate_json_output,
        ),
    ]
