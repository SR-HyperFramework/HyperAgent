import os
import yaml
from typing import Dict, Any, Optional
import hashlib

from core.claude_code_runner import run_claude_code
from core.pipeline_logger import PipelineLogger


class NativeAgent:
    def __init__(self, config_path: str = "config.yaml"):
        self.config = self._load_config(config_path)
        # IDA file opening is handled inside Claude via /ida-pro:idapython.
        # Keep config loading intact, but skip the legacy host-side uv run idalib-mcp flow.

    def _load_config(self, path: str) -> Dict[str, Any]:
        """Load cấu hình từ file yaml."""
        try:
            if os.path.exists(path):
                with open(path, "r") as f:
                    return yaml.safe_load(f)
            return {}
        except Exception as e:
            print(f"[ERROR] Error loading config: {e}")
            return {}

    def _get_file_hash(self, file_path: str) -> str:
        """Tính SHA256 của file để làm ID cho endpoint."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    async def run_goose_analysis(
        self,
        file_path: str,
        pipeline_logger: Optional[PipelineLogger] = None,
    ) -> str:
        """Run Claude Code directly; IDA file opening now happens via /ida-pro:idapython inside the analysis workflow."""
        try:
            print("[INFO] Running Claude Code AI agent...")
            if pipeline_logger:
                pipeline_logger.log(
                    "native_agent.claude",
                    "started",
                    "Running Claude Code AI agent",
                )

            abs_target = os.path.abspath(file_path)
            instruction = (
                f"Target file path: {abs_target}. "
                "Use hyperagent-malware-analysis skill and start analyze"
            )

            return await run_claude_code(
                instruction,
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

    # @staticmethod
    # def filter_goose_report(raw_log: str) -> str:
    #     # 1. Cắt đoạn từ **Start of Analysis** đến **End of Analysis**
    #     start_marker = "**Start of Analysis**"
    #     end_marker = "**End of Analysis**"

    #     start_idx = raw_log.find(start_marker)
    #     end_idx = raw_log.find(end_marker)

    #     if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
    #         content = raw_log[start_idx : end_idx + len(end_marker)]
    #     elif start_idx != -1:
    #         content = raw_log[start_idx:]
    #     else:
    #         content = raw_log

    #     # 2. Regex để xóa các log gọi tool MCP (các thanh kẻ ngang ───)
    #     # Loại bỏ các dòng dạng: ─── tên_tool | ida ─────────────────────────-
    #     content = re.sub(r"───.*?\n", "", content)

    #     # Loại bỏ các thông báo lỗi tham số tool (nếu có)
    #     content = re.sub(r"-\d+: Could not interpret tool use parameters.*?\n", "", content)

    #     # Loại bỏ các dòng trống dư thừa
    #     content = re.sub(r"\n\s*\n", "\n\n", content).strip()

    #     return content

    async def analyze(
        self,
        file_path: str,
        pipeline_logger: Optional[PipelineLogger] = None,
    ) -> Dict[str, Any]:
        """Workflow chính: Tự động hóa toàn bộ quá trình."""
        if not os.path.exists(file_path):
            if pipeline_logger:
                pipeline_logger.log("native_agent", "failed", "File does not exist", file_path=file_path)
            return {"error": "File does not exist"}

        file_hash = self._get_file_hash(file_path)
        if pipeline_logger:
            pipeline_logger.log(
                "native_agent",
                "started",
                "Native analysis started",
                file_name=os.path.basename(file_path),
                file_hash=file_hash,
            )

        goose_report_raw = await self.run_goose_analysis(file_path, pipeline_logger=pipeline_logger)
        # clean_rp = self.filter_goose_report(goose_report_raw)
        
        # capa_res, floss_res = await asyncio.gather(capa_task, floss_task)

        # Bước 3: Tổng hợp kết quả (Context Logger)
        f_context = {
            "file_name": os.path.basename(file_path),
            "file_hash": file_hash,
            "ai_analysis_report": goose_report_raw,
        }

        print("\n[INFO] Analysis complete.")
        return f_context