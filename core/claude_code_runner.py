import asyncio
from typing import Any, Dict, Optional

from core.pipeline_logger import PipelineLogger
from core.task_runtime import create_child_task_scope, run_tracked_process, run_tracked_subprocess
from core.tool_policy import get_claude_code_args, get_claude_code_command

_MAX_TASK_OUTPUT_CHARS = 4000


def _bounded_text(value: str) -> tuple[str, bool]:
    if len(value) <= _MAX_TASK_OUTPUT_CHARS:
        return value, False
    return value[:_MAX_TASK_OUTPUT_CHARS], True


async def _run_claude_process(
    command: list[str],
    command_args: list[str],
    *,
    pipeline_logger: PipelineLogger | None = None,
) -> tuple[int, bytes | str, bytes | str, str]:
    argv = [*command, *command_args]
    try:
        returncode, stdout, stderr = await run_tracked_process(*argv, pipeline_logger=pipeline_logger)
        return returncode, stdout, stderr, "asyncio_subprocess"
    except NotImplementedError:
        completed = await asyncio.to_thread(
            run_tracked_subprocess,
            argv,
            pipeline_logger=pipeline_logger,
        )
        return completed.returncode, completed.stdout, completed.stderr, "threaded_subprocess"


async def run_claude_code(
    instruction: str,
    config: Optional[Dict[str, Any]] = None,
    pipeline_logger: Optional[PipelineLogger] = None,
) -> str:
    command = get_claude_code_command(config)
    command_args = get_claude_code_args(instruction)

    runner_logger = pipeline_logger
    if pipeline_logger:
        _, runner_logger = create_child_task_scope(
            pipeline_logger,
            stage_key="claude_runner",
            title="Launch Claude Code command",
        )
        runner_logger.log(
            "claude_runner",
            "started",
            "Launching Claude Code command",
            command=" ".join(command),
        )

    returncode, stdout, stderr, execution_mode = await _run_claude_process(
        command,
        command_args,
        pipeline_logger=runner_logger,
    )

    if isinstance(stdout, bytes):
        stdout = stdout.decode(errors="replace")
    if isinstance(stderr, bytes):
        stderr = stderr.decode(errors="replace")

    bounded_stdout, stdout_truncated = _bounded_text(stdout)
    bounded_stderr, stderr_truncated = _bounded_text(stderr)

    if returncode != 0:
        if runner_logger:
            runner_logger.record_output(
                {
                    "stdout": bounded_stdout,
                    "stdout_truncated": stdout_truncated,
                    "stderr": bounded_stderr,
                    "stderr_truncated": stderr_truncated,
                    "exit_code": returncode,
                    "execution_mode": execution_mode,
                    "command": command,
                },
                output_kind="claude_command",
            )
            runner_logger.log(
                "claude_runner",
                "failed",
                "Claude Code command failed",
                exit_code=returncode,
                execution_mode=execution_mode,
                stderr=(bounded_stderr[:500] if bounded_stderr else ""),
                error=bounded_stderr,
            )
        raise RuntimeError(
            f"Claude Code command failed with exit code {returncode}: {command!r}"
            f" for instruction {instruction!r}. stderr: {stderr}"
        )

    if runner_logger:
        runner_logger.record_output(
            {
                "stdout": bounded_stdout,
                "stdout_truncated": stdout_truncated,
                "stderr": bounded_stderr,
                "stderr_truncated": stderr_truncated,
                "exit_code": returncode,
                "execution_mode": execution_mode,
                "command": command,
            },
            output_kind="claude_command",
        )
        runner_logger.log(
            "claude_runner",
            "completed",
            "Claude Code command completed",
            exit_code=returncode,
            execution_mode=execution_mode,
        )

    return stdout
