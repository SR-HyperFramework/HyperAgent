import hashlib
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from agents.dotnet_agent import DotNetAgent
from agents.file_classifier_agent import FileClassification, FileClassifierAgent
from agents.native_agent import NativeAgent
from agents.python_bytecode_prep_agent import PythonBytecodePrepAgent
from core.die_handler import AnalysisType


class FileClassifierAgentTests(unittest.TestCase):
    def test_analyze_wraps_die_handler_identify(self):
        die_handler = Mock()
        die_handler.identify.return_value = ({"compiler": "msvc"}, AnalysisType.NATIVE)

        agent = FileClassifierAgent(die_handler=die_handler)
        result = agent.analyze("C:/sample.exe")

        self.assertEqual(result, FileClassification(die_data={"compiler": "msvc"}, analysis_type=AnalysisType.NATIVE))
        die_handler.identify.assert_called_once_with("C:/sample.exe")


class DotNetPrepDelegationTests(unittest.IsolatedAsyncioTestCase):
    async def test_dotnet_agent_prepares_source_directory_via_prep_agent(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".exe", delete=False) as temp_file:
            temp_file.write(b"MZ\x00dotnet")
            file_path = temp_file.name

        try:
            agent = DotNetAgent()
            file_hash = hashlib.sha256(b"MZ\x00dotnet").hexdigest()
            source_directory = os.path.join(agent.output_root, file_hash)

            with patch.object(DotNetAgent, "run_de4dot", new=AsyncMock(return_value=file_path)) as run_de4dot_mock, patch.object(
                DotNetAgent,
                "run_dnspy_decompile",
                new=AsyncMock(return_value=True),
            ) as run_dnspy_mock, patch.object(
                DotNetAgent,
                "_pick_interesting_cs_files",
                return_value=["Program.cs"],
            ) as pick_mock:
                prep = await agent._prepare_source_directory(file_path, file_hash)

            self.assertTrue(prep.decompiled)
            self.assertEqual(prep.target_file, file_path)
            self.assertEqual(prep.cleaned_file, None)
            self.assertEqual(prep.source_directory, source_directory)
            self.assertEqual(prep.key_files, ["Program.cs"])
            run_de4dot_mock.assert_awaited_once()
            run_dnspy_mock.assert_awaited_once_with(file_path, source_directory, pipeline_logger=None)
            pick_mock.assert_called_once_with(source_directory, limit=15)
        finally:
            os.unlink(file_path)


class PythonPrepDelegationTests(unittest.IsolatedAsyncioTestCase):
    async def test_prepare_returns_existing_pyasm_when_pycdas_creates_none(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".py", delete=False) as temp_file:
            temp_file.write(b"print('hello')\n")
            file_path = temp_file.name

        with tempfile.TemporaryDirectory() as output_dir:
            extract_dir = os.path.join(output_dir, "sample_extracted")
            nested_dir = os.path.join(extract_dir, "pkg")
            os.makedirs(nested_dir, exist_ok=True)
            existing_pyasm = os.path.join(nested_dir, "payload.pyc.pyasm")
            with open(existing_pyasm, "w", encoding="utf-8") as f:
                f.write("existing")

            try:
                agent = PythonBytecodePrepAgent(config={}, repo_root=os.path.dirname(file_path))
                prep = await agent.prepare(
                    file_path,
                    output_dir,
                    extract_pyinstaller=AsyncMock(return_value=(extract_dir, [existing_pyasm])),
                    disassemble_with_pycdas=AsyncMock(return_value=[]),
                )

                self.assertEqual(prep.extract_dir, extract_dir)
                self.assertEqual(prep.pyasm_files, [existing_pyasm])
                self.assertIn("payload.pyc.pyasm", prep.priority_pyasm_files[0])
            finally:
                os.unlink(file_path)


class NativePrepDelegationTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_agent_uses_prep_instruction_contract(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".exe", delete=False) as temp_file:
            temp_file.write(b"MZ\x00native")
            file_path = temp_file.name

        try:
            with patch("agents.native_agent.print"), patch("agents.native_agent.run_claude_code", new=AsyncMock(return_value="ok")) as run_claude_code_mock:
                agent = NativeAgent()
                prep = await agent._prepare_native_target(file_path)
                result = await agent.run_goose_analysis(file_path)

            self.assertEqual(result, "ok")
            self.assertEqual(prep.instruction, f"/hyperagent-malware-analyze @{os.path.abspath(file_path)}")
            run_claude_code_mock.assert_awaited_once_with(
                prep.instruction,
                config=agent.config,
                pipeline_logger=None,
            )
        finally:
            os.unlink(file_path)


if __name__ == "__main__":
    unittest.main()
