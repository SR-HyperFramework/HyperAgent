import asyncio
import subprocess
import os
import yaml
from typing import Dict, Any, List
import hashlib
import re
import shlex
import time

# Adjust import based on project structure
# from core.mcp_client import IDAMCPClient

class NativeAgent:
    def __init__(self, config_path: str = "config.yaml"):
        self.config = self._load_config(config_path)
        self.ida_mcp_cmd = "uv run idalib-mcp"
        self.goose_cmd = "goose"
        
        # Auto-configure IDA_PATH environment variable for idalib
        ida_path = self.config.get("tools", {}).get("ida_path")
        if ida_path:
            os.environ["IDA_PATH"] = ida_path
            # Also add to PATH to ensure ida64.exe/ida.exe can be found if needed
            if ida_path not in os.environ["PATH"]:
                os.environ["PATH"] = ida_path + os.pathsep + os.environ["PATH"]

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

    async def _wait_for_port(self, host: str, port: int, timeout_s: float = 30.0) -> bool:
        """Wait until a TCP port is accepting connections."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                reader, writer = await asyncio.open_connection(host, port)
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass
                return True
            except Exception:
                await asyncio.sleep(0.5)
        return False

    async def run_goose_analysis(self, file_path: str) -> str:
        """Khởi chạy IDA MCP Server và bắt Stream từ Goose CLI."""
        print(f"[INFO] Khởi động IDA MCP Server cho: {os.path.basename(file_path)} tại {file_path}")
        
        server_proc = None
        captured_logs = []
        try:
            # 1. Khởi động idalib-mcp server chạy ngầm (no shell -> fewer quoting/path issues)
            host = "127.0.0.1"
            port = 8745
            server_args = shlex.split(self.ida_mcp_cmd, posix=False)
            server_args += ["--host", host, "--port", str(port), file_path]

            creationflags = 0
            if os.name == "nt" and hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

            # Capture stderr so we can diagnose 'cannot access file' issues.
            server_proc = await asyncio.create_subprocess_exec(
                *server_args,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                creationflags=creationflags,
            )

            # Wait for MCP server port to accept connections before running goose.
            ready = await self._wait_for_port(host, port, timeout_s=45.0)
            if not ready:
                server_err = ""
                try:
                    if server_proc.stderr is not None:
                        server_err_bytes = await asyncio.wait_for(server_proc.stderr.read(4096), timeout=1)
                        server_err = server_err_bytes.decode("utf-8", errors="ignore")
                except Exception:
                    pass
                return f"Error: IDA MCP server not ready on {host}:{port}. {server_err}".strip()

            # Give IDA a bit more time to finish initial auto-analysis if needed.
            await asyncio.sleep(5)

            print("[INFO] Đang chạy Goose AI Agent (Bắt luồng stream trực tiếp)...")
            
            # Instruction tối ưu cho Crackme/Malware
            abs_target = os.path.abspath(file_path)
            instruction = (
                f"Target file path: {abs_target}. "
                f"An IDA MCP server is already running at http://{host}:{port}/sse with this file loaded. "
                "Use MCP tools to inspect decompilation and add comments, rename variables and functions for clarity, "
                "adjust variable/argument types (pointers/arrays), disassemble functions for deeper detail if needed. "
                "ALWAYS use 'int_convert' for number bases. "
                "Document all steps and findings in result as Markdown type. "
                "ALWAYS start the report **Start of Analysis** and end with **End of Analysis**. "
                "If you cannot access the target via MCP, return exactly: Error: Cannot access target file." 
                "Do not draw table."
            )
            
            # 2. Chạy Goose và hứng STDOUT theo thời gian thực
            goose_proc = await asyncio.create_subprocess_exec(
                self.goose_cmd, "run", "--text", instruction,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )

            while True:
                line = await goose_proc.stdout.readline()
                if not line:
                    break
                
                decoded_line = line.decode('utf-8', errors='ignore')
                captured_logs.append(decoded_line)
                
                # In ra màn hình để người dùng theo dõi tiến trình của AI
                if "[tool call" not in decoded_line.lower(): # Ẩn bớt log gọi tool cho sạch
                    print(f"  [IDA-AI]: {decoded_line.strip()}")

            await goose_proc.wait()
            return "".join(captured_logs)

        except FileNotFoundError as e:
            return f"Missing dependency: {str(e)}"

        except Exception as e:
            return f"Lỗi thực thi Goose: {str(e)}"
        finally:
            # Dọn dẹp: Tắt server IDA và giải phóng port
            if server_proc is not None:
                try:
                    if os.name == "nt":
                        subprocess.run(
                            ["taskkill", "/PID", str(server_proc.pid), "/T", "/F"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            check=False,
                        )
                    else:
                        server_proc.terminate()
                    try:
                        await asyncio.wait_for(server_proc.wait(), timeout=5)
                    except Exception:
                        try:
                            server_proc.kill()
                        except Exception:
                            pass
                except Exception:
                    pass
            print("[INFO] Đã đóng IDA MCP Server.")

    @staticmethod
    def filter_goose_report(raw_log: str) -> str:
        # 1. Cắt đoạn từ **Start of Analysis** đến **End of Analysis**
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

        # 2. Regex để xóa các log gọi tool MCP (các thanh kẻ ngang ───)
        # Loại bỏ các dòng dạng: ─── tên_tool | ida ─────────────────────────-
        content = re.sub(r"───.*?\n", "", content)

        # Loại bỏ các thông báo lỗi tham số tool (nếu có)
        content = re.sub(r"-\d+: Could not interpret tool use parameters.*?\n", "", content)

        # Loại bỏ các dòng trống dư thừa
        content = re.sub(r"\n\s*\n", "\n\n", content).strip()

        return content

    async def analyze(self, file_path: str) -> Dict[str, Any]:
        """Workflow chính: Tự động hóa toàn bộ quá trình."""
        if not os.path.exists(file_path):
            return {"error": "File không tồn tại"}

        file_hash = self._get_file_hash(file_path)
        
        # Bước 2: Chạy Goose Analysis (Bắt stream)
        # Bước này thường lâu hơn nên chúng ta đợi CAPA/FLOSS hoàn thành trước hoặc song song
        goose_report_raw = await self.run_goose_analysis(file_path)
        clean_rp = self.filter_goose_report(goose_report_raw)
        
        # capa_res, floss_res = await asyncio.gather(capa_task, floss_task)

        # Bước 3: Tổng hợp kết quả (Context Logger)
        f_context = {
            "file_name": os.path.basename(file_path),
            "file_hash": file_hash,
            "ai_analysis_report": clean_rp,
        }

        print(f"\n[INFO] Phân tích hoàn tất.")
        return f_context