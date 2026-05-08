import asyncio
from typing import Any, Dict, Optional


async def run_claude_code(instruction: str, config: Optional[Dict[str, Any]] = None) -> str:
    command = ["claude"]
    if config:
        configured_command = config.get("llm", {}).get("claude_code_command")
        if isinstance(configured_command, list) and configured_command:
            command = configured_command

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
        raise RuntimeError(
            f"Claude Code command failed with exit code {process.returncode}: {command!r}"
            f" for instruction {instruction!r}. stderr: {stderr}"
        )

    return stdout
