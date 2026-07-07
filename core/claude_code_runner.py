import asyncio
import subprocess
from typing import Any, Dict, Optional

from core.pipeline_logger import PipelineLogger
from core.tool_policy import get_claude_code_args, get_claude_code_command


async def _run_claude_process(command: list[str], command_args: list[str]) -> tuple[int, bytes | str, bytes | str, str]:
    argv = [*command, *command_args]
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        return process.returncode, stdout, stderr, "asyncio_subprocess"
    except NotImplementedError:
        completed = await asyncio.to_thread(
            subprocess.run,
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        return completed.returncode, completed.stdout, completed.stderr, "threaded_subprocess"


async def run_claude_code(
    instruction: str,
    config: Optional[Dict[str, Any]] = None,
    pipeline_logger: Optional[PipelineLogger] = None,
) -> str:
    command = get_claude_code_command(config)
    command_args = get_claude_code_args(instruction)

    if pipeline_logger:
        pipeline_logger.log(
            "claude_runner",
            "started",
            "Launching Claude Code command",
            command=" ".join(command),
        )

    returncode, stdout, stderr, execution_mode = await _run_claude_process(command, command_args)

    if isinstance(stdout, bytes):
        stdout = stdout.decode(errors="replace")
    if isinstance(stderr, bytes):
        stderr = stderr.decode(errors="replace")

    if returncode != 0:
        if pipeline_logger:
            pipeline_logger.log(
                "claude_runner",
                "failed",
                "Claude Code command failed",
                exit_code=returncode,
                execution_mode=execution_mode,
                stderr=(stderr[:500] if stderr else ""),
            )
        raise RuntimeError(
            f"Claude Code command failed with exit code {returncode}: {command!r}"
            f" for instruction {instruction!r}. stderr: {stderr}"
        )

    if pipeline_logger:
        pipeline_logger.log(
            "claude_runner",
            "completed",
            "Claude Code command completed",
            exit_code=returncode,
            execution_mode=execution_mode,
        )

    return stdout
