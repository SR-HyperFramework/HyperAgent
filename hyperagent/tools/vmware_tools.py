"""VMware Workstation tool wrappers.

Each vmrun command is exposed as a ``ToolDefinition`` so the LLM can
orchestrate the guest VM lifecycle during prepare-env, unpack, and dynamic
stages.
"""
from __future__ import annotations

import subprocess
import sys

from ..config import VMwareConfig
from .base import ToolDefinition, ToolResult


def _run_vmrun(args: list[str], timeout: int = 30) -> ToolResult:
    """Execute a vmrun command and return the result."""
    cmd = ["vmrun"] + args
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        if completed.returncode != 0:
            return ToolResult(
                content=f"vmrun failed (exit {completed.returncode}): {completed.stderr.strip()}",
                is_error=True,
            )
        return ToolResult(content=completed.stdout.strip() or "OK")
    except subprocess.TimeoutExpired:
        return ToolResult(content=f"vmrun timed out after {timeout}s", is_error=True)
    except FileNotFoundError:
        return ToolResult(content="vmrun executable not found on PATH", is_error=True)


def create_vmware_tools(config: VMwareConfig) -> list[ToolDefinition]:
    """Build VMware tool definitions from the current config."""
    vmx = config.vmx_path
    snap = config.snapshot_name
    user = config.guest_user
    pwd = config.guest_password
    desktop = config.guest_desktop
    debugger = config.guest_debugger
    startup_timeout = config.startup_timeout

    def revert_snapshot(**_kw) -> ToolResult:
        return _run_vmrun(["-T", "ws", "revertToSnapshot", vmx, snap])

    def start_vm(**_kw) -> ToolResult:
        return _run_vmrun(["-T", "ws", "start", vmx, "nogui"], timeout=startup_timeout)

    def get_guest_ip(**_kw) -> ToolResult:
        return _run_vmrun(
            ["-T", "ws", "getGuestIPAddress", vmx, "-wait"],
            timeout=startup_timeout,
        )

    def copy_to_guest(host_path: str = "", guest_filename: str = "", **_kw) -> ToolResult:
        if not host_path or not guest_filename:
            return ToolResult(content="host_path and guest_filename are required", is_error=True)
        guest_path = f"{desktop}\\{guest_filename}"
        return _run_vmrun(
            ["-T", "ws", "-gu", user, "-gp", pwd,
             "CopyFileFromHostToGuest", vmx, host_path, guest_path],
        )

    def run_program_in_guest(guest_program: str = "", guest_args: str = "", **_kw) -> ToolResult:
        program = guest_program or debugger
        args_parts = ["-T", "ws", "-gu", user, "-gp", pwd,
                      "runProgramInGuest", vmx, "-noWait", program]
        if guest_args:
            args_parts.append(guest_args)
        return _run_vmrun(args_parts)

    def run_debugger_with_sample(sample_filename: str = "", **_kw) -> ToolResult:
        if not sample_filename:
            return ToolResult(content="sample_filename is required", is_error=True)
        guest_sample = f"{desktop}\\{sample_filename}"
        return _run_vmrun(
            ["-T", "ws", "-gu", user, "-gp", pwd,
             "runProgramInGuest", vmx, "-noWait", debugger, guest_sample],
        )

    return [
        ToolDefinition(
            name="vm_revert_snapshot",
            description="Revert the analysis VM to the clean snapshot.",
            parameters={"type": "object", "properties": {}},
            handler=revert_snapshot,
        ),
        ToolDefinition(
            name="vm_start",
            description="Start the analysis VM (headless).",
            parameters={"type": "object", "properties": {}},
            handler=start_vm,
        ),
        ToolDefinition(
            name="vm_get_guest_ip",
            description="Wait for the guest OS to be ready and return its IP address.",
            parameters={"type": "object", "properties": {}},
            handler=get_guest_ip,
        ),
        ToolDefinition(
            name="vm_copy_to_guest",
            description="Copy a file from the host into the guest VM desktop.",
            parameters={
                "type": "object",
                "properties": {
                    "host_path": {"type": "string", "description": "Absolute host path to the file"},
                    "guest_filename": {"type": "string", "description": "Filename on the guest desktop"},
                },
                "required": ["host_path", "guest_filename"],
            },
            handler=copy_to_guest,
        ),
        ToolDefinition(
            name="vm_run_program",
            description="Run an arbitrary program inside the guest VM (non-blocking).",
            parameters={
                "type": "object",
                "properties": {
                    "guest_program": {"type": "string", "description": "Full guest path to the program"},
                    "guest_args": {"type": "string", "description": "Command-line arguments"},
                },
                "required": ["guest_program"],
            },
            handler=run_program_in_guest,
        ),
        ToolDefinition(
            name="vm_run_debugger_with_sample",
            description="Launch x64dbg in the guest with the sample as its argument.",
            parameters={
                "type": "object",
                "properties": {
                    "sample_filename": {"type": "string", "description": "Sample filename on the guest desktop"},
                },
                "required": ["sample_filename"],
            },
            handler=run_debugger_with_sample,
        ),
    ]
