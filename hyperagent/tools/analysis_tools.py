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
from .path_scope import PathScope, PathScopeError


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


def _get_scripts_dir(scripts_dir: str | Path | None = None) -> Path:
    """Resolve the directory containing the `_hyperagent-common` helper scripts.

    Resolution order: explicit argument -> ``HYPERAGENT_SCRIPTS_DIR`` env ->
    ``HYPERAGENT_SKILLS_ROOT`` env (or ``~/.claude/skills`` default) joined
    with the ``_hyperagent-common/scripts`` layout used by the real skill.
    """
    if scripts_dir:
        return Path(scripts_dir)

    env_scripts_dir = os.environ.get("HYPERAGENT_SCRIPTS_DIR")
    if env_scripts_dir:
        return Path(env_scripts_dir)

    skills_root = os.environ.get("HYPERAGENT_SKILLS_ROOT") or str(
        Path.home() / ".claude" / "skills"
    )
    return Path(skills_root) / "_hyperagent-common" / "scripts"


# -- Bounded Wrappers --------------------------------------------------------

def _make_upx_unpack(scripts_dir: Path, scope: PathScope):
    def upx_unpack(input_path: str = "", output_path: str = "", **_kw) -> ToolResult:
        """Run `upx -d -o <output> <input>`."""
        if not input_path or not output_path:
            return ToolResult(content="input_path and output_path required", is_error=True)
        try:
            scoped_input = scope.check_read(input_path)
            scoped_output = scope.check_write(output_path)
        except PathScopeError as exc:
            return ToolResult(content=str(exc), is_error=True)
        return _run_bounded(["upx", "-d", "-o", str(scoped_output), str(scoped_input)])

    return upx_unpack


def _make_fetch_vt_report(scripts_dir: Path, scope: PathScope):
    def fetch_vt_report(
        file_id: str = "",
        output_path: str = "",
        endpoint: str = "file_info",
        api_key: str = "",
        timeout: float | None = None,
        indent: int | None = None,
        include_meta: bool = False,
        **_kw,
    ) -> ToolResult:
        """Run fetch_vt_file_report.py."""
        if not file_id or not output_path:
            return ToolResult(content="file_id and output_path required", is_error=True)

        script_path = scripts_dir / "fetch_vt_file_report.py"
        if not script_path.exists():
            return ToolResult(content=f"Script not found: {script_path}", is_error=True)

        try:
            scoped_output = scope.check_write(output_path)
        except PathScopeError as exc:
            return ToolResult(content=str(exc), is_error=True)

        cmd = [
            sys.executable, str(script_path),
            file_id,
            "--endpoint", endpoint,
            "-o", str(scoped_output),
        ]
        if api_key:
            cmd += ["--api-key", api_key]
        if timeout is not None:
            cmd += ["--timeout", str(timeout)]
        if indent is not None:
            cmd += ["--indent", str(indent)]
        if include_meta:
            cmd.append("--include-meta")
        return _run_bounded(cmd)

    return fetch_vt_report


def _make_normalize_vt_report(scripts_dir: Path, scope: PathScope):
    def normalize_vt_report(
        file_info_path: str = "",
        behaviour_summary_path: str = "",
        output_path: str = "",
        local_context_path: str = "",
        sample_sha256: str = "",
        upstream_inputs: list[str] | None = None,
        validate: bool = False,
        schema_path: str = "",
        indent: int | None = None,
        **_kw,
    ) -> ToolResult:
        """Run normalize_vt_to_intel.py."""
        if not file_info_path and not behaviour_summary_path:
            return ToolResult(
                content="At least one of file_info_path or behaviour_summary_path is required",
                is_error=True,
            )
        if not output_path:
            return ToolResult(content="output_path required", is_error=True)

        script_path = scripts_dir / "normalize_vt_to_intel.py"
        if not script_path.exists():
            return ToolResult(content=f"Script not found: {script_path}", is_error=True)

        try:
            scoped_file_info = str(scope.check_read(file_info_path)) if file_info_path else ""
            scoped_behaviour = str(scope.check_read(behaviour_summary_path)) if behaviour_summary_path else ""
            scoped_local_context = str(scope.check_read(local_context_path)) if local_context_path else ""
            scoped_schema = str(scope.check_read(schema_path)) if schema_path else ""
            scoped_upstream_inputs = [str(scope.check_read(path)) for path in (upstream_inputs or [])]
            scoped_output = scope.check_write(output_path)
        except PathScopeError as exc:
            return ToolResult(content=str(exc), is_error=True)

        cmd = [sys.executable, str(script_path)]
        if scoped_file_info:
            cmd += ["--file-info", scoped_file_info]
        if scoped_behaviour:
            cmd += ["--behaviour-summary", scoped_behaviour]
        if scoped_local_context:
            cmd += ["--local-context", scoped_local_context]
        if sample_sha256:
            cmd += ["--sample-sha256", sample_sha256]
        for upstream_input in scoped_upstream_inputs:
            cmd += ["--upstream-input", upstream_input]
        if validate:
            cmd.append("--validate")
        if scoped_schema:
            cmd += ["--schema", scoped_schema]
        cmd += ["-o", str(scoped_output)]
        if indent is not None:
            cmd += ["--indent", str(indent)]
        return _run_bounded(cmd)

    return normalize_vt_report


def _make_validate_json_output(scripts_dir: Path, scope: PathScope):
    def validate_json_output(schema_path: str = "", json_path: str = "", **_kw) -> ToolResult:
        """Run validate_output.py."""
        if not schema_path or not json_path:
            return ToolResult(content="schema_path, json_path required", is_error=True)

        script_path = scripts_dir / "validate_output.py"
        if not script_path.exists():
            return ToolResult(content=f"Script not found: {script_path}", is_error=True)

        try:
            scoped_schema = scope.check_read(schema_path)
            scoped_json = scope.check_read(json_path)
        except PathScopeError as exc:
            return ToolResult(content=str(exc), is_error=True)

        return _run_bounded([sys.executable, str(script_path), str(scoped_schema), str(scoped_json)])

    return validate_json_output


def create_analysis_tools(scripts_dir: str | Path | None = None, scope: PathScope | None = None) -> list[ToolDefinition]:
    """Return bounded analysis tool definitions.

    ``scripts_dir`` overrides the resolved ``_hyperagent-common/scripts``
    directory — used by tests to point at fixture scripts.
    """
    if scope is None:
        raise ValueError("create_analysis_tools requires a PathScope")

    resolved_scripts_dir = _get_scripts_dir(scripts_dir)

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
            handler=_make_upx_unpack(resolved_scripts_dir, scope),
            source="analysis",
        ),
        ToolDefinition(
            name="fetch_vt_report",
            description="Fetch a VirusTotal report for a file by MD5, SHA-1, or SHA-256. "
                        "Writes JSON to output_path (never returned inline).",
            parameters={
                "type": "object",
                "properties": {
                    "file_id": {"type": "string", "description": "MD5, SHA-1, or SHA-256 hash"},
                    "output_path": {"type": "string", "description": "Where to write the JSON result"},
                    "endpoint": {
                        "type": "string",
                        "enum": ["file_info", "behaviour_summary"],
                        "default": "file_info",
                    },
                    "api_key": {"type": "string"},
                    "timeout": {"type": "number"},
                    "indent": {"type": "integer"},
                    "include_meta": {"type": "boolean"},
                },
                "required": ["file_id", "output_path"],
            },
            handler=_make_fetch_vt_report(resolved_scripts_dir, scope),
            source="analysis",
        ),
        ToolDefinition(
            name="normalize_vt_report",
            description="Normalize raw VT file_info/behaviour_summary JSON into a HyperAgent "
                        "intel-stage document. Writes JSON to output_path.",
            parameters={
                "type": "object",
                "properties": {
                    "file_info_path": {"type": "string"},
                    "behaviour_summary_path": {"type": "string"},
                    "output_path": {"type": "string"},
                    "local_context_path": {"type": "string"},
                    "sample_sha256": {"type": "string"},
                    "upstream_inputs": {"type": "array", "items": {"type": "string"}},
                    "validate": {"type": "boolean"},
                    "schema_path": {"type": "string"},
                    "indent": {"type": "integer"},
                },
                "required": ["output_path"],
                "anyOf": [
                    {"required": ["file_info_path"]},
                    {"required": ["behaviour_summary_path"]},
                ],
            },
            handler=_make_normalize_vt_report(resolved_scripts_dir, scope),
            source="analysis",
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
            handler=_make_validate_json_output(resolved_scripts_dir, scope),
            source="analysis",
        ),
    ]
