import unittest
from unittest.mock import AsyncMock, patch

from core.claude_code_runner import run_claude_code


class ClaudeCodeRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_command_uses_claude_prompt_flag_and_instruction(self):
        process = AsyncMock()
        process.communicate.return_value = ("output", "")
        process.returncode = 0

        with patch("core.claude_code_runner.asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)) as create_subprocess_exec:
            result = await run_claude_code("inspect binary")

        create_subprocess_exec.assert_awaited_once()
        args = create_subprocess_exec.await_args.args
        self.assertEqual(args[:4], ("claude", "-p", "--dangerously-skip-permissions", "inspect binary"))
        self.assertEqual(result, "output")

    async def test_configured_command_list_is_honored(self):
        process = AsyncMock()
        process.communicate.return_value = ("configured", "")
        process.returncode = 0
        config = {"llm": {"claude_code_command": ["custom-claude", "--json"]}}

        with patch("core.claude_code_runner.asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)) as create_subprocess_exec:
            result = await run_claude_code("inspect binary", config=config)

        create_subprocess_exec.assert_awaited_once()
        args = create_subprocess_exec.await_args.args
        self.assertEqual(args[:5], ("custom-claude", "--json", "-p", "--dangerously-skip-permissions", "inspect binary"))
        self.assertEqual(result, "configured")

    async def test_non_zero_exit_raises_runtimeerror_with_stderr_context(self):
        process = AsyncMock()
        process.communicate.return_value = (b"partial\xffoutput", b"fatal error")
        process.returncode = 7

        with patch("core.claude_code_runner.asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)):
            with self.assertRaisesRegex(RuntimeError, "exit code 7") as exc_info:
                await run_claude_code("inspect binary")

        message = str(exc_info.exception)
        self.assertIn("fatal error", message)
        self.assertIn("inspect binary", message)
        self.assertIn("claude", message)

    async def test_missing_binary_propagates_filenotfounderror(self):
        with patch(
            "core.claude_code_runner.asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=FileNotFoundError("missing")),
        ):
            with self.assertRaises(FileNotFoundError):
                await run_claude_code("inspect binary")


if __name__ == "__main__":
    unittest.main()
