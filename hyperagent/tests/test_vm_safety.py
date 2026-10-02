"""VM safety hook tests."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from hyperagent.config import VMwareConfig
from hyperagent.tools.path_scope import PathScope
from hyperagent.tools.vmware_tools import create_vmware_tools, vm_auto_revert_after_dynamic


class _Completed:
    def __init__(self, *, returncode: int = 0, stdout: str = "OK", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr



def _scope(root: Path) -> PathScope:
    return PathScope(read_roots=(root,), write_roots=(root,))



def _tool_from(tools, name: str):
    for tool in tools:
        if tool.name == name:
            return tool
    raise AssertionError(f"tool {name} not found")


@pytest.fixture()
def scoped_root(tmp_path: Path) -> Path:
    root = tmp_path / "scoped"
    root.mkdir()
    return root


@pytest.fixture()
def scope(scoped_root: Path) -> PathScope:
    return _scope(scoped_root)


@pytest.fixture()
def outside_path(tmp_path: Path) -> Path:
    outside = tmp_path / "outside.exe"
    outside.write_bytes(b"MZ")
    return outside


@pytest.fixture()
def inside_path(scope: PathScope) -> Path:
    path = scope.read_roots[0] / "sample.exe"
    path.write_bytes(b"MZ")
    return path


@pytest.fixture()
def vm_tools(scope: PathScope):
    return create_vmware_tools(VMwareConfig(), scope)


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


def test_vm_auto_revert_after_dynamic_is_not_llm_callable(scope):
    names = {tool.name for tool in create_vmware_tools(VMwareConfig(), scope)}
    assert "vm_auto_revert_after_dynamic" not in names
    assert "vm_revert_snapshot" in names


def test_vm_copy_to_guest_rejects_out_of_scope_host_path(vm_tools, outside_path):
    res = _tool_from(vm_tools, "vm_copy_to_guest").handler(
        host_path=str(outside_path),
        guest_filename="sample.exe",
    )
    assert res.is_error
    assert "allowed analysis scope" in res.content


def test_vm_copy_to_guest_allows_in_scope_host_path(monkeypatch, vm_tools, inside_path):
    calls: list[list[str]] = []

    def fake_run(cmd, capture_output, text, timeout, shell):
        calls.append(cmd)
        return _Completed(stdout="copied")

    monkeypatch.setattr(subprocess, "run", fake_run)

    res = _tool_from(vm_tools, "vm_copy_to_guest").handler(
        host_path=str(inside_path),
        guest_filename="sample.exe",
    )

    assert not res.is_error
    assert calls
    assert str(inside_path) in calls[0]


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
