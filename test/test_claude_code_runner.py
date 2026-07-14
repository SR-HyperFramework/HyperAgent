import subprocess
import unittest
from unittest.mock import AsyncMock, patch

from core.task_runtime import TrackedCompletedProcess

from core.claude_code_runner import run_claude_code
from core.pipeline_logger import PipelineLogger


class ClaudeCodeRunnerTaskScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_runner_creates_distinct_claude_task_scope(self):
        logger = PipelineLogger(run_id="run-1", task_id="parent-task", session_id="parent-session", executor_kind="claude")

        with patch("core.claude_code_runner.run_tracked_process", new=AsyncMock(return_value=(0, "output", ""))):
            result = await run_claude_code("inspect binary", pipeline_logger=logger)

        self.assertEqual(result, "output")
        events = logger.snapshot()
        self.assertEqual([event["stage"] for event in events], ["claude_runner", "claude_runner"])
        self.assertEqual([event["state"] for event in events], ["started", "completed"])
        started, completed = events
        self.assertEqual(started["data"]["executor_kind"], "claude")
        self.assertEqual(completed["data"]["executor_kind"], "claude")
        self.assertEqual(started["data"]["parent_task_id"], "parent-task")
        self.assertEqual(completed["data"]["parent_task_id"], "parent-task")
        self.assertEqual(started["data"]["task_id"], completed["data"]["task_id"])
        self.assertNotEqual(started["data"]["task_id"], "parent-task")
        self.assertNotEqual(started["data"]["session_id"], "parent-session")

        output = logger.task_output(task_id=started["data"]["task_id"])
        self.assertEqual(output["output_kind"], "claude_command")
        self.assertEqual(output["result"]["stdout"], "output")
        self.assertEqual(output["result"]["exit_code"], 0)
        self.assertEqual(output["status"], "completed")
        self.assertEqual(output["terminal_state"], "success")

    async def test_runner_records_stderr_and_exit_code_on_failure(self):
        logger = PipelineLogger(run_id="run-1", task_id="parent-task", session_id="parent-session", executor_kind="claude")

        with patch("core.claude_code_runner.run_tracked_process", new=AsyncMock(return_value=(9, b"partial", b"fatal error"))):
            with self.assertRaisesRegex(RuntimeError, "exit code 9"):
                await run_claude_code("inspect binary", pipeline_logger=logger)

        child_task_id = logger.snapshot()[0]["data"]["task_id"]
        output = logger.task_output(task_id=child_task_id)
        self.assertEqual(output["output_kind"], "claude_command")
        self.assertEqual(output["result"]["stderr"], "fatal error")
        self.assertEqual(output["result"]["exit_code"], 9)
        self.assertEqual(output["status"], "completed")
        self.assertEqual(output["terminal_state"], "failed")
        self.assertEqual(output["error"], "fatal error")


class ClaudeCodeRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_command_uses_claude_prompt_flag_and_instruction(self):
        tracked = AsyncMock(return_value=(0, "output", ""))

        with patch("core.claude_code_runner.run_tracked_process", new=tracked):
            result = await run_claude_code("inspect binary")

        tracked.assert_awaited_once()
        args = tracked.await_args.args
        self.assertEqual(args[:4], ("claude", "-p", "--dangerously-skip-permissions", "inspect binary"))
        self.assertEqual(result, "output")

    async def test_configured_command_list_is_honored(self):
        config = {"llm": {"claude_code_command": ["custom-claude", "--json"]}}
        tracked = AsyncMock(return_value=(0, "configured", ""))

        with patch("core.claude_code_runner.run_tracked_process", new=tracked):
            result = await run_claude_code("inspect binary", config=config)

        tracked.assert_awaited_once()
        args = tracked.await_args.args
        self.assertEqual(args[:5], ("custom-claude", "--json", "-p", "--dangerously-skip-permissions", "inspect binary"))
        self.assertEqual(result, "configured")

    async def test_non_zero_exit_raises_runtimeerror_with_stderr_context(self):
        with patch("core.claude_code_runner.run_tracked_process", new=AsyncMock(return_value=(7, b"partial\xffoutput", b"fatal error"))):
            with self.assertRaisesRegex(RuntimeError, "exit code 7") as exc_info:
                await run_claude_code("inspect binary")

        message = str(exc_info.exception)
        self.assertIn("fatal error", message)
        self.assertIn("inspect binary", message)
        self.assertIn("claude", message)

    async def test_missing_binary_propagates_filenotfounderror(self):
        with patch(
            "core.claude_code_runner.run_tracked_process",
            new=AsyncMock(side_effect=FileNotFoundError("missing")),
        ):
            with self.assertRaises(FileNotFoundError):
                await run_claude_code("inspect binary")

    async def test_notimplementederror_falls_back_to_threaded_subprocess(self):
        completed = TrackedCompletedProcess(
            args=["claude", "-p", "--dangerously-skip-permissions", "inspect binary"],
            returncode=0,
            stdout=b"fallback-output",
            stderr=b"",
        )

        with patch(
            "core.claude_code_runner.run_tracked_process",
            new=AsyncMock(side_effect=NotImplementedError),
        ) as tracked, patch(
            "core.claude_code_runner.run_tracked_subprocess",
            return_value=completed,
        ) as tracked_subprocess:
            result = await run_claude_code("inspect binary")

        tracked.assert_awaited_once()
        tracked_subprocess.assert_called_once()
        self.assertEqual(result, "fallback-output")


if __name__ == "__main__":
    unittest.main()
