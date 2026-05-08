import asyncio
import hashlib
import os
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from agents.dotnet_agent import DotNetAgent
from agents.native_agent import NativeAgent
from agents.script_agent import ScriptAgent


class ScriptAgentRunnerIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_script_agent_builds_prompt_from_extraction_and_pyasm_outputs(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".py", delete=False) as temp_file:
            temp_file.write(b"print('hello')\n")
            file_path = temp_file.name

        with tempfile.TemporaryDirectory() as extract_dir:
            pyasm_path = os.path.join(extract_dir, "__main__.pyc.pyasm")
            source_path = os.path.join(extract_dir, "loader.py")
            nested_dir = os.path.join(extract_dir, "pkg")
            os.makedirs(nested_dir, exist_ok=True)
            nested_pyc = os.path.join(nested_dir, "payload.pyc")

            for path, content in (
                (pyasm_path, "disassembly"),
                (source_path, "print('loader')"),
                (nested_pyc, "bytecode"),
            ):
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)

            try:
                raw_report = "preface\n─── tool | ida ─────────────────────────\n**Start of Analysis**\nUseful finding\n\n-1: Could not interpret tool use parameters bad\n\n**End of Analysis**\ntrailer"
                expected_hash = hashlib.sha256(b"print('hello')\n").hexdigest()

                with patch("agents.script_agent.run_claude_code", new=AsyncMock(return_value=raw_report)) as run_claude_code_mock, patch.object(
                    ScriptAgent,
                    "_ensure_output_dir",
                    return_value=extract_dir,
                ), patch.object(
                    ScriptAgent,
                    "_extract_pyinstaller",
                    new=AsyncMock(return_value=(extract_dir, [pyasm_path, source_path, nested_pyc])),
                ), patch.object(
                    ScriptAgent,
                    "_disassemble_with_pycdas",
                    new=AsyncMock(return_value=[pyasm_path]),
                ):
                    agent = ScriptAgent()
                    result = await agent.analyze(file_path)

                run_claude_code_mock.assert_awaited_once()
                instruction = run_claude_code_mock.await_args.args[0]
                self.assertIs(run_claude_code_mock.await_args.kwargs["config"], agent.config)
                self.assertIn(os.path.abspath(file_path), instruction)
                self.assertIn("Start with the generated .pyasm files", instruction)
                self.assertIn("Use the extracted contents under:", instruction)
                self.assertIn("__main__.pyc.pyasm", instruction)
                self.assertIn("loader.py", instruction)
                self.assertIn("payload.pyc", instruction)
                self.assertIn("Cross-check findings between .pyasm output", instruction)
                self.assertIn("NEVER execute the file", instruction)

                self.assertEqual(result["file_name"], os.path.basename(file_path))
                self.assertEqual(result["file_hash"], expected_hash)
                self.assertEqual(result["pyasm_files"], [agent._to_workspace_rel_posix(pyasm_path)])
                self.assertEqual(result["extract_dir"], extract_dir)
                self.assertEqual(
                    result["ai_analysis_report"],
                    "**Start of Analysis**\nUseful finding\n\n**End of Analysis**",
                )
            finally:
                os.unlink(file_path)


class NativeAgentRunnerIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def _make_server_proc(self, pid=4321, stderr_bytes=b""):
        proc = Mock()
        proc.pid = pid
        proc.stderr = Mock()
        proc.stderr.read = AsyncMock(return_value=stderr_bytes)
        proc.wait = AsyncMock(return_value=0)
        proc.kill = Mock()
        proc.terminate = Mock()
        return proc

    async def test_native_agent_builds_prompt_and_filters_runner_output(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".exe", delete=False) as temp_file:
            temp_file.write(b"MZ\x00native")
            file_path = temp_file.name

        raw_report = "noise\n─── tool | ida ─────────────────────────\n**Start of Analysis**\nNative finding\n\n-1: Could not interpret tool use parameters nope\n\n**End of Analysis**\ntrailer"
        expected_hash = hashlib.sha256(b"MZ\x00native").hexdigest()
        fake_server_proc = self._make_server_proc()

        try:
            with patch("agents.native_agent.print"), patch("agents.native_agent.run_claude_code", new=AsyncMock(return_value=raw_report)) as run_claude_code_mock, patch(
                "agents.native_agent.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=fake_server_proc),
            ) as create_subprocess_mock, patch.object(
                NativeAgent,
                "_wait_for_http_ready",
                new=AsyncMock(return_value=True),
            ) as wait_for_http_ready_mock, patch("agents.native_agent.asyncio.sleep", new=AsyncMock()) as sleep_mock, patch(
                "agents.native_agent.subprocess.run"
            ) as taskkill_mock:
                agent = NativeAgent()
                result = await agent.analyze(file_path)

            expected_creationflags = 0
            if os.name == "nt" and hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
                expected_creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

            create_subprocess_mock.assert_awaited_once_with(
                "uv",
                "run",
                "idalib-mcp",
                "--host",
                "127.0.0.1",
                "--port",
                "8745",
                file_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                creationflags=expected_creationflags,
            )
            wait_for_http_ready_mock.assert_awaited_once_with(
                "127.0.0.1", 8745, timeout_s=agent.ida_startup_timeout_s
            )
            sleep_mock.assert_awaited_once_with(5)
            run_claude_code_mock.assert_awaited_once()

            instruction = run_claude_code_mock.await_args.args[0]
            self.assertIs(run_claude_code_mock.await_args.kwargs["config"], agent.config)
            self.assertIn(os.path.abspath(file_path), instruction)
            self.assertIn("An IDA MCP server is already running with this file loaded.", instruction)
            self.assertIn("Use hyperagent-malware-analysis skill and start analyze", instruction)

            taskkill_mock.assert_called_once()
            self.assertEqual(result["file_name"], os.path.basename(file_path))
            self.assertEqual(result["file_hash"], expected_hash)
            self.assertEqual(
                result["ai_analysis_report"],
                "**Start of Analysis**\nNative finding\n\n**End of Analysis**",
            )

        finally:
            os.unlink(file_path)

    async def test_native_agent_wait_for_http_ready_prefers_sse_probe(self):
        agent = NativeAgent()
        probe_results = [True]

        async def fake_probe(host, port, path, expect_sse, timeout_s=2.0):
            self.assertEqual(host, "127.0.0.1")
            self.assertEqual(port, 8745)
            self.assertEqual(path, "/sse")
            self.assertTrue(expect_sse)
            return probe_results.pop(0)

        with patch.object(agent, "_probe_http", side_effect=fake_probe) as probe_mock, patch(
            "agents.native_agent.asyncio.sleep", new=AsyncMock()
        ) as sleep_mock:
            ready = await agent._wait_for_http_ready("127.0.0.1", 8745, timeout_s=1)

        self.assertTrue(ready)
        probe_mock.assert_awaited_once()
        sleep_mock.assert_not_awaited()

    async def test_native_agent_wait_for_http_ready_falls_back_to_root_probe(self):
        agent = NativeAgent()
        probe_results = [False, True]

        async def fake_probe(host, port, path, expect_sse, timeout_s=2.0):
            result = probe_results.pop(0)
            if path == "/sse":
                self.assertTrue(expect_sse)
            elif path == "/":
                self.assertFalse(expect_sse)
            else:
                self.fail(f"unexpected probe path: {path}")
            return result

        with patch.object(agent, "_probe_http", side_effect=fake_probe) as probe_mock, patch(
            "agents.native_agent.asyncio.sleep", new=AsyncMock()
        ) as sleep_mock:
            ready = await agent._wait_for_http_ready("127.0.0.1", 8745, timeout_s=1)

        self.assertTrue(ready)
        self.assertEqual(probe_mock.await_count, 2)
        sleep_mock.assert_not_awaited()

    async def test_native_agent_wait_for_http_ready_bounds_probe_timeout_to_deadline(self):
        agent = NativeAgent()
        time_values = iter([100.0, 100.0, 100.25, 100.7, 101.05])
        probe_timeouts = []

        async def fake_probe(host, port, path, expect_sse, timeout_s=2.0):
            probe_timeouts.append((path, timeout_s))
            return False

        with patch.object(agent, "_probe_http", side_effect=fake_probe), patch(
            "agents.native_agent.time.monotonic", side_effect=lambda: next(time_values)
        ), patch("agents.native_agent.asyncio.sleep", new=AsyncMock()) as sleep_mock:
            ready = await agent._wait_for_http_ready("127.0.0.1", 8745, timeout_s=1)

        self.assertFalse(ready)
        self.assertEqual(probe_timeouts, [("/sse", 1.0), ("/", 0.75)])
        sleep_mock.assert_awaited_once_with(0.29999999999999716)

    async def test_native_agent_probe_http_closes_writer_when_read_raises(self):
        agent = NativeAgent()
        reader = AsyncMock()
        reader.read.side_effect = RuntimeError("read failed")
        writer = MagicMock()
        writer.wait_closed = AsyncMock()

        with patch(
            "agents.native_agent.asyncio.open_connection",
            new=AsyncMock(return_value=(reader, writer)),
        ):
            ready = await agent._probe_http("127.0.0.1", 8745, "/sse", expect_sse=True, timeout_s=0.5)

        self.assertFalse(ready)
        writer.close.assert_called_once()
        writer.wait_closed.assert_awaited_once()

    async def test_native_agent_probe_http_closes_writer_when_drain_raises(self):
        agent = NativeAgent()
        reader = AsyncMock()
        writer = MagicMock()
        writer.drain = AsyncMock(side_effect=RuntimeError("drain failed"))
        writer.wait_closed = AsyncMock()

        with patch(
            "agents.native_agent.asyncio.open_connection",
            new=AsyncMock(return_value=(reader, writer)),
        ):
            ready = await agent._probe_http("127.0.0.1", 8745, "/", expect_sse=False, timeout_s=0.5)

        self.assertFalse(ready)
        writer.close.assert_called_once()
        writer.wait_closed.assert_awaited_once()

    async def test_native_agent_probe_http_closes_writer_when_wait_closed_raises(self):
        agent = NativeAgent()
        reader = AsyncMock()
        reader.read = AsyncMock(return_value=b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n\r\n")

        class ClosingWriter:
            def __init__(self):
                self.close = MagicMock()
                self.wait_closed = AsyncMock(side_effect=RuntimeError("close failed"))

            def write(self, data):
                return None

            async def drain(self):
                return None

        writer = ClosingWriter()

        with patch(
            "agents.native_agent.asyncio.open_connection",
            new=AsyncMock(return_value=(reader, writer)),
        ):
            ready = await agent._probe_http("127.0.0.1", 8745, "/sse", expect_sse=True, timeout_s=0.5)

        self.assertTrue(ready)
        writer.close.assert_called_once()
        writer.wait_closed.assert_awaited_once()

    async def test_native_agent_returns_server_ready_error_without_runner_call(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".exe", delete=False) as temp_file:
            temp_file.write(b"MZ\x00native")
            file_path = temp_file.name

        fake_server_proc = self._make_server_proc(pid=9876, stderr_bytes=b"boot failed")

        try:
            with patch("agents.native_agent.print"), patch(
                "agents.native_agent.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=fake_server_proc),
            ), patch.object(
                NativeAgent,
                "_wait_for_http_ready",
                new=AsyncMock(return_value=False),
            ), patch("agents.native_agent.run_claude_code", new=AsyncMock()) as run_claude_code_mock, patch(
                "agents.native_agent.subprocess.run"
            ) as taskkill_mock:
                agent = NativeAgent()
                result = await agent.run_goose_analysis(file_path)

            self.assertEqual(
                result,
                f"Error: IDA MCP HTTP not ready on http://127.0.0.1:8745 within {agent.ida_startup_timeout_s:.0f}s. boot failed",
            )
            run_claude_code_mock.assert_not_awaited()
            fake_server_proc.stderr.read.assert_awaited_once_with(4096)
            taskkill_mock.assert_called_once()
        finally:
            os.unlink(file_path)

    async def test_native_agent_cleans_up_when_runner_raises(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".exe", delete=False) as temp_file:
            temp_file.write(b"MZ\x00native")
            file_path = temp_file.name

        fake_server_proc = self._make_server_proc(pid=2468)

        try:
            with patch("agents.native_agent.print"), patch(
                "agents.native_agent.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=fake_server_proc),
            ), patch.object(
                NativeAgent,
                "_wait_for_http_ready",
                new=AsyncMock(return_value=True),
            ), patch("agents.native_agent.asyncio.sleep", new=AsyncMock()), patch(
                "agents.native_agent.run_claude_code",
                new=AsyncMock(side_effect=RuntimeError("runner boom")),
            ) as run_claude_code_mock, patch("agents.native_agent.subprocess.run") as taskkill_mock:
                agent = NativeAgent()
                result = await agent.run_goose_analysis(file_path)

            self.assertEqual(result, "Claude Code execution error: runner boom")
            run_claude_code_mock.assert_awaited_once()
            taskkill_mock.assert_called_once()
        finally:
            os.unlink(file_path)

    async def test_native_agent_returns_missing_dependency_for_ida_startup_failure(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".exe", delete=False) as temp_file:
            temp_file.write(b"MZ\x00native")
            file_path = temp_file.name

        try:
            with patch("agents.native_agent.print"), patch(
                "agents.native_agent.asyncio.create_subprocess_exec",
                new=AsyncMock(side_effect=FileNotFoundError("idalib-mcp missing")),
            ):
                agent = NativeAgent()
                result = await agent.run_goose_analysis(file_path)

            self.assertEqual(
                result,
                f"Missing dependency while starting command ['uv', 'run', 'idalib-mcp', '--host', '127.0.0.1', '--port', '8745', {file_path!r}]: idalib-mcp missing",
            )
        finally:
            os.unlink(file_path)


class DotNetAgentRunnerIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_dotnet_agent_builds_prompt_from_decompiled_cs_context(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".exe", delete=False) as temp_file:
            temp_file.write(b"MZ\x00dotnet")
            file_path = temp_file.name

        with tempfile.TemporaryDirectory() as output_root:
            expected_hash = hashlib.sha256(b"MZ\x00dotnet").hexdigest()
            decompiled_dir = os.path.join(output_root, expected_hash)
            nested_dir = os.path.join(decompiled_dir, "Sub")
            os.makedirs(nested_dir, exist_ok=True)

            program_path = os.path.join(decompiled_dir, "Program.cs")
            injector_path = os.path.join(nested_dir, "ProcessInjector.cs")
            other_path = os.path.join(decompiled_dir, "Helpers.cs")
            ignored_path = os.path.join(decompiled_dir, "notes.txt")

            for path, content in (
                (program_path, "class Program {}"),
                (injector_path, "class ProcessInjector {}"),
                (other_path, "class Helpers {}"),
                (ignored_path, "ignore me"),
            ):
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)

            raw_report = "noise\n─── tool | ida ─────────────────────────\n**Start of Analysis**\nDotNet finding\n\n-1: Could not interpret tool use parameters nope\n\n**End of Analysis**\ntrailer"
            expected_hash = hashlib.sha256(b"MZ\x00dotnet").hexdigest()

            try:
                with patch("agents.dotnet_agent.print"), patch("agents.dotnet_agent.run_claude_code", new=AsyncMock(return_value=raw_report)) as run_claude_code_mock, patch.object(
                    DotNetAgent,
                    "run_dnspy_decompile",
                    new=AsyncMock(return_value=True),
                ):
                    agent = DotNetAgent()
                    agent.output_root = output_root
                    result = await agent.analyze(file_path)

                run_claude_code_mock.assert_awaited_once()
                instruction = run_claude_code_mock.await_args.args[0]
                self.assertIs(run_claude_code_mock.await_args.kwargs["config"], agent.config)
                self.assertIn(
                    f"Examine the decompiled C# source code under: {agent._to_workspace_rel_posix(decompiled_dir)}",
                    instruction,
                )
                self.assertIn("Files to read first:", instruction)
                self.assertIn(agent._to_workspace_rel_posix(program_path), instruction)
                self.assertIn(agent._to_workspace_rel_posix(injector_path), instruction)
                self.assertIn(agent._to_workspace_rel_posix(other_path), instruction)
                self.assertNotIn("notes.txt", instruction)
                self.assertIn("Identify the Entry Point and main execution flow", instruction)
                self.assertIn("sensitive strings, API imports (P/Invoke), or network activities", instruction)
                self.assertIn("Costura/Fody loaders", instruction)
                self.assertIn("NEVER try to execute any code", instruction)
                self.assertIn("Error: File cannot accessed.", instruction)

                self.assertEqual(result["file_name"], os.path.basename(file_path))
                self.assertEqual(result["file_hash"], expected_hash)
                self.assertEqual(result["source_directory"], os.path.join(output_root, expected_hash))
                self.assertEqual(
                    result["ai_analysis_report"],
                    "**Start of Analysis**\nDotNet finding\n\n**End of Analysis**",
                )
            finally:
                os.unlink(file_path)

    async def test_dotnet_agent_uses_placeholder_when_no_cs_files_exist(self):
        with tempfile.TemporaryDirectory() as decompiled_dir:
            with patch("agents.dotnet_agent.print"), patch("agents.dotnet_agent.run_claude_code", new=AsyncMock(return_value="**Start of Analysis**\nOK\n**End of Analysis**")) as run_claude_code_mock:
                agent = DotNetAgent()
                await agent.run_goose_analysis(decompiled_dir)

            run_claude_code_mock.assert_awaited_once()
            instruction = run_claude_code_mock.await_args.args[0]
            self.assertIn("- (no .cs files detected)", instruction)
            self.assertIn("Files to read first:", instruction)
            self.assertIn(
                f"Examine the decompiled C# source code under: {agent._to_workspace_rel_posix(decompiled_dir)}",
                instruction,
            )
            self.assertIs(run_claude_code_mock.await_args.kwargs["config"], agent.config)

    async def test_dotnet_agent_returns_error_when_decompilation_fails(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".exe", delete=False) as temp_file:
            temp_file.write(b"MZ\x00dotnet")
            file_path = temp_file.name

        try:
            with patch.object(DotNetAgent, "run_dnspy_decompile", new=AsyncMock(return_value=False)), patch(
                "agents.dotnet_agent.run_claude_code",
                new=AsyncMock(),
            ) as run_claude_code_mock:
                agent = DotNetAgent()
                result = await agent.analyze(file_path)

            self.assertEqual(result, {"error": "Decompilation failed"})
            run_claude_code_mock.assert_not_awaited()
        finally:
            os.unlink(file_path)

    async def test_dotnet_agent_prefers_interesting_cs_files(self):
        with tempfile.TemporaryDirectory() as decompiled_dir:
            nested_dir = os.path.join(decompiled_dir, "Deep")
            os.makedirs(nested_dir, exist_ok=True)

            interesting = os.path.join(nested_dir, "AssemblyLoader.cs")
            generic = os.path.join(decompiled_dir, "Utility.cs")
            another_generic = os.path.join(nested_dir, "Worker.cs")

            for path in (interesting, generic, another_generic):
                with open(path, "w", encoding="utf-8") as f:
                    f.write("class Sample {}")

            agent = DotNetAgent()
            selected = agent._pick_interesting_cs_files(decompiled_dir, limit=2)

            self.assertEqual(len(selected), 2)
            self.assertEqual(selected[0], agent._to_workspace_rel_posix(interesting))
            self.assertEqual(selected[1], min(
                agent._to_workspace_rel_posix(generic),
                agent._to_workspace_rel_posix(another_generic),
            ))

    async def test_dotnet_agent_run_dnspy_decompile_invokes_asyncio_subprocess(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".exe", delete=False) as temp_file:
            temp_file.write(b"MZ\x00dotnet")
            file_path = temp_file.name

        with tempfile.TemporaryDirectory() as output_root:
            output_dir = os.path.join(output_root, "hash")
            proc = AsyncMock()
            proc.communicate.return_value = (b"", b"")
            proc.returncode = 0

            try:
                with patch("agents.dotnet_agent.print"), patch("agents.dotnet_agent.asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)) as create_subprocess_mock, patch.object(
                    DotNetAgent,
                    "_resolve_executable",
                    return_value="C:/tools/dnspyc.exe",
                ):
                    agent = DotNetAgent()
                    agent.output_root = output_root
                    result = await agent.run_dnspy_decompile(file_path, output_dir)

                self.assertTrue(result)
                create_subprocess_mock.assert_awaited_once_with(
                    "C:/tools/dnspyc.exe",
                    "-o",
                    agent._abs_path(output_dir),
                    agent._abs_path(file_path),
                    stdout=__import__("asyncio").subprocess.PIPE,
                    stderr=__import__("asyncio").subprocess.PIPE,
                )
            finally:
                os.unlink(file_path)

    async def test_script_agent_falls_back_to_existing_pyasm_files_when_pycdas_creates_none(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".py", delete=False) as temp_file:
            temp_file.write(b"print('hello')\n")
            file_path = temp_file.name

        with tempfile.TemporaryDirectory() as extract_dir:
            nested_dir = os.path.join(extract_dir, "pkg")
            os.makedirs(nested_dir, exist_ok=True)
            existing_pyasm_path = os.path.join(nested_dir, "payload.pyc.pyasm")

            with open(existing_pyasm_path, "w", encoding="utf-8") as f:
                f.write("existing disassembly")

            try:
                with patch("agents.script_agent.run_claude_code", new=AsyncMock(return_value="**Start of Analysis**\nOK\n**End of Analysis**")), patch.object(
                    ScriptAgent,
                    "_ensure_output_dir",
                    return_value=extract_dir,
                ), patch.object(
                    ScriptAgent,
                    "_extract_pyinstaller",
                    new=AsyncMock(return_value=(extract_dir, [existing_pyasm_path])),
                ), patch.object(
                    ScriptAgent,
                    "_disassemble_with_pycdas",
                    new=AsyncMock(return_value=[]),
                ):
                    agent = ScriptAgent()
                    result = await agent.analyze(file_path)

                self.assertEqual(result["extract_dir"], extract_dir)
                self.assertEqual(result["pyasm_files"], [agent._to_workspace_rel_posix(existing_pyasm_path)])
            finally:
                os.unlink(file_path)

    async def test_script_agent_returns_error_for_missing_file(self):
        agent = ScriptAgent()
        result = await agent.analyze("C:/definitely/missing/script.py")
        self.assertEqual(result, {"error": "File does not exist"})

    async def test_script_agent_returns_error_for_unreadable_file(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".py", delete=False) as temp_file:
            temp_file.write(b"print('hello')\n")
            file_path = temp_file.name

        original_access = os.access

        try:
            os.chmod(file_path, 0)
            with patch("agents.script_agent.os.access", side_effect=lambda path, mode: False if path == file_path else original_access(path, mode)):
                agent = ScriptAgent()
                result = await agent.analyze(file_path)
            self.assertEqual(result, {"error": "File is not readable"})
        finally:
            os.chmod(file_path, stat.S_IWRITE | stat.S_IREAD)
            os.unlink(file_path)


if __name__ == "__main__":
    unittest.main()
