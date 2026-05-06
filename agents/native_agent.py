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
        mcp_cfg = (self.config or {}).get("mcp") or {}
        # Big binaries (eg. Go) can take a long time before the MCP HTTP server is actually usable.
        # config.yaml example:
        # mcp:
        #   ida_startup_timeout_s: 300
        #   ida_probe_interval_s: 0.5
        self.ida_startup_timeout_s = float(mcp_cfg.get("ida_startup_timeout_s", 180))
        self.ida_probe_interval_s = float(mcp_cfg.get("ida_probe_interval_s", 0.5))

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

    async def _probe_http(self, host: str, port: int, path: str, expect_sse: bool, timeout_s: float = 2.0) -> bool:
        """Probe an HTTP endpoint and return True if it responds.

        If expect_sse=True, requires status 200 and 'text/event-stream' header.
        Otherwise any HTTP status line is treated as success.
        """
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout_s)
            req = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
                "Accept: */*\r\n"
                "Connection: close\r\n"
                "\r\n"
            )
            writer.write(req.encode("ascii", errors="ignore"))
            await writer.drain()

            raw = await asyncio.wait_for(reader.read(2048), timeout=timeout_s)
            text = raw.decode("utf-8", errors="ignore")
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

            if expect_sse:
                return ("HTTP/1.1 200" in text or "HTTP/1.0 200" in text) and ("text/event-stream" in text.lower())

            return "HTTP/1.1" in text or "HTTP/1.0" in text
        except Exception:
            return False

    async def _wait_for_http_ready(self, host: str, port: int, timeout_s: float) -> bool:
        """Poll MCP HTTP server until it is usable."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            # Prefer /sse because it indicates the SSE endpoint is live.
            if await self._probe_http(host, port, "/sse", expect_sse=True, timeout_s=2.0):
                return True
            # Fallback: root responds (even 404/redirect/etc) means HTTP server is up.
            if await self._probe_http(host, port, "/", expect_sse=False, timeout_s=2.0):
                return True
            await asyncio.sleep(self.ida_probe_interval_s)
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

            # Wait until MCP HTTP is actually responding, then start Goose.
            ready = await self._wait_for_http_ready(host, port, timeout_s=self.ida_startup_timeout_s)
            if not ready:
                server_err = ""
                try:
                    if server_proc.stderr is not None:
                        server_err_bytes = await asyncio.wait_for(server_proc.stderr.read(4096), timeout=1)
                        server_err = server_err_bytes.decode("utf-8", errors="ignore")
                except Exception:
                    pass
                return (
                    f"Error: IDA MCP HTTP not ready on http://{host}:{port} within {self.ida_startup_timeout_s:.0f}s. "
                    f"{server_err}"
                ).strip()

            # Give IDA a bit more time to finish initial auto-analysis if needed.
            await asyncio.sleep(5)

            print("[INFO] Đang chạy Goose AI Agent (Bắt luồng stream trực tiếp)...")
            
            # Instruction tối ưu cho Crackme/Malware
            abs_target = os.path.abspath(file_path)
            instruction = (
                "Role: Senior Malware Researcher.\n"
                f"Target: {abs_target}\n"
                f"IDA MCP: http://{host}:{port}/sse\n\n"
                "If MCP fails, reply exactly: 'Error: Cannot access target file.\n"
                "Tasks:\n"
                "- Decompile & Comment: Explain logic, fix types (ptr/array).\n"
                "- Deep Dive: Disassemble if detail is needed.\n"
                "- Number Base: ALWAYS use 'int_convert' for ALL bases.\n"
                "- Constraint: No tables.'\n\n"
                "Report Structure (Strictly Follow):\n"
                "1. Start with **Start of Analysis**.\n"
                "2. Content: [Entry Point & Main Flow] | [Sensitive Strings, IOCs, Network] | [API Imports/P-Invoke] | [Malicious Behavior/Obfuscation] | [File Summary] | [Conclusion].\n"
                "3. End with **End of Analysis**."
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