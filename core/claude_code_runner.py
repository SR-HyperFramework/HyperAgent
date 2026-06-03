import asyncio
from typing import Any, Dict, Optional

from core.pipeline_logger import PipelineLogger


async def run_claude_code(
    instruction: str,
    config: Optional[Dict[str, Any]] = None,
    pipeline_logger: Optional[PipelineLogger] = None,
) -> str:
    command = ["claude"]
    if config:
        configured_command = config.get("llm", {}).get("claude_code_command")
        if isinstance(configured_command, list) and configured_command:
            command = configured_command

    if pipeline_logger:
        pipeline_logger.log(
            "claude_runner",
            "started",
            "Launching Claude Code command",
            command=" ".join(command),
        )

    process = await asyncio.create_subprocess_exec(
        *command,
        "-p",
        "--dangerously-skip-permissions",
        instruction,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    if isinstance(stdout, bytes):
        stdout = stdout.decode(errors="replace")
    if isinstance(stderr, bytes):
        stderr = stderr.decode(errors="replace")

    if process.returncode != 0:
        if pipeline_logger:
            pipeline_logger.log(
                "claude_runner",
                "failed",
                "Claude Code command failed",
                exit_code=process.returncode,
                stderr=(stderr[:500] if stderr else ""),
            )
        raise RuntimeError(
            f"Claude Code command failed with exit code {process.returncode}: {command!r}"
            f" for instruction {instruction!r}. stderr: {stderr}"
        )

    if pipeline_logger:
        pipeline_logger.log(
            "claude_runner",
            "completed",
            "Claude Code command completed",
            exit_code=process.returncode,
        )

    return stdout
