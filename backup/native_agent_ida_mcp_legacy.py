import asyncio
import subprocess
import os
import yaml
from typing import Dict, Any, Optional
import hashlib
import re
import shlex
import time

from core.claude_code_runner import run_claude_code
from core.pipeline_logger import PipelineLogger


class NativeAgent:
    def __init__(self, config_path: str = "config.yaml"):
        self.config = self._load_config(config_path)
        self.ida_mcp_cmd = "uv run idalib-mcp"
        # self.goose_cmd = "goose"
        mcp_cfg = (self.config or {}).get("mcp") or {}
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

    async def _probe_http(
        self,
        host: str,
        port: int,
        path: str,
        expect_sse: bool,
        timeout_s: float = 2.0,
    ) -> bool:
        """Probe an HTTP endpoint and return True when the MCP server responds as expected."""
        writer = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=timeout_s
            )
            request = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
                "Accept: */*\r\n"
                "Connection: close\r\n"
                "\r\n"
            )
            writer.write(request.encode("ascii", errors="ignore"))
            await writer.drain()

            raw_response = await asyncio.wait_for(reader.read(2048), timeout=timeout_s)
            response_text = raw_response.decode("utf-8", errors="ignore")

            if expect_sse:
                return (
                    ("HTTP/1.1 200" in response_text or "HTTP/1.0 200" in response_text)
                    and "text/event-stream" in response_text.lower()
                )

            return "HTTP/1.1" in response_text or "HTTP/1.0" in response_text
        except Exception:
            return False
        finally:
            if writer is not None:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

    async def _wait_for_http_ready(self, host: str, port: int, timeout_s: float) -> bool:
        """Wait until the IDA MCP HTTP/SSE interface is actually usable."""
        deadline = time.monotonic() + timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False

            probe_timeout_s = min(2.0, remaining)
            if await self._probe_http(host, port, "/sse", expect_sse=True, timeout_s=probe_timeout_s):
                return True

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False

            probe_timeout_s = min(2.0, remaining)
            if await self._probe_http(host, port, "/", expect_sse=False, timeout_s=probe_timeout_s):
                return True

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False

            await asyncio.sleep(min(self.ida_probe_interval_s, remaining))

    async def run_goose_analysis(
        self,
        file_path: str,
        pipeline_logger: Optional[PipelineLogger] = None,
    ) -> str:
        """Khởi chạy IDA MCP Server và dùng shared Claude Code runner cho bước AI."""
        if pipeline_logger:
            pipeline_logger.log(
                "native_agent.ida_mcp",
                "started",
                "Starting IDA MCP server",
                file_name=os.path.basename(file_path),
                file_path=file_path,
            )
        print(f"[INFO] Starting IDA MCP server for: {os.path.basename(file_path)} at {file_path}")

        server_proc = None
        try:
            host = "127.0.0.1"
            port = 13337
            server_args = shlex.split(self.ida_mcp_cmd, posix=False)
            server_args += ["--host", host, "--port", str(port), file_path]
            print(f"[DEBUG] IDA MCP command: {server_args!r}")
            if pipeline_logger:
                pipeline_logger.log(
                    "native_agent.ida_mcp",
                    "running",
                    "IDA MCP command prepared",
                    command=" ".join(server_args),
                )

            creationflags = 0
            if os.name == "nt" and hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

            try:
                server_proc = await asyncio.create_subprocess_exec(
                    *server_args,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                    creationflags=creationflags,
                )
            except FileNotFoundError as e:
                if pipeline_logger:
                    pipeline_logger.log(
                        "native_agent.ida_mcp",
                        "failed",
                        "Missing dependency while starting IDA MCP",
                        error=str(e),
                    )
                return f"Missing dependency while starting command {server_args!r}: {str(e)}"

            ready = await self._wait_for_http_ready(
                host, port, timeout_s=self.ida_startup_timeout_s
            )
            if pipeline_logger and ready:
                pipeline_logger.log(
                    "native_agent.ida_mcp",
                    "completed",
                    "IDA MCP server is ready",
                    host=host,
                    port=port,
                )
            if not ready:
                server_err = ""
                try:
                    if server_proc.stderr is not None:
                        server_err_bytes = await asyncio.wait_for(
                            server_proc.stderr.read(4096), timeout=1
                        )
                        server_err = server_err_bytes.decode("utf-8", errors="ignore")
                except Exception:
                    pass
                if pipeline_logger:
                    pipeline_logger.log(
                        "native_agent.ida_mcp",
                        "failed",
                        "IDA MCP HTTP not ready",
                        host=host,
                        port=port,
                        timeout_s=self.ida_startup_timeout_s,
                        stderr=server_err[:500],
                    )
                return (
                    f"Error: IDA MCP HTTP not ready on http://{host}:{port} "
                    f"within {self.ida_startup_timeout_s:.0f}s. {server_err}"
                ).strip()

            await asyncio.sleep(5)

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
                    "started",
                    "Cleaning up native analysis resources",
                )
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
            print("[INFO] Closed IDA MCP server.")
            if pipeline_logger:
                pipeline_logger.log(
                    "native_agent.cleanup",
                    "completed",
                    "Closed IDA MCP server",
                )
