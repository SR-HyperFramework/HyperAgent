import io
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from starlette.datastructures import UploadFile

import api
from core.die_handler import AnalysisType
from main import HyperAgentOrchestrator


class OrchestratorPhase0ContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_orchestrator_preserves_legacy_response_envelope(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".exe", delete=False) as temp_file:
            temp_file.write(b"MZ")
            file_path = temp_file.name

        try:
            expected_result = {
                "file_name": os.path.basename(file_path),
                "file_hash": "abc123",
                "ai_analysis_report": "**Start of Analysis**\nOK\n**End of Analysis**",
            }
            agent = Mock()
            agent.analyze = AsyncMock(return_value=expected_result)

            orchestrator = HyperAgentOrchestrator()
            orchestrator.die_handler = Mock()
            orchestrator.die_handler.identify.return_value = ({"language": "c++"}, AnalysisType.NATIVE)

            with patch("main.NativeAgent", return_value=agent):
                result = await orchestrator.analyze(file_path, run_id="run-123")

            self.assertEqual(
                set(result.keys()),
                {
                    "run_id",
                    "file_path",
                    "detected_type",
                    "die",
                    "result",
                    "next_stage_results",
                    "pipeline_log",
                    "artifacts",
                    "findings",
                    "iocs",
                    "verdict",
                    "final_report_markdown",
                },
            )
            self.assertEqual(result["run_id"], "run-123")
            self.assertEqual(result["file_path"], os.path.abspath(file_path))
            self.assertEqual(result["detected_type"], "NATIVE")
            self.assertEqual(result["die"], {"language": "c++"})
            self.assertEqual(result["result"], expected_result)
            self.assertEqual(result["next_stage_results"], [])
            self.assertIsInstance(result["pipeline_log"], list)
            self.assertGreater(len(result["pipeline_log"]), 0)
            first_event = result["pipeline_log"][0]
            self.assertTrue({"run_id", "timestamp", "stage", "state", "message"}.issubset(first_event.keys()))
            self.assertIn("sequence", first_event)
            self.assertIn("status_label", first_event)
            self.assertIn("display_stage", first_event)
            self.assertEqual(result["artifacts"], [])
            self.assertEqual(result["findings"], [])
            self.assertEqual(result["iocs"], [])
            self.assertIsNone(result["verdict"])
            self.assertIsNone(result["final_report_markdown"])
        finally:
            os.unlink(file_path)


class ApiPhase0ContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_analyze_path_only_adds_run_id_to_orchestrator_payload(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".exe", delete=False) as temp_file:
            temp_file.write(b"MZ")
            file_path = temp_file.name

        base_result = {
            "file_path": os.path.abspath(file_path),
            "detected_type": "NATIVE",
            "die": {"language": "c++"},
            "result": {"ai_analysis_report": "ok"},
            "next_stage_results": [],
            "pipeline_log": [],
            "artifacts": [],
            "findings": [],
            "iocs": [],
            "verdict": None,
            "final_report_markdown": None,
        }

        try:
            with patch.object(api.orchestrator, "analyze", new=AsyncMock(return_value=dict(base_result))):
                response = await api.analyze_path(api.AnalyzePathRequest(file_path=file_path))

            self.assertEqual(
                set(response.keys()),
                {
                    "run_id",
                    "file_path",
                    "detected_type",
                    "die",
                    "result",
                    "next_stage_results",
                    "pipeline_log",
                    "artifacts",
                    "findings",
                    "iocs",
                    "verdict",
                    "final_report_markdown",
                },
            )
            self.assertEqual(response["file_path"], base_result["file_path"])
            self.assertEqual(response["detected_type"], "NATIVE")
            self.assertEqual(response["die"], {"language": "c++"})
            self.assertEqual(response["result"], {"ai_analysis_report": "ok"})
            self.assertEqual(response["artifacts"], [])
            self.assertEqual(response["findings"], [])
            self.assertEqual(response["iocs"], [])
            self.assertIsNone(response["verdict"])
            self.assertIsNone(response["final_report_markdown"])
            self.assertTrue(response["run_id"])
        finally:
            os.unlink(file_path)

    async def test_analyze_upload_only_adds_upload_wrapper_fields(self):
        upload = UploadFile(file=io.BytesIO(b"MZ"), filename="sample.exe")
        base_result = {
            "file_path": "C:/analysis/sample.exe",
            "detected_type": "NATIVE",
            "die": {"language": "c++"},
            "result": {"ai_analysis_report": "ok"},
            "next_stage_results": [],
            "pipeline_log": [],
            "artifacts": [],
            "findings": [],
            "iocs": [],
            "verdict": None,
            "final_report_markdown": None,
        }

        try:
            with patch.object(api.orchestrator, "analyze", new=AsyncMock(return_value=dict(base_result))):
                response = await api.analyze_upload(file=upload, keep_file=False)

            self.assertEqual(
                set(response.keys()),
                {
                    "upload_id",
                    "run_id",
                    "saved_path",
                    "file_path",
                    "detected_type",
                    "die",
                    "result",
                    "next_stage_results",
                    "pipeline_log",
                    "artifacts",
                    "findings",
                    "iocs",
                    "verdict",
                    "final_report_markdown",
                },
            )
            self.assertEqual(response["run_id"], response["upload_id"])
            self.assertIsNone(response["saved_path"])
            self.assertEqual(response["file_path"], base_result["file_path"])
            self.assertEqual(response["result"], {"ai_analysis_report": "ok"})
            self.assertEqual(response["artifacts"], [])
            self.assertEqual(response["findings"], [])
            self.assertEqual(response["iocs"], [])
            self.assertIsNone(response["verdict"])
            self.assertIsNone(response["final_report_markdown"])
        finally:
            await upload.close()


if __name__ == "__main__":
    unittest.main()
