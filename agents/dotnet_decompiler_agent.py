from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass
from typing import Any, Optional

from core.pipeline_logger import PipelineLogger
from core.task_runtime import create_child_task_scope, run_tracked_process
from core.tool_policy import resolve_candidate_path, resolve_tool_path


@dataclass
class DotNetPreparation:
    target_file: str
    source_directory: str
    decompiled: bool
    cleaned_file: str | None
    key_files: list[str]


class DotNetDecompilerAgent:
    def __init__(self, config: dict[str, Any], output_root: str, repo_root: str, resolve_executable=None):
        self.config = config
        self.output_root = output_root
        self.repo_root = repo_root
        self.resolve_executable = resolve_executable or self._resolve_executable

    def _tool_config(self, key: str) -> str | None:
        tools = (self.config or {}).get("tools") or {}
        value = tools.get(key)
        return str(value) if value else None

    def _resolve_executable(self, configured: str | None, fallbacks: list[str]) -> str | None:
        return resolve_candidate_path(configured, fallbacks, repo_root=self.repo_root)

    def _abs_path(self, path: str) -> str:
        return os.path.normpath(os.path.abspath(os.path.expandvars(os.path.expanduser(path))))

    def _to_workspace_rel_posix(self, path: str) -> str:
        repo_root_abs = self._abs_path(self.repo_root)
        path_abs = self._abs_path(path)
        try:
            rel = os.path.relpath(path_abs, start=repo_root_abs)
        except Exception:
            rel = path_abs
        return rel.replace("\\", "/")

    def pick_interesting_cs_files(self, base_dir: str, limit: int = 15) -> list[str]:
        base_abs = self._abs_path(base_dir)
        if not os.path.isdir(base_abs):
            return []

        interesting_names = {
            "program.cs",
            "assemblyloader.cs",
            "app.xaml.cs",
            "mainwindow.xaml.cs",
        }
        keywords = ("load", "inject", "decrypt", "encrypt", "http", "socket", "dns", "web", "download", "shell", "process", "registry")

        hits: list[str] = []
        others: list[str] = []

        for root, _, files in os.walk(base_abs):
            for name in files:
                if not name.lower().endswith(".cs"):
                    continue
                full = os.path.join(root, name)
                rel = self._to_workspace_rel_posix(full)
                low = name.lower()
                if low in interesting_names or any(k in low for k in keywords):
                    hits.append(rel)
                else:
                    others.append(rel)

        hits.sort()
        others.sort()

        result = hits[:limit]
        if len(result) < limit:
            result.extend(others[: limit - len(result)])
        return result

    async def run_de4dot(
        self,
        file_path: str,
        pipeline_logger: Optional[PipelineLogger] = None,
    ) -> str:
        de4dot_logger = pipeline_logger
        if pipeline_logger:
            _, de4dot_logger = create_child_task_scope(
                pipeline_logger,
                stage_key="dotnet_agent.de4dot",
                title="Run de4dot cleanup",
            )

        de4dot = resolve_tool_path(self.config, "de4dot", ["de4dot.exe", "de4dot"], repo_root=self.repo_root)
        if not de4dot:
            if de4dot_logger:
                de4dot_logger.log("dotnet_agent.de4dot", "skipped", "de4dot tool not found")
            return file_path

        file_path = self._abs_path(file_path)
        if de4dot_logger:
            de4dot_logger.log("dotnet_agent.de4dot", "started", "Starting de4dot cleanup")

        returncode, _, _ = await run_tracked_process(
            de4dot,
            file_path,
            pipeline_logger=de4dot_logger,
        )

        root, ext = os.path.splitext(file_path)
        cleaned_path = f"{root}-cleaned{ext}"
        if returncode == 0 and os.path.exists(cleaned_path):
            if de4dot_logger:
                de4dot_logger.log("dotnet_agent.de4dot", "completed", "de4dot cleanup completed", cleaned_path=cleaned_path)
            return cleaned_path

        if de4dot_logger:
            de4dot_logger.log("dotnet_agent.de4dot", "failed", "de4dot did not produce a cleaned file", exit_code=returncode)
        return file_path

    async def run_dnspy_decompile(
        self,
        file_path: str,
        output_dir: str,
        pipeline_logger: Optional[PipelineLogger] = None,
    ) -> bool:
        decompile_logger = pipeline_logger
        if pipeline_logger:
            _, decompile_logger = create_child_task_scope(
                pipeline_logger,
                stage_key="dotnet_agent.decompile",
                title="Decompile DotNet assembly",
            )

        file_path = self._abs_path(file_path)
        output_dir = self._abs_path(output_dir)

        print(f"[*] Decompile project (dnSpy-Ex) to: {output_dir}")
        if decompile_logger:
            decompile_logger.log(
                "dotnet_agent.decompile",
                "started",
                "Starting dnSpy decompile",
                output_dir=output_dir,
            )

        dnspy_exe = self.resolve_executable(
            self._tool_config("dnspy"),
            ["dnspyc.exe", "dnspyc", "dnSpy.Console.exe", "dnSpy.Console"],
        )
        if not dnspy_exe:
            configured = self._tool_config("dnspy")
            print("[-] dnSpy tool not found.")
            print(f"    - config.yaml tools.dnspy = {configured!r}")
            print("    - Put dnspyc.exe in PATH, or set tools.dnspy to an absolute path.")
            if decompile_logger:
                decompile_logger.log(
                    "dotnet_agent.decompile",
                    "failed",
                    "dnSpy tool not found",
                    configured=configured,
                )
            return False

        output_root_abs = self._abs_path(self.output_root)
        if not os.path.commonpath([output_root_abs, output_dir]) == output_root_abs:
            raise ValueError(f"Refusing to use output_dir outside output_root: {output_dir}")

        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)
        os.makedirs(output_dir, exist_ok=True)

        try:
            print(f"[*] Input file (absolute): {file_path}")
            print(f"[*] Output dir  (absolute): {output_dir}")
            cmd = [dnspy_exe, "-o", output_dir, file_path]
            returncode, stdout, stderr = await run_tracked_process(
                *cmd,
                pipeline_logger=decompile_logger,
            )
            if returncode != 0:
                print(f"[-] dnSpy-Ex exited with code {returncode}")
                if stdout:
                    print("[dnSpy stdout]")
                    print(stdout.decode("utf-8", errors="ignore"))
                if stderr:
                    print("[dnSpy stderr]")
                    print(stderr.decode("utf-8", errors="ignore"))
                if decompile_logger:
                    decompile_logger.log(
                        "dotnet_agent.decompile",
                        "failed",
                        "dnSpy decompile exited with non-zero status",
                        exit_code=returncode,
                    )
                return False
            if decompile_logger:
                decompile_logger.log(
                    "dotnet_agent.decompile",
                    "completed",
                    "dnSpy decompile completed",
                    output_dir=output_dir,
                )
            return True
        except Exception as e:
            print(f"[-] dnSpy-Ex failed: {e}")
            if decompile_logger:
                decompile_logger.log(
                    "dotnet_agent.decompile",
                    "failed",
                    "dnSpy decompile raised an exception",
                    error=str(e),
                )
            return False

    async def prepare(
        self,
        file_path: str,
        file_hash: str,
        pipeline_logger: Optional[PipelineLogger] = None,
        run_de4dot=None,
        run_dnspy_decompile=None,
        pick_interesting_cs_files=None,
    ) -> DotNetPreparation:
        source_directory = os.path.join(self.output_root, file_hash)
        run_de4dot = run_de4dot or self.run_de4dot
        run_dnspy_decompile = run_dnspy_decompile or self.run_dnspy_decompile
        pick_interesting_cs_files = pick_interesting_cs_files or self.pick_interesting_cs_files

        target_file = await run_de4dot(file_path, pipeline_logger=pipeline_logger)
        decompiled = await run_dnspy_decompile(target_file, source_directory, pipeline_logger=pipeline_logger)
        key_files = pick_interesting_cs_files(source_directory, limit=15)

        return DotNetPreparation(
            target_file=target_file,
            source_directory=source_directory,
            decompiled=bool(decompiled),
            cleaned_file=target_file if target_file != file_path else None,
            key_files=key_files,
        )
