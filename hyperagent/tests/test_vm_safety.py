"""VM safety hook tests."""
from __future__ import annotations

import subprocess

from hyperagent.config import VMwareConfig
from hyperagent.tools.vmware_tools import create_vmware_tools, vm_auto_revert_after_dynamic


class _Completed:
    def __init__(self, *, returncode: int = 0, stdout: str = "OK", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_vm_auto_revert_after_dynamic_calls_vmrun(monkeypatch):
    calls: list[dict[str, object]] = []

    def fake_run(cmd, capture_output, text, timeout, shell):
        calls.append(
            {
                "cmd": cmd,
                "capture_output": capture_output,
                "text": text,
                "timeout": timeout,
                "shell": shell,
            }
        )
        return _Completed(stdout="reverted")

    monkeypatch.setattr(subprocess, "run", fake_run)

    config = VMwareConfig(
        vmx_path=r"C:\VMs\sandbox.vmx",
        snapshot_name="clean-snapshot",
        command_timeout=45,
    )

    result = vm_auto_revert_after_dynamic(config)

    assert not result.is_error
    assert result.content == "reverted"
    assert calls == [
        {
            "cmd": [
                "vmrun",
                "-T",
                "ws",
                "revertToSnapshot",
                r"C:\VMs\sandbox.vmx",
                "clean-snapshot",
            ],
            "capture_output": True,
            "text": True,
            "timeout": 45,
            "shell": False,
        }
    ]


def test_vm_auto_revert_after_dynamic_is_not_llm_callable():
    names = {tool.name for tool in create_vmware_tools(VMwareConfig())}
    assert "vm_auto_revert_after_dynamic" not in names
    assert "vm_revert_snapshot" in names


def test_vm_auto_revert_after_dynamic_surfaces_vmrun_errors(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout, shell):
        return _Completed(returncode=1, stderr="snapshot missing")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = vm_auto_revert_after_dynamic(
        VMwareConfig(vmx_path="sandbox.vmx", snapshot_name="clean", command_timeout=10)
    )

    assert result.is_error
    assert "snapshot missing" in result.content
    assert "exit 1" in result.content
