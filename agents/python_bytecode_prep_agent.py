from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from typing import Any, Optional

from core.pipeline_logger import PipelineLogger
from core.task_runtime import create_child_task_scope, run_tracked_process
from core.tool_policy import resolve_candidate_path, resolve_tool_path


@dataclass
class PythonPreparation:
    extract_dir: str
    pyasm_files: list[str]
    priority_pyasm_files: list[str]
    extracted_candidates: list[str]


class PythonBytecodePrepAgent:
    def __init__(self, config: dict[str, Any], repo_root: str):
        self.config = config
        self.repo_root = repo_root

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

    async def _run_cmd(
        self,
        *cmd: str,
        cwd: str | None = None,
        pipeline_logger: Optional[PipelineLogger] = None,
    ) -> tuple[int, str, str]:
        returncode, stdout, stderr = await run_tracked_process(*cmd, cwd=cwd, pipeline_logger=pipeline_logger)
        return (
            returncode,
            stdout.decode("utf-8", errors="replace") if isinstance(stdout, bytes) else str(stdout),
            stderr.decode("utf-8", errors="replace") if isinstance(stderr, bytes) else str(stderr),
        )

    def _resolve_tool(self, configured: str | None, fallbacks: list[str]) -> str | None:
        return resolve_candidate_path(configured, fallbacks, repo_root=self.repo_root)

    async def extract_pyinstaller(
        self,
        file_path: str,
        output_dir: str,
        pipeline_logger: Optional[PipelineLogger] = None,
    ) -> tuple[str, list[str]]:
        extract_logger = pipeline_logger
        if pipeline_logger:
            _, extract_logger = create_child_task_scope(
                pipeline_logger,
                stage_key="script_agent.extract",
                title="Extract PyInstaller bundle",
            )

        extractor = resolve_tool_path(
            self.config,
            "pyinstxtractor",
            ["pyinstxtractor.py", "pyinstxtractor"],
            repo_root=self.repo_root,
        )
        if not extractor:
            if extract_logger:
                extract_logger.log(
                    "script_agent.extract",
                    "failed",
                    "PyInstaller extractor not found",
                )
            return file_path, []

        if extract_logger:
            extract_logger.log(
                "script_agent.extract",
                "started",
                "Starting PyInstaller extraction",
                output_dir=output_dir,
            )
        before_dirs = {entry for entry in os.listdir(output_dir) if os.path.isdir(os.path.join(output_dir, entry))}
        cmd = [sys.executable, extractor, file_path]
        code, _, stderr = await self._run_cmd(*cmd, cwd=output_dir, pipeline_logger=extract_logger)
        if code != 0:
            print(f"[WARN] pyinstxtractor failed: {stderr.strip()}")
            if extract_logger:
                extract_logger.log(
                    "script_agent.extract",
                    "failed",
                    "PyInstaller extraction failed",
                    stderr=stderr[:500],
                )
            return file_path, []

        after_dirs = [
            os.path.join(output_dir, entry)
            for entry in os.listdir(output_dir)
            if os.path.isdir(os.path.join(output_dir, entry)) and entry not in before_dirs
        ]
        after_dirs.sort(key=lambda p: len(p), reverse=True)
        extract_dir = after_dirs[0] if after_dirs else file_path

        extracted_files: list[str] = []
        if os.path.isdir(extract_dir):
            for root, _, files in os.walk(extract_dir):
                for name in files:
                    extracted_files.append(os.path.join(root, name))

        if extract_logger:
            extract_logger.log(
                "script_agent.extract",
                "completed",
                "PyInstaller extraction completed",
                extract_dir=extract_dir,
                extracted_file_count=len(extracted_files),
            )
        return extract_dir, extracted_files

    async def disassemble_with_pycdas(
        self,
        target_dir: str,
        pipeline_logger: Optional[PipelineLogger] = None,
    ) -> list[str]:
        disassemble_logger = pipeline_logger
        if pipeline_logger:
            _, disassemble_logger = create_child_task_scope(
                pipeline_logger,
                stage_key="script_agent.disassemble",
                title="Disassemble Python bytecode",
            )

        pycdas = resolve_tool_path(self.config, "pycdas", ["pycdas", "pycdas.exe"], repo_root=self.repo_root)
        if not pycdas or not os.path.isdir(target_dir):
            if disassemble_logger:
                disassemble_logger.log(
                    "script_agent.disassemble",
                    "failed",
                    "pycdas unavailable or target directory missing",
                    target_dir=target_dir,
                )
            return []

        if disassemble_logger:
            disassemble_logger.log(
                "script_agent.disassemble",
                "started",
                "Starting pycdas disassembly",
                target_dir=target_dir,
            )

        pyc_files: list[str] = []
        for root, _, files in os.walk(target_dir):
            for name in files:
                if name.lower().endswith((".pyc", ".pyo")):
                    pyc_files.append(os.path.join(root, name))

        created_pyasm: list[str] = []
        for pyc_file in pyc_files:
            pyasm_path = f"{pyc_file}.pyasm"
            code, stdout, stderr = await self._run_cmd(pycdas, pyc_file, pipeline_logger=disassemble_logger)
            if code != 0:
                print(f"[WARN] pycdas failed for {pyc_file}: {(stderr or stdout).strip()}")
                continue
            with open(pyasm_path, "w", encoding="utf-8", errors="replace") as f:
                f.write(stdout)
            created_pyasm.append(pyasm_path)

        if disassemble_logger:
            disassemble_logger.log(
                "script_agent.disassemble",
                "completed",
                "pycdas disassembly completed",
                pyasm_count=len(created_pyasm),
            )
        return created_pyasm

    def pick_interesting_files(self, base_dir: str, suffixes: tuple[str, ...], limit: int = 20) -> list[str]:
        if not os.path.isdir(base_dir):
            return []

        interesting_names = {"__main__.py", "main.py", "app.py", "run.py", "loader.py", "bootstrap.py"}
        keywords = ("main", "entry", "loader", "bootstrap", "decrypt", "config", "socket", "http", "request", "exec")
        hits: list[str] = []
        others: list[str] = []

        for root, _, files in os.walk(base_dir):
            for name in files:
                low = name.lower()
                if not low.endswith(suffixes):
                    continue
                rel = self._to_workspace_rel_posix(os.path.join(root, name))
                if low in interesting_names or any(keyword in low for keyword in keywords):
                    hits.append(rel)
                else:
                    others.append(rel)

        result = hits[:limit]
        if len(result) < limit:
            result.extend(others[: limit - len(result)])
        return result

    async def prepare(
        self,
        file_path: str,
        output_dir: str,
        pipeline_logger: Optional[PipelineLogger] = None,
        extract_pyinstaller=None,
        disassemble_with_pycdas=None,
    ) -> PythonPreparation:
        abs_file_path = self._abs_path(file_path)
        extract_pyinstaller = extract_pyinstaller or self.extract_pyinstaller
        disassemble_with_pycdas = disassemble_with_pycdas or self.disassemble_with_pycdas

        extract_dir, _ = await extract_pyinstaller(
            abs_file_path,
            output_dir,
            pipeline_logger=pipeline_logger,
        )
        if os.path.isfile(extract_dir):
            extract_dir = os.path.dirname(abs_file_path)

        pyasm_files = await disassemble_with_pycdas(
            extract_dir,
            pipeline_logger=pipeline_logger,
        )
        if not pyasm_files and os.path.isdir(extract_dir):
            for root, _, files in os.walk(extract_dir):
                for name in files:
                    if name.lower().endswith(".pyasm"):
                        pyasm_files.append(os.path.join(root, name))

        return PythonPreparation(
            extract_dir=extract_dir,
            pyasm_files=pyasm_files,
            priority_pyasm_files=self.pick_interesting_files(extract_dir, (".pyasm",), limit=20),
            extracted_candidates=self.pick_interesting_files(extract_dir, (".py", ".pyc", ".pyo", ".pyasm"), limit=25),
        )
