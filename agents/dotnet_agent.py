import asyncio
import os
import hashlib
import shutil
import yaml
import sys
import re
from typing import Dict, Any, Optional

from core.claude_code_runner import run_claude_code
from core.pipeline_logger import PipelineLogger


class DotNetAgent:
    def __init__(self, config_path: str = "config.yaml"):
        self.config = self._load_config(config_path)       
        # Đường dẫn tới các công cụ (Nên để trong config.yaml)
        # self.de4dot_path = r"E:\Program\de4dot\de4dot.exe" 
        # self.dnspy_path = r"E:\Program\dnSpyEx\dnSpy.Console.exe"
        self.output_root = "dotnet_output"
        self.repo_root = os.path.normpath(os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))

    def _tool_config(self, key: str) -> str | None:
        tools = (self.config or {}).get("tools") or {}
        value = tools.get(key)
        return str(value) if value else None

    def _resolve_executable(self, configured: str | None, fallbacks: list[str]) -> str | None:
        """Resolve an executable path from config, PATH, or repo-relative locations."""

        def _candidates() -> list[str]:
            out: list[str] = []
            if configured:
                out.append(configured)
            out.extend(fallbacks)
            return out

        for candidate in _candidates():
            expanded = os.path.expandvars(os.path.expanduser(str(candidate)))

            # Absolute/relative filesystem path
            path_like = expanded
            if os.path.isabs(path_like):
                if os.path.isfile(path_like):
                    return os.path.normpath(path_like)
            else:
                # PATH lookup
                which = shutil.which(path_like)
                if which:
                    return os.path.normpath(which)

                # repo-root relative lookup (common for bundled tools)
                repo_rel = os.path.normpath(os.path.join(self.repo_root, path_like))
                if os.path.isfile(repo_rel):
                    return repo_rel

        return None

    def _abs_path(self, path: str) -> str:
        """Return a normalized absolute path for consistent tool invocation/logging."""
        return os.path.normpath(os.path.abspath(os.path.expandvars(os.path.expanduser(path))))
    
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
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def _to_workspace_rel_posix(self, path: str) -> str:
        """Convert an absolute path to a workspace-relative POSIX-style path for Goose tools."""
        repo_root_abs = self._abs_path(self.repo_root)
        path_abs = self._abs_path(path)
        try:
            rel = os.path.relpath(path_abs, start=repo_root_abs)
        except Exception:
            rel = path_abs
        return rel.replace("\\", "/")

    def _pick_interesting_cs_files(self, base_dir: str, limit: int = 15) -> list[str]:
        """Return up to `limit` interesting .cs files (workspace-relative, POSIX path)."""
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

        # Prefer "hits" but fall back to any .cs files
        result = hits[:limit]
        if len(result) < limit:
            remaining = limit - len(result)
            result.extend(others[:remaining])
        return result

    # async def run_de4dot(self, file_path: str) -> str:
    #     """Sử dụng de4dot để làm sạch mã nguồn .NET."""
    #     print(f"[*] Đang thực hiện De-obfuscate (de4dot): {os.path.basename(file_path)}")
    #     try:
    #         # de4dot sẽ tạo ra file mới có đuôi -cleaned.exe
    #         proc = await asyncio.create_subprocess_exec(
    #             self.de4dot_path, file_path,
    #             stdout=asyncio.subprocess.PIPE,
    #             stderr=asyncio.subprocess.PIPE
    #         )
    #         await proc.communicate()
            
    #         cleaned_path = file_path.replace(".exe", "-cleaned.exe")
    #         if os.path.exists(cleaned_path):
    #             return cleaned_path
    #         return file_path
    #     except Exception as e:
    #         print(f"[-] de4dot failed: {e}")
    #         return file_path

    async def run_dnspy_decompile(
        self,
        file_path: str,
        output_dir: str,
        pipeline_logger: Optional[PipelineLogger] = None,
    ):
        """Sử dụng dnSpy.Console để xuất toàn bộ project C#."""
        file_path = self._abs_path(file_path)
        output_dir = self._abs_path(output_dir)

        # fh_dir = file_hash + output_dir
        print(f"[*] Đang Decompile project (dnSpy-Ex) vào: {output_dir}")
        if pipeline_logger:
            pipeline_logger.log(
                "dotnet_agent.decompile",
                "started",
                "Starting dnSpy decompile",
                output_dir=output_dir,
            )

        dnspy_exe = self._resolve_executable(
            self._tool_config("dnspy"),
            [
                # preferred wrapper name
                "dnspyc.exe",
                "dnspyc",
                # fallback to dnSpy console (if user points config at it)
                "dnSpy.Console.exe",
                "dnSpy.Console",
            ],
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

        # Safety: only delete output inside output_root to avoid accidents
        output_root_abs = self._abs_path(self.output_root)
        if not os.path.commonpath([output_root_abs, output_dir]) == output_root_abs:
            raise ValueError(f"Refusing to use output_dir outside output_root: {output_dir}")

        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)
        os.makedirs(output_dir, exist_ok=True)

        try:
            # Lệnh: dnSpy.Console.exe -o <outdir> <file>
            # Thêm các option tối ưu cho malware: --no-resources để nhanh hơn nếu chỉ cần code
            print(f"[*] Input file (absolute): {file_path}")
            print(f"[*] Output dir  (absolute): {output_dir}")
            cmd = [dnspy_exe, "-o", output_dir, file_path]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                print(f"[-] dnSpy-Ex exited with code {proc.returncode}")
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
                        exit_code=proc.returncode,
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
    
    async def run_goose_analysis(
        self,
        specific_out_dir: str,
        pipeline_logger: Optional[PipelineLogger] = None,
    ) -> str:
        # 3. Gọi AI phân tích cấu trúc thư mục source C# thông qua shared Claude Code runner.
        print("[*] Đang khởi chạy Claude Code để phân tích mã nguồn C#...")
        if pipeline_logger:
            pipeline_logger.log(
                "dotnet_agent.claude",
                "started",
                "Starting Claude Code source analysis",
            )

        # Use workspace-relative forward-slash paths to avoid Windows backslash issues inside LLM/tool calls.
        workspace_dir = self._to_workspace_rel_posix(specific_out_dir)
        key_files = self._pick_interesting_cs_files(specific_out_dir, limit=15)

        if not key_files:
            print("[WARN] No .cs files found for analysis (directory missing or empty).")

        files_block = "\n".join(f"- {p}" for p in key_files) if key_files else "- (no .cs files detected)"

        instruction = (
            "You are a Senior .NET Malware Researcher. "
            f"Examine the decompiled C# source code under: {workspace_dir}\n"
            "Start by opening the files listed below (they are paths inside the current workspace).\n"
            f"Files to read first:\n{files_block}\n\n"
            "Tasks:\n"
            "1) Identify the Entry Point and main execution flow.\n"
            "2) Search for sensitive strings, API imports (P/Invoke), or network activities.\n"
            "3) Explain any malicious behavior or obfuscation remaining (e.g., Costura/Fody loaders).\n"
            "4) NEVER try to execute any code.\n"
            "If you cannot read files, write exactly: Error: File cannot accessed.\n"
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
    ) -> Dict[str, Any]:
        """Workflow .NET: de4dot -> dnSpy-Ex -> Goose Analysis."""
        file_hash = self._get_file_hash(file_path)
        specific_out_dir = os.path.join(self.output_root, file_hash)
        if pipeline_logger:
            pipeline_logger.log(
                "dotnet_agent",
                "started",
                "DotNet analysis started",
                file_name=os.path.basename(file_path),
                file_hash=file_hash,
            )

        # 1. Unpack/Clean file
        # target_file = await self.run_de4dot(file_path)

        # 2. Decompile ra mã nguồn C#
        dnspyc = await self.run_dnspy_decompile(
            file_path,
            specific_out_dir,
            pipeline_logger=pipeline_logger,
        )
        if not dnspyc:
            return {
                "error": "Decompilation failed"
            }
        goose_report_raw = await self.run_goose_analysis(
            specific_out_dir,
            pipeline_logger=pipeline_logger,
        )
        # clean_rp = self.filter_goose_report(goose_report_raw)

        # Dọn dẹp file cleaned sau khi xong (tùy chọn)
        # if target_file != file_path and os.path.exists(target_file):
        #     os.remove(target_file)

        f_context = {
            # "type": "DOTNET_ANALYSIS",
            "file_name": os.path.basename(file_path),
            "file_hash": file_hash,
            "source_directory": specific_out_dir,
            "ai_analysis_report": goose_report_raw
        }

        print(f"\n[INFO] Phân tích hoàn tất.")
        return f_context