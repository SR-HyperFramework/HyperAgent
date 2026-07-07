import asyncio
import hashlib
import os
import re
import shutil
import sys
from typing import Any, Dict, Optional

import yaml

from core.claude_code_runner import run_claude_code
from core.pipeline_logger import PipelineLogger
from core.result_models import AgentResult, ArtifactNode, Finding, RunContext
from core.tool_policy import resolve_candidate_path
from agents.python_bytecode_prep_agent import PythonBytecodePrepAgent


class ScriptAgent:
    def __init__(self, config_path: str = "config.yaml"):
        self.config = self._load_config(config_path)
        self.output_root = "script_output"
        self.repo_root = os.path.normpath(os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))

    def _prep_agent(self) -> PythonBytecodePrepAgent:
        return PythonBytecodePrepAgent(config=self.config, repo_root=self.repo_root)

    def _load_config(self, path: str) -> Dict[str, Any]:
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
            return {}
        except Exception as e:
            print(f"[ERROR] Error loading config: {e}")
            return {}

    def _tool_config(self, key: str) -> str | None:
        tools = (self.config or {}).get("tools") or {}
        value = tools.get(key)
        return str(value) if value else None

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

    def _ensure_output_dir(self, file_hash: str) -> str:
        output_dir = self._abs_path(os.path.join(self.output_root, file_hash))
        os.makedirs(output_dir, exist_ok=True)
        return output_dir

    async def _run_cmd(self, *cmd: str, cwd: str | None = None) -> tuple[int, str, str]:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        return (
            process.returncode,
            stdout.decode("utf-8", errors="replace") if isinstance(stdout, bytes) else str(stdout),
            stderr.decode("utf-8", errors="replace") if isinstance(stderr, bytes) else str(stderr),
        )

    def _resolve_tool(self, configured: str | None, fallbacks: list[str]) -> str | None:
        return resolve_candidate_path(configured, fallbacks, repo_root=self.repo_root)

    async def _extract_pyinstaller(
        self,
        file_path: str,
        output_dir: str,
        pipeline_logger: Optional[PipelineLogger] = None,
    ) -> tuple[str, list[str]]:
        return await self._prep_agent().extract_pyinstaller(file_path, output_dir, pipeline_logger=pipeline_logger)

    async def _disassemble_with_pycdas(
        self,
        target_dir: str,
        pipeline_logger: Optional[PipelineLogger] = None,
    ) -> list[str]:
        return await self._prep_agent().disassemble_with_pycdas(target_dir, pipeline_logger=pipeline_logger)

    def _pick_interesting_files(self, base_dir: str, suffixes: tuple[str, ...], limit: int = 20) -> list[str]:
        return self._prep_agent().pick_interesting_files(base_dir, suffixes, limit=limit)

    async def _prepare_extraction(
        self,
        file_path: str,
        output_dir: str,
        pipeline_logger: Optional[PipelineLogger] = None,
    ):
        return await self._prep_agent().prepare(
            file_path,
            output_dir,
            pipeline_logger=pipeline_logger,
            extract_pyinstaller=self._extract_pyinstaller,
            disassemble_with_pycdas=self._disassemble_with_pycdas,
        )

    @staticmethod
    def filter_goose_report(raw_log: str) -> str:
        start_marker = "**Start of Analysis**"
        end_marker = "**End of Analysis**"

        start_idx = raw_log.find(start_marker)
        end_idx = raw_log.find(end_marker)

        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            content = raw_log[start_idx : end_idx + len(end_marker)]
        elif start_idx != -1:
            content = raw_log[start_idx:]
        else:
            content = raw_log

        content = re.sub(r"───.*?\n", "", content)
        content = re.sub(r"-\d+: Could not interpret tool use parameters.*?\n", "", content)
        content = re.sub(r"\n\s*\n", "\n\n", content).strip()
        return content

    @staticmethod
    def _get_file_hash(file_path: str) -> str:
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def _build_result(
        self,
        *,
        file_path: str,
        file_hash: str,
        extract_dir: str,
        pyasm_files: list[str],
        report: str,
        run_context: RunContext | None,
    ) -> dict[str, Any] | AgentResult:
        legacy_payload = {
            "file_name": os.path.basename(file_path),
            "file_hash": file_hash,
            "extract_dir": extract_dir,
            "pyasm_files": [self._to_workspace_rel_posix(path) for path in pyasm_files],
            "ai_analysis_report": report,
        }
        if run_context is None:
            return legacy_payload

        input_artifact = ArtifactNode(
            path=self._abs_path(file_path),
            sha256=file_hash,
            depth=run_context.depth,
            kind="script_input",
        )
        artifacts = [input_artifact]
        if run_context.artifact_registry:
            run_context.artifact_registry.add(input_artifact)

        if os.path.isdir(extract_dir):
            extract_artifact = ArtifactNode(
                path=self._abs_path(extract_dir),
                parent_id=input_artifact.id,
                depth=run_context.depth + 1,
                kind="script_extract_directory",
                metadata={"display_path": extract_dir},
            )
            artifacts.append(extract_artifact)
            if run_context.artifact_registry:
                run_context.artifact_registry.add(extract_artifact)
            parent_id = extract_artifact.id
        else:
            parent_id = input_artifact.id

        for pyasm_path in pyasm_files:
            pyasm_artifact = ArtifactNode(
                path=self._abs_path(pyasm_path),
                parent_id=parent_id,
                depth=run_context.depth + 1,
                kind="script_pyasm",
                metadata={"display_path": self._to_workspace_rel_posix(pyasm_path)},
            )
            artifacts.append(pyasm_artifact)
            if run_context.artifact_registry:
                run_context.artifact_registry.add(pyasm_artifact)

        finding = Finding(
            artifact_id=input_artifact.id,
            category="analysis_report",
            summary="Script analysis report generated",
            evidence=report,
            confidence=1.0,
        )
        if run_context.finding_store:
            run_context.finding_store.add(finding)

        return AgentResult(
            artifact_id=input_artifact.id,
            legacy_payload=legacy_payload,
            artifacts=artifacts,
            findings=[finding],
        )

    async def run_goose_analysis(
        self,
        file_path: str,
        extract_dir: str,
        pipeline_logger: Optional[PipelineLogger] = None,
    ) -> str:
        abs_target = self._abs_path(file_path)
        workspace_target = self._to_workspace_rel_posix(file_path)

        pyasm_files = self._pick_interesting_files(extract_dir, (".pyasm",), limit=20)
        extracted_files = self._pick_interesting_files(extract_dir, (".py", ".pyc", ".pyo", ".pyasm"), limit=25)
        workspace_extract_dir = self._to_workspace_rel_posix(extract_dir)

        files_block = "\n".join(f"- {path}" for path in pyasm_files) if pyasm_files else "- (no .pyasm files generated)"
        extracted_block = "\n".join(f"- {path}" for path in extracted_files) if extracted_files else "- (no extracted files detected)"

        if pipeline_logger:
            pipeline_logger.log(
                "script_agent.claude",
                "started",
                "Starting Claude Code script analysis",
                extract_dir=extract_dir,
            )

        instruction = (
            "You are a Senior Python malware analyst. "
            f"Target file path: {abs_target}. "
            f"Workspace-relative target path: {workspace_target}. "
            f"Use the extracted contents under: {workspace_extract_dir}.\n"
            "Start with the generated .pyasm files listed below because they contain pycdas disassembly output.\n"
            f"Primary .pyasm files to inspect first:\n{files_block}\n\n"
            "Other extracted files/directories worth checking:\n"
            f"{extracted_block}\n\n"
            "Tasks:\n"
            "1) Reconstruct the likely entry point and main execution flow from the extraction/disassembly output.\n"
            "2) Call out suspicious strings, imports, dynamic execution, filesystem/network/process behavior, persistence, and obfuscation.\n"
            "3) Cross-check findings between .pyasm output and extracted source/bytecode files.\n"
            "4) NEVER execute the file.\n"
            "If you cannot read the target or extracted files, write exactly: Error: Cannot access target file.\n"
            "Write a report starting with **Start of Analysis** and ending with **End of Analysis**."
        )
        return await run_claude_code(
            instruction,
            config=self.config,
            pipeline_logger=pipeline_logger,
        )

    async def analyze(
        self,
        file_path: str,
        pipeline_logger: Optional[PipelineLogger] = None,
        run_context: RunContext | None = None,
    ) -> Dict[str, Any] | AgentResult:
        if not os.path.exists(file_path):
            if pipeline_logger:
                pipeline_logger.log("script_agent", "failed", "File does not exist", file_path=file_path)
            return {"error": "File does not exist"}
        if not os.access(file_path, os.R_OK):
            if pipeline_logger:
                pipeline_logger.log("script_agent", "failed", "File is not readable", file_path=file_path)
            return {"error": "File is not readable"}

        abs_file_path = self._abs_path(file_path)
        file_hash = self._get_file_hash(abs_file_path)
        if pipeline_logger:
            pipeline_logger.log(
                "script_agent",
                "started",
                "Script analysis started",
                file_name=os.path.basename(abs_file_path),
                file_hash=file_hash,
            )
        output_dir = self._ensure_output_dir(file_hash)
        prep = await self._prepare_extraction(
            abs_file_path,
            output_dir,
            pipeline_logger=pipeline_logger,
        )

        raw_report = await self.run_goose_analysis(
            abs_file_path,
            prep.extract_dir,
            pipeline_logger=pipeline_logger,
        )
        report = self.filter_goose_report(raw_report)
        if pipeline_logger:
            pipeline_logger.log(
                "script_agent",
                "completed",
                "Script analysis complete",
                file_hash=file_hash,
                pyasm_count=len(prep.pyasm_files),
            )
        return self._build_result(
            file_path=abs_file_path,
            file_hash=file_hash,
            extract_dir=prep.extract_dir,
            pyasm_files=prep.pyasm_files,
            report=report,
            run_context=run_context,
        )
