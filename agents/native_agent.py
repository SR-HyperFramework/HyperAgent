import hashlib
import os
import re
from typing import Any, Dict, Optional

import yaml

from agents.native_disassembly_prep_agent import NativeDisassemblyPrepAgent
from core.claude_code_runner import run_claude_code
from core.pipeline_logger import PipelineLogger
from core.result_models import AgentResult, ArtifactNode, Finding, RunContext
from core.tool_policy import get_ida_server_command


class NativeAgent:
    def __init__(self, config_path: str = "config.yaml"):
        self.config = self._load_config(config_path)
        self.ida_server_command = get_ida_server_command(self.config)
        self.prep_agent = NativeDisassemblyPrepAgent()

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

    def _build_result(
        self,
        *,
        file_path: str,
        file_hash: str,
        report: str,
        run_context: RunContext | None,
    ) -> dict[str, Any] | AgentResult:
        legacy_payload = {
            "file_name": os.path.basename(file_path),
            "file_hash": file_hash,
            "ai_analysis_report": report,
        }
        if run_context is None:
            return legacy_payload

        artifact = ArtifactNode(
            path=os.path.abspath(file_path),
            sha256=file_hash,
            depth=run_context.depth,
            kind="native_input",
        )
        if run_context.artifact_registry:
            run_context.artifact_registry.add(artifact)

        finding = Finding(
            artifact_id=artifact.id,
            category="analysis_report",
            summary="Native analysis report generated",
            evidence=report,
            confidence=1.0,
        )
        if run_context.finding_store:
            run_context.finding_store.add(finding)

        return AgentResult(
            artifact_id=artifact.id,
            legacy_payload=legacy_payload,
            artifacts=[artifact],
            findings=[finding],
        )

    async def _prepare_native_target(self, file_path: str):
        return self.prep_agent.prepare(file_path)

    async def run_goose_analysis(
        self,
        file_path: str,
        pipeline_logger: Optional[PipelineLogger] = None,
    ) -> str:
        try:
            print("[INFO] Running Claude Code AI agent...")
            if pipeline_logger:
                pipeline_logger.log(
                    "native_agent.claude",
                    "started",
                    "Running Claude Code AI agent",
                )

            prep = await self._prepare_native_target(file_path)

            return await run_claude_code(
                prep.instruction,
                config=self.config,
                pipeline_logger=pipeline_logger,
            )
        except Exception as e:
            if pipeline_logger:
                pipeline_logger.log(
                    "native_agent.claude",
                    "failed",
                    "Claude Code execution error",
                    error=str(e),
                )
            return f"Claude Code execution error: {str(e)}"
        finally:
            if pipeline_logger:
                pipeline_logger.log(
                    "native_agent.cleanup",
                    "completed",
                    "Skipped legacy IDA MCP startup and cleanup",
                )
            print("[INFO] Skipped legacy IDA MCP server startup.")

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

    async def analyze(
        self,
        file_path: str,
        pipeline_logger: Optional[PipelineLogger] = None,
        run_context: RunContext | None = None,
    ) -> Dict[str, Any] | AgentResult:
        if not os.path.exists(file_path):
            if pipeline_logger:
                pipeline_logger.log("native_agent", "failed", "File does not exist", file_path=file_path)
            return {"error": "File does not exist"}

        prep = await self._prepare_native_target(file_path)
        file_hash = prep.file_hash
        if pipeline_logger:
            pipeline_logger.log(
                "native_agent",
                "started",
                "Native analysis started",
                file_name=os.path.basename(file_path),
                file_hash=file_hash,
            )

        goose_report_raw = await self.run_goose_analysis(file_path, pipeline_logger=pipeline_logger)
        report = self.filter_goose_report(goose_report_raw)

        print("\n[INFO] Analysis complete.")
        return self._build_result(
            file_path=file_path,
            file_hash=file_hash,
            report=report,
            run_context=run_context,
        )
