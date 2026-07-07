import asyncio
import io
import os
import tempfile
import unittest
from unittest.mock import patch

from starlette.datastructures import UploadFile

import api


class ApiDashboardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        api.RUNS.clear()

    def tearDown(self):
        api.RUNS.clear()

    async def _fake_analyze(self, target, run_id=None, pipeline_logger=None):
        if pipeline_logger:
            pipeline_logger.log("request", "started", "Analysis request accepted", file_path=os.path.abspath(target))
            pipeline_logger.log("response", "completed", "Final response assembled", file_path=os.path.abspath(target), target_stage="Complete")
        return {
            "run_id": run_id,
            "file_path": os.path.abspath(target),
            "detected_type": "NATIVE",
            "die": {"language": "c++"},
            "result": {"ai_analysis_report": "ok"},
            "next_stage_results": [],
            "pipeline_log": pipeline_logger.snapshot() if pipeline_logger else [],
            "artifacts": [],
            "findings": [],
            "iocs": [],
            "verdict": None,
            "final_report_markdown": None,
        }

    async def test_start_run_path_returns_queued_run_and_snapshot_completes(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".exe", delete=False) as temp_file:
            temp_file.write(b"MZ")
            file_path = temp_file.name

        try:
            with patch.object(api.orchestrator, "analyze", side_effect=self._fake_analyze):
                response = await api.start_run_path(api.AnalyzePathRequest(file_path=file_path))
                self.assertEqual(response["status"], "queued")
                self.assertIn(response["run_id"], api.RUNS)
                await asyncio.sleep(0.01)
                snapshot = await api.get_run(response["run_id"])

            self.assertEqual(snapshot["run_id"], response["run_id"])
            self.assertEqual(snapshot["status"], "completed")
            self.assertEqual(snapshot["source"], "path")
            self.assertEqual(snapshot["file_name"], os.path.basename(file_path))
            self.assertEqual(snapshot["result"]["file_path"], os.path.abspath(file_path))
            self.assertEqual([event["stage"] for event in snapshot["pipeline_log"]], ["request", "response"])
            self.assertEqual(snapshot["pipeline_log"][0]["display_stage"], "Request")
            self.assertEqual(snapshot["pipeline_log"][1]["display_stage"], "Complete")
            self.assertIsNotNone(snapshot["finished_at"])
        finally:
            os.unlink(file_path)

    async def test_start_run_upload_returns_queued_run_and_snapshot_completes(self):
        upload = UploadFile(file=io.BytesIO(b"MZ"), filename="sample.exe")

        with patch.object(api.orchestrator, "analyze", side_effect=self._fake_analyze):
            response = await api.start_run_upload(file=upload, keep_file=False)
            self.assertEqual(response["status"], "queued")
            self.assertEqual(response["run_id"], response["upload_id"])
            self.assertIn(response["run_id"], api.RUNS)
            self.assertIsNone(response["saved_path"])
            await asyncio.sleep(0.01)
            snapshot = await api.get_run(response["run_id"])

        self.assertEqual(snapshot["run_id"], response["run_id"])
        self.assertEqual(snapshot["status"], "completed")
        self.assertEqual(snapshot["source"], "upload")
        self.assertEqual(snapshot["file_name"], "sample.exe")
        self.assertEqual(snapshot["result"]["detected_type"], "NATIVE")
        self.assertEqual([event["stage"] for event in snapshot["pipeline_log"]], ["request", "response"])
        self.assertIsNotNone(snapshot["finished_at"])
        self.assertTrue(upload.file.closed)

    async def test_analyze_upload_preserves_sync_wrapper_fields(self):
        upload = UploadFile(file=io.BytesIO(b"MZ"), filename="sample.exe")

        with patch.object(api.orchestrator, "analyze", side_effect=self._fake_analyze):
            response = await api.analyze_upload(file=upload, keep_file=False)

        self.assertEqual(response["run_id"], response["upload_id"])
        self.assertIsNone(response["saved_path"])
        self.assertEqual(response["detected_type"], "NATIVE")
        self.assertEqual(response["result"], {"ai_analysis_report": "ok"})
        self.assertTrue(upload.file.closed)

    async def test_dashboard_routes_return_html_shell(self):
        index_response = await api.dashboard_index()
        run_response = await api.dashboard_run("run-123")

        index_html = index_response.body.decode("utf-8")
        run_html = run_response.body.decode("utf-8")

        self.assertIn("HyperAgent Workflow Dashboard", index_html)
        self.assertIn("Open run", index_html)
        self.assertIn("Upload run", index_html)
        self.assertIn("Choose file", index_html)
        self.assertIn('id="uploadFileInput"', index_html)
        self.assertIn('id="chooseFileButton"', index_html)
        self.assertIn('class="button-like secondary-button file-picker"', index_html)
        self.assertIn('id="selectedFileName"', index_html)
        self.assertIn("No file selected.", index_html)
        self.assertIn("/runs/upload", index_html)
        self.assertIn("HyperAgent Workflow Dashboard", run_html)
        self.assertIn('value="run-123"', run_html)
        self.assertIn("/runs/${encodeURIComponent(runId)}", run_html)


if __name__ == "__main__":
    unittest.main()
