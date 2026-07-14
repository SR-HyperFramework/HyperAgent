import asyncio
import hashlib
import os
import re
import shutil
from typing import Any, Dict, Optional

import yaml

from agents.dotnet_decompiler_agent import DotNetDecompilerAgent
from core.claude_code_runner import run_claude_code
from core.pipeline_logger import PipelineLogger
from core.result_models import AgentResult, ArtifactNode, Finding, RunContext
from core.task_runtime import bind_process_scope, create_child_task_scope, run_tracked_process
from core.tool_policy import resolve_candidate_path, resolve_tool_path


class DotNetAgent:
    def __init__(self, config_path: str = "config.yaml"):
        self.config = self._load_config(config_path)
        self.output_root = "dotnet_output"
        self.repo_root = os.path.normpath(os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))

    def _prep_agent(self) -> DotNetDecompilerAgent:
        return DotNetDecompilerAgent(
            config=self.config,
            output_root=self.output_root,
            repo_root=self.repo_root,
            resolve_executable=self._resolve_executable,
        )

    def _tool_config(self, key: str) -> str | None:
        tools = (self.config or {}).get("tools") or {}
        value = tools.get(key)
        return str(value) if value else None

    def _resolve_executable(self, configured: str | None, fallbacks: list[str]) -> str | None:
        return resolve_candidate_path(configured, fallbacks, repo_root=self.repo_root)

    def _abs_path(self, path: str) -> str:
        return os.path.normpath(os.path.abspath(os.path.expandvars(os.path.expanduser(path))))

    def _load_config(self, path: str) -> Dict[str, Any]:
        try:
            if os.path.exists(path):
                with open(path, "r") as f:
                    return yaml.safe_load(f)
            return {}
        except Exception as e:
            print(f"[ERROR] Error loading config: {e}")
            return {}

    def _get_file_hash(self, file_path: str) -> str:
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def _to_workspace_rel_posix(self, path: str) -> str:
        repo_root_abs = self._abs_path(self.repo_root)
        path_abs = self._abs_path(path)
        try:
            rel = os.path.relpath(path_abs, start=repo_root_abs)
        except Exception:
            rel = path_abs
        return rel.replace("\\", "/")

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

    def _pick_interesting_cs_files(self, base_dir: str, limit: int = 15) -> list[str]:
        return self._prep_agent().pick_interesting_cs_files(base_dir, limit=limit)

    def _build_result(
        self,
        *,
        file_path: str,
        file_hash: str,
        source_directory: str,
        cleaned_file: str | None,
        report: str,
        run_context: RunContext | None,
    ) -> dict[str, Any] | AgentResult:
        legacy_payload = {
            "file_name": os.path.basename(file_path),
            "file_hash": file_hash,
            "source_directory": source_directory,
            "cleaned_file": cleaned_file,
            "ai_analysis_report": report,
        }
        if run_context is None:
            return legacy_payload

        input_artifact = ArtifactNode(
            path=self._abs_path(file_path),
            sha256=file_hash,
            depth=run_context.depth,
            kind="dotnet_input",
        )
        source_artifact = ArtifactNode(
            path=self._abs_path(source_directory),
            parent_id=input_artifact.id,
            depth=run_context.depth + 1,
            kind="dotnet_source_directory",
            metadata={"display_path": source_directory},
        )
        if run_context.artifact_registry:
            run_context.artifact_registry.add(input_artifact)
            run_context.artifact_registry.add(source_artifact)

        finding = Finding(
            artifact_id=input_artifact.id,
            category="analysis_report",
            summary="DotNet analysis report generated",
            evidence=report,
            confidence=1.0,
        )
        if run_context.finding_store:
            run_context.finding_store.add(finding)

        return AgentResult(
            artifact_id=input_artifact.id,
            legacy_payload=legacy_payload,
            artifacts=[input_artifact, source_artifact],
            findings=[finding],
            metadata={"source_directory_artifact_id": source_artifact.id},
        )

    async def run_de4dot(
        self,
        file_path: str,
        pipeline_logger: Optional[PipelineLogger] = None,
    ) -> str:
        de4dot = resolve_tool_path(self.config, "de4dot", ["de4dot.exe", "de4dot"], repo_root=self.repo_root)
        if not de4dot:
            if pipeline_logger:
                pipeline_logger.log("dotnet_agent.de4dot", "skipped", "de4dot tool not found")
            return file_path

        file_path = self._abs_path(file_path)
        if pipeline_logger:
            pipeline_logger.log("dotnet_agent.de4dot", "started", "Starting de4dot cleanup")

        returncode, _, _ = await run_tracked_process(
            de4dot,
            file_path,
            pipeline_logger=pipeline_logger,
        )

        root, ext = os.path.splitext(file_path)
        cleaned_path = f"{root}-cleaned{ext}"
        if returncode == 0 and os.path.exists(cleaned_path):
            if pipeline_logger:
                pipeline_logger.log("dotnet_agent.de4dot", "completed", "de4dot cleanup completed", cleaned_path=cleaned_path)
            return cleaned_path

        if pipeline_logger:
            pipeline_logger.log("dotnet_agent.de4dot", "failed", "de4dot did not produce a cleaned file", exit_code=returncode)
        return file_path

    async def run_dnspy_decompile(
        self,
        file_path: str,
        output_dir: str,
        pipeline_logger: Optional[PipelineLogger] = None,
    ):
        file_path = self._abs_path(file_path)
        output_dir = self._abs_path(output_dir)

        print(f"[*] Decompile project (dnSpy-Ex) to: {output_dir}")
        if pipeline_logger:
            pipeline_logger.log(
                "dotnet_agent.decompile",
                "started",
                "Starting dnSpy decompile",
                output_dir=output_dir,
            )

        dnspy_exe = self._resolve_executable(
            self._tool_config("dnspy"),
            ["dnspyc.exe", "dnspyc", "dnSpy.Console.exe", "dnSpy.Console"],
        )
        if not dnspy_exe:
            configured = self._tool_config("dnspy")
            print("[-] dnSpy tool not found.")
            print(f"    - config.yaml tools.dnspy = {configured!r}")
            print("    - Put dnspyc.exe in PATH, or set tools.dnspy to an absolute path.")
            if pipeline_logger:
                pipeline_logger.log(
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
                pipeline_logger=pipeline_logger,
            )
            if returncode != 0:
                print(f"[-] dnSpy-Ex exited with code {returncode}")
                if stdout:
                    print("[dnSpy stdout]")
                    print(stdout.decode("utf-8", errors="ignore"))
                if stderr:
                    print("[dnSpy stderr]")
                    print(stderr.decode("utf-8", errors="ignore"))
                if pipeline_logger:
                    pipeline_logger.log(
                        "dotnet_agent.decompile",
                        "failed",
                        "dnSpy decompile exited with non-zero status",
                        exit_code=returncode,
                    )
                return False
            if pipeline_logger:
                pipeline_logger.log(
                    "dotnet_agent.decompile",
                    "completed",
                    "dnSpy decompile completed",
                    output_dir=output_dir,
                )
            return True
        except Exception as e:
            print(f"[-] dnSpy-Ex failed: {e}")
            if pipeline_logger:
                pipeline_logger.log(
                    "dotnet_agent.decompile",
                    "failed",
                    "dnSpy decompile raised an exception",
                    error=str(e),
                )
            return False

    async def _prepare_source_directory(
        self,
        file_path: str,
        file_hash: str,
        pipeline_logger: Optional[PipelineLogger] = None,
    ):
        return await self._prep_agent().prepare(
            file_path,
            file_hash,
            pipeline_logger=pipeline_logger,
            run_de4dot=self.run_de4dot,
            run_dnspy_decompile=self.run_dnspy_decompile,
            pick_interesting_cs_files=self._pick_interesting_cs_files,
        )

    async def run_goose_analysis(
        self,
        specific_out_dir: str,
        pipeline_logger: Optional[PipelineLogger] = None,
    ) -> str:
        print("[*] Starting Claude Code C# analysis...")
        claude_logger = pipeline_logger
        if pipeline_logger:
            _, claude_logger = create_child_task_scope(
                pipeline_logger,
                stage_key="dotnet_agent.claude",
                title="Run DotNet Claude analysis",
            )
            claude_logger.log(
                "dotnet_agent.claude",
                "started",
                "Starting Claude Code source analysis",
            )

        workspace_dir = self._to_workspace_rel_posix(specific_out_dir)
        key_files = self._pick_interesting_cs_files(specific_out_dir, limit=15)

        if not key_files:
            print("[WARN] No .cs files found for analysis (directory missing or empty).")

        files_block = "\n".join(key_files) if key_files else "- (no .cs files detected)"

        instruction = (
            "Role: Senior .NET Malware Researcher.\n"
            "Workspace Root: repository root (current working directory).\n"
            f"Examine the decompiled C# source code under: {workspace_dir}\n\n"
            "Files to read first:\n"
            f"{files_block}\n\n"
            "Constraints:\n"
            "1. Read priority files first, using EXACT repo-relative paths shown above (no drive letters, no absolute paths).\n"
            "2. NEVER try to execute any code.\n"
            "3. If file access fails, reply exactly: 'Error: File cannot accessed.'.\n"
            "4. Format: Start with '**Start of Analysis**', end with '**End of Analysis**'.\n\n"
            "Analysis Requirements:\n"
            "- Identify the Entry Point and main execution flow.\n"
            "- Identify sensitive strings, API imports (P/Invoke), or network activities.\n"
            "- Identify Costura/Fody loaders, packers, obfuscation, and malicious logic.\n"
            "- If embedded or unpacked next-stage payloads are visible, list their paths and explain how to analyze them next.\n"
            "- Report Structure: [Entry Point] | [Flow] | [IOCs/APIs] | [Malicious/Obfuscation] | [File Summary] | [Conclusion]"
        )

        try:
            result = await run_claude_code(
                instruction,
                config=self.config,
                pipeline_logger=claude_logger,
            )
            if claude_logger:
                claude_logger.log(
                    "dotnet_agent.claude",
                    "completed",
                    "Claude Code source analysis completed",
                    source_directory=specific_out_dir,
                )
            return result
        except Exception as exc:
            if claude_logger:
                claude_logger.log(
                    "dotnet_agent.claude",
                    "failed",
                    "Claude Code source analysis failed",
                    source_directory=specific_out_dir,
                    error=str(exc),
                )
            raise

    async def analyze(
        self,
        file_path: str,
        pipeline_logger: Optional[PipelineLogger] = None,
        run_context: RunContext | None = None,
    ) -> Dict[str, Any] | AgentResult:
        file_hash = self._get_file_hash(file_path)
        if pipeline_logger:
            pipeline_logger.log(
                "dotnet_agent",
                "started",
                "DotNet analysis started",
                file_name=os.path.basename(file_path),
                file_hash=file_hash,
            )

        with bind_process_scope(pipeline_logger=run_context.pipeline_logger if run_context else pipeline_logger):
            prep = await self._prepare_source_directory(
                file_path,
                file_hash,
                pipeline_logger=pipeline_logger,
            )
            if not prep.decompiled:
                return {"error": "Decompilation failed"}

            goose_report_raw = await self.run_goose_analysis(
                prep.source_directory,
                pipeline_logger=pipeline_logger,
            )
        report = self.filter_goose_report(goose_report_raw)

        print("\n[INFO] Analysis complete.")
        return self._build_result(
            file_path=file_path,
            file_hash=file_hash,
            source_directory=prep.source_directory,
            cleaned_file=prep.cleaned_file,
            report=report,
            run_context=run_context,
        )
