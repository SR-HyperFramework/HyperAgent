"""VMware Workstation tool wrappers.

Each vmrun command is exposed as a ``ToolDefinition`` so the LLM can
orchestrate the guest VM lifecycle during prepare-env, unpack, and dynamic
stages.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

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


def vm_check_vmrun(**_kw) -> ToolResult:
    """Resolve ``vmrun`` via PATH instead of guessing install directories.

    ``_run_vmrun`` already invokes the bare ``vmrun`` command and relies on
    PATH resolution, so probing hardcoded ``Program Files`` locations with
    ``file_exists`` is both unnecessary and unreliable (VMware Workstation is
    not always installed under ``Program Files``, e.g. custom drive/paths).
    """
    found = shutil.which("vmrun")
    if found:
        return ToolResult(content=f"vmrun found on PATH: {found}")
    return ToolResult(content="vmrun not found on PATH", is_error=True)


def vm_auto_revert_after_dynamic(config: VMwareConfig) -> ToolResult:
    """Revert the VM to the clean snapshot after the dynamic stage finishes.

    This is a host-side safety hook for the launcher, not an LLM-callable tool.
    """
    return _run_vmrun(
        ["-T", "ws", "revertToSnapshot", config.vmx_path, config.snapshot_name],
        timeout=config.command_timeout,
    )


def create_vmware_tools(config: VMwareConfig) -> list[ToolDefinition]:
    """Build VMware tool definitions from the current config."""
    vmx = config.vmx_path
    snap = config.snapshot_name
    user = config.guest_user
    pwd = config.guest_password
    desktop = config.guest_desktop
    debugger = config.guest_debugger
    startup_timeout = config.startup_timeout
    command_timeout = config.command_timeout

    def revert_snapshot(**_kw) -> ToolResult:
        return _run_vmrun(["-T", "ws", "revertToSnapshot", vmx, snap], timeout=command_timeout)

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
        # Large samples (100+ MB) routinely exceed the base command_timeout over
        # CopyFileFromHostToGuest, so this scales the budget with file size instead
        # of hardcoding a bigger constant that would still be wrong for some sample.
        try:
            file_size = Path(host_path).stat().st_size
        except OSError:
            file_size = 0
        copy_timeout = max(command_timeout, startup_timeout, int(file_size / (1024 * 1024)) * 5)
        return _run_vmrun(
            ["-T", "ws", "-gu", user, "-gp", pwd,
             "CopyFileFromHostToGuest", vmx, host_path, guest_path],
            timeout=copy_timeout,
        )

    def run_program_in_guest(guest_program: str = "", guest_args: str = "", **_kw) -> ToolResult:
        program = guest_program or debugger
        args_parts = ["-T", "ws", "-gu", user, "-gp", pwd,
                      "runProgramInGuest", vmx, "-noWait", program]
        if guest_args:
            args_parts.append(guest_args)
        return _run_vmrun(args_parts, timeout=command_timeout)

    def run_debugger_with_sample(sample_filename: str = "", **_kw) -> ToolResult:
        if not sample_filename:
            return ToolResult(content="sample_filename is required", is_error=True)
        guest_sample = f"{desktop}\\{sample_filename}"
        return _run_vmrun(
            ["-T", "ws", "-gu", user, "-gp", pwd,
             "runProgramInGuest", vmx, "-noWait", debugger, guest_sample],
            timeout=command_timeout,
        )

    return [
        ToolDefinition(
            name="vm_check_vmrun",
            description=(
                "Resolve the vmrun executable via PATH. Call this first to confirm "
                "VMware tooling is accessible instead of guessing install paths."
            ),
            parameters={"type": "object", "properties": {}},
            handler=vm_check_vmrun,
            source="vm",
        ),
        ToolDefinition(
            name="vm_revert_snapshot",
            description="Revert the analysis VM to the clean snapshot.",
            parameters={"type": "object", "properties": {}},
            handler=revert_snapshot,
            source="vm",
        ),
        ToolDefinition(
            name="vm_start",
            description="Start the analysis VM (headless).",
            parameters={"type": "object", "properties": {}},
            handler=start_vm,
            source="vm",
        ),
        ToolDefinition(
            name="vm_get_guest_ip",
            description="Wait for the guest OS to be ready and return its IP address.",
            parameters={"type": "object", "properties": {}},
            handler=get_guest_ip,
            source="vm",
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
            source="vm",
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
            source="vm",
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
            source="vm",
        ),
    ]
