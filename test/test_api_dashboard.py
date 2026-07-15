import asyncio
import io
import os
import tempfile
import unittest
from unittest.mock import patch

from starlette.datastructures import UploadFile

import api
from core.task_runtime import bind_process_scope, _finalize_process, _register_process


class ApiDashboardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        api.RUNS.clear()
        api.TASK_SESSIONS.clear()
        api.RUN_TASK_INDEX.clear()
        api.TASK_OUTPUTS.clear()
        api.RUN_WORKERS.clear()
        api.reset_process_runtime()

    def tearDown(self):
        api.RUNS.clear()
        api.TASK_SESSIONS.clear()
        api.RUN_TASK_INDEX.clear()
        api.TASK_OUTPUTS.clear()
        api.RUN_WORKERS.clear()
        api.reset_process_runtime()

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
                tasks_snapshot = await api.get_run_tasks(response["run_id"])

            self.assertEqual(snapshot["run_id"], response["run_id"])
            self.assertEqual(snapshot["status"], "completed")
            self.assertEqual(snapshot["source"], "path")
            self.assertEqual(snapshot["file_name"], os.path.basename(file_path))
            self.assertEqual(snapshot["result"]["file_path"], os.path.abspath(file_path))
            self.assertEqual([event["stage"] for event in snapshot["pipeline_log"]], ["request", "response"])
            self.assertEqual(snapshot["pipeline_log"][0]["display_stage"], "Request")
            self.assertEqual(snapshot["pipeline_log"][1]["display_stage"], "Complete")
            self.assertIsNotNone(snapshot["finished_at"])
            self.assertEqual(tasks_snapshot["run_id"], response["run_id"])
            self.assertEqual(tasks_snapshot["status"], "completed")
            self.assertGreaterEqual(len(tasks_snapshot["tasks"]), 1)
            self.assertEqual(tasks_snapshot["tasks"][0]["run_id"], response["run_id"])
            self.assertEqual(tasks_snapshot["tasks"][0]["status"], "completed")
            self.assertEqual(tasks_snapshot["tasks"][0]["terminal_state"], "success")
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
            tasks_snapshot = await api.get_run_tasks(response["run_id"])

        self.assertEqual(snapshot["run_id"], response["run_id"])
        self.assertEqual(snapshot["status"], "completed")
        self.assertEqual(snapshot["source"], "upload")
        self.assertEqual(snapshot["file_name"], "sample.exe")
        self.assertEqual(snapshot["result"]["detected_type"], "NATIVE")
        self.assertEqual([event["stage"] for event in snapshot["pipeline_log"]], ["request", "response"])
        self.assertIsNotNone(snapshot["finished_at"])
        self.assertEqual(tasks_snapshot["status"], "completed")
        self.assertTrue(tasks_snapshot["tasks"])
        self.assertEqual(tasks_snapshot["tasks"][0]["executor_kind"], "local")
        self.assertTrue(upload.file.closed)

    async def test_get_run_tasks_returns_404_for_missing_run(self):
        with self.assertRaises(api.HTTPException) as context:
            await api.get_run_tasks("missing-run")

        self.assertEqual(context.exception.status_code, 404)

    async def test_get_run_task_output_returns_404_for_missing_run(self):
        with self.assertRaises(api.HTTPException) as context:
            await api.get_run_task_output("missing-run", "task-1")

        self.assertEqual(context.exception.status_code, 404)

    async def test_get_run_task_output_returns_404_for_missing_task(self):
        api._create_run_record(run_id="run-404", source="path", file_name="sample.exe")

        with self.assertRaises(api.HTTPException) as context:
            await api.get_run_task_output("run-404", "missing-task")

        self.assertEqual(context.exception.status_code, 404)

    async def test_get_run_processes_returns_404_for_missing_run(self):
        with self.assertRaises(api.HTTPException) as context:
            await api.get_run_processes("missing-run")

        self.assertEqual(context.exception.status_code, 404)

    async def test_get_run_processes_returns_registered_runtime_processes(self):
        api._create_run_record(run_id="run-proc", source="path", file_name="sample.exe")

        with bind_process_scope(run_id="run-proc", task_id="task-1", session_id="session-1", executor_kind="local", stage_key="identify", title="Detect file type"):
            process_id = _register_process(["diec.exe", "sample.exe"], pid=4321, cwd="C:/tmp")
        _finalize_process(process_id, returncode=0)

        snapshot = await api.get_run_processes("run-proc")

        self.assertEqual(snapshot["run_id"], "run-proc")
        self.assertEqual(snapshot["status"], "queued")
        self.assertEqual(len(snapshot["processes"]), 1)
        process = snapshot["processes"][0]
        self.assertEqual(process["pid"], 4321)
        self.assertEqual(process["task_id"], "task-1")
        self.assertEqual(process["session_id"], "session-1")
        self.assertEqual(process["stage_key"], "identify")
        self.assertEqual(process["title"], "Detect file type")
        self.assertEqual(process["command_text"], "diec.exe sample.exe")
        self.assertEqual(process["status"], "completed")
        self.assertEqual(process["return_code"], 0)

    async def test_stop_run_cancels_worker_and_marks_run_cancelled(self):
        run = api._create_run_record(run_id="run-stop", source="path", file_name="sample.exe")
        worker_cancelled = asyncio.Event()
        worker_released = asyncio.Event()

        async def worker():
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                worker_cancelled.set()
                raise
            finally:
                worker_released.set()

        task = asyncio.create_task(worker())
        api.RUN_WORKERS["run-stop"] = task
        await asyncio.sleep(0)

        with bind_process_scope(run_id="run-stop", task_id=run["root_task_id"], session_id=run["root_session_id"], executor_kind="local", stage_key="agent", title="Run coarse analysis"):
            process_id = _register_process(["python", "analyze.py"], pid=9876, cwd="C:/tmp")

        result = await api.stop_run("run-stop")
        await asyncio.wait_for(worker_cancelled.wait(), timeout=0.2)
        await asyncio.wait_for(worker_released.wait(), timeout=0.2)

        self.assertEqual(result["run_id"], "run-stop")
        self.assertEqual(result["status"], "cancelled")
        self.assertFalse(api.RUN_WORKERS.get("run-stop"))
        snapshot = await api.get_run("run-stop")
        self.assertEqual(snapshot["status"], "cancelled")
        self.assertEqual(snapshot["error"], "Run cancelled by user")
        processes = await api.get_run_processes("run-stop")
        self.assertEqual(processes["processes"][0]["process_id"], process_id)
        self.assertEqual(processes["processes"][0]["status"], "cancelled")
        self.assertEqual(processes["processes"][0]["error"], "Run cancelled by user")

    async def test_root_task_output_contains_final_run_result(self):
        run = api._create_run_record(run_id="run-root", source="path", file_name="sample.exe")
        api._merge_task_output(
            run["root_task_id"],
            {
                "output_kind": "run_result",
                "result": {"ai_analysis_report": "ok"},
                "status": "completed",
                "terminal_state": "success",
                "summary": "Analysis completed",
            },
        )

        detail = await api.get_run_task_output("run-root", run["root_task_id"])

        self.assertEqual(detail["run_id"], "run-root")
        self.assertEqual(detail["task"]["task_id"], run["root_task_id"])
        self.assertEqual(detail["output"]["output_kind"], "run_result")
        self.assertEqual(detail["output"]["result"], {"ai_analysis_report": "ok"})
        self.assertEqual(detail["output"]["terminal_state"], "success")

    async def test_nested_task_output_tracks_events_and_payload(self):
        run = api._create_run_record(run_id="run-detail", source="path", file_name="sample.exe")

        api._sync_task_from_event(
            run_id="run-detail",
            event={
                "stage": "script_agent.claude",
                "state": "started",
                "message": "Starting Claude Code script analysis",
                "timestamp": "2026-07-07T00:00:00+00:00",
                "data": {
                    "task_id": "task-child",
                    "session_id": "session-child",
                    "parent_task_id": run["root_task_id"],
                    "executor_kind": "claude",
                },
            },
        )
        api._merge_task_output(
            "task-child",
            {
                "output_kind": "claude_command",
                "result": {"stdout": "analysis output", "exit_code": 0},
            },
        )
        api._sync_task_from_event(
            run_id="run-detail",
            event={
                "stage": "script_agent.claude",
                "state": "completed",
                "message": "Claude Code script analysis completed",
                "timestamp": "2026-07-07T00:01:00+00:00",
                "data": {
                    "task_id": "task-child",
                    "session_id": "session-child",
                    "parent_task_id": run["root_task_id"],
                    "executor_kind": "claude",
                },
            },
        )

        detail = await api.get_run_task_output("run-detail", "task-child")

        self.assertEqual(detail["task"]["status"], "completed")
        self.assertEqual(detail["output"]["output_kind"], "claude_command")
        self.assertEqual(detail["output"]["result"]["stdout"], "analysis output")
        self.assertEqual(detail["output"]["terminal_state"], "success")
        self.assertEqual(len(detail["output"]["events"]), 2)
        self.assertEqual(detail["output"]["events"][0]["state"], "started")
        self.assertEqual(detail["output"]["events"][1]["state"], "completed")

    async def test_run_task_output_snapshot_can_show_live_partial_stdout(self):
        run = api._create_run_record(run_id="run-live", source="path", file_name="sample.exe")
        api._sync_task_from_event(
            run_id="run-live",
            event={
                "stage": "claude_runner",
                "state": "started",
                "message": "Launching Claude Code command",
                "timestamp": "2026-07-07T00:00:00+00:00",
                "data": {
                    "task_id": "task-live",
                    "session_id": "session-live",
                    "parent_task_id": run["root_task_id"],
                    "executor_kind": "claude",
                },
            },
        )
        api._merge_task_output(
            "task-live",
            {
                "output_kind": "claude_command",
                "status": "processing",
                "summary": "Launching Claude Code command",
                "result": {"stdout": "partial output", "stderr": ""},
            },
        )

        detail = await api.get_run_task_output("run-live", "task-live")

        self.assertEqual(detail["task"]["status"], "processing")
        self.assertEqual(detail["output"]["result"]["stdout"], "partial output")
        self.assertEqual(detail["output"]["status"], "processing")

    async def test_run_tasks_projection_tracks_root_task_identity(self):
        run = api._create_run_record(run_id="run-123", source="path", file_name="sample.exe")

        snapshot = await api.get_run_tasks("run-123")

        self.assertEqual(snapshot["run_id"], "run-123")
        self.assertEqual(snapshot["status"], "queued")
        self.assertEqual(len(snapshot["tasks"]), 1)
        task = snapshot["tasks"][0]
        self.assertEqual(task["task_id"], run["root_task_id"])
        self.assertEqual(task["session_id"], run["root_session_id"])
        self.assertEqual(task["stage_key"], "request")
        self.assertEqual(task["status"], "pending")
        self.assertEqual(task["terminal_state"], None)
        self.assertEqual(task["metadata"]["source"], "path")
        self.assertEqual(task["metadata"]["file_name"], "sample.exe")
        self.assertEqual(task["title"], "Run request")

    async def test_run_tasks_projection_tracks_nested_child_task_identity(self):
        run = api._create_run_record(run_id="run-456", source="path", file_name="sample.exe")

        api._sync_task_from_event(
            run_id="run-456",
            event={
                "stage": "script_agent.claude",
                "state": "started",
                "message": "Starting Claude Code script analysis",
                "timestamp": "2026-07-07T00:00:00+00:00",
                "data": {
                    "task_id": "task-child",
                    "session_id": "session-child",
                    "parent_task_id": run["root_task_id"],
                    "executor_kind": "claude",
                },
            },
        )
        api._sync_task_from_event(
            run_id="run-456",
            event={
                "stage": "script_agent.claude",
                "state": "completed",
                "message": "Claude Code script analysis completed",
                "timestamp": "2026-07-07T00:01:00+00:00",
                "data": {
                    "task_id": "task-child",
                    "session_id": "session-child",
                    "parent_task_id": run["root_task_id"],
                    "executor_kind": "claude",
                    "artifact_id": "artifact-1",
                },
            },
        )

        snapshot = await api.get_run_tasks("run-456")

        self.assertEqual(len(snapshot["tasks"]), 2)
        child_task = next(task for task in snapshot["tasks"] if task["task_id"] == "task-child")
        self.assertEqual(child_task["session_id"], "session-child")
        self.assertEqual(child_task["parent_task_id"], run["root_task_id"])
        self.assertEqual(child_task["stage_key"], "script_agent.claude")
        self.assertEqual(child_task["executor_kind"], "claude")
        self.assertEqual(child_task["status"], "completed")
        self.assertEqual(child_task["terminal_state"], "success")
        self.assertEqual(child_task["artifact_id"], "artifact-1")
        self.assertEqual(child_task["summary"], "Claude Code script analysis completed")
        self.assertEqual(child_task["started_at"], "2026-07-07T00:00:00+00:00")
        self.assertEqual(child_task["finished_at"], "2026-07-07T00:01:00+00:00")
        self.assertEqual(snapshot["status"], "running")

    async def test_run_tasks_projection_keeps_local_executor_for_nested_prep_task(self):
        run = api._create_run_record(run_id="run-789", source="path", file_name="sample.exe")

        api._sync_task_from_event(
            run_id="run-789",
            event={
                "stage": "script_agent.extract",
                "state": "started",
                "message": "Starting PyInstaller extraction",
                "timestamp": "2026-07-07T00:00:00+00:00",
                "data": {
                    "task_id": "task-extract",
                    "session_id": "session-extract",
                    "parent_task_id": run["root_task_id"],
                    "executor_kind": "local",
                },
            },
        )

        snapshot = await api.get_run_tasks("run-789")

        child_task = next(task for task in snapshot["tasks"] if task["task_id"] == "task-extract")
        self.assertEqual(child_task["stage_key"], "script_agent.extract")
        self.assertEqual(child_task["executor_kind"], "local")
        self.assertEqual(child_task["status"], "processing")
        self.assertIsNone(child_task["terminal_state"])
        self.assertEqual(snapshot["status"], "running")

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
        self.assertIn("Task board", index_html)
        self.assertIn("Pending", index_html)
        self.assertIn("Processing", index_html)
        self.assertIn("Completed", index_html)
        self.assertIn("Related processes", index_html)
        self.assertIn('id="processPanel"', index_html)
        self.assertIn("Open a run to observe related OS processes.", index_html)
        self.assertIn('id="stopRunButton"', index_html)
        self.assertIn("Task output", index_html)
        self.assertIn('id="pendingTasks"', index_html)
        self.assertIn('id="processingTasks"', index_html)
        self.assertIn('id="completedTasks"', index_html)
        self.assertIn('id="taskOutput"', index_html)
        self.assertIn('id="taskOutputModal"', index_html)
        self.assertIn('id="taskOutputClose"', index_html)
        self.assertIn("modal-overlay", index_html)
        self.assertIn("View output", index_html)
        self.assertNotIn("<h2>Task output</h2>", index_html)
        self.assertIn("/runs/upload", index_html)
        self.assertIn("/runs/${encodeURIComponent(runId)}/tasks", index_html)
        self.assertIn("/runs/${encodeURIComponent(runId)}/tasks/${encodeURIComponent(taskId)}", index_html)
        self.assertIn("/runs/${encodeURIComponent(runId)}/processes", index_html)
        self.assertIn("/runs/${encodeURIComponent(currentRunId)}/stop", index_html)
        self.assertIn("stopCurrentRun", index_html)
        self.assertIn("HyperAgent Workflow Dashboard", run_html)
        self.assertIn('value="run-123"', run_html)
        self.assertIn("/runs/${encodeURIComponent(runId)}", run_html)
        self.assertIn("/runs/${encodeURIComponent(runId)}/tasks", run_html)
        self.assertIn("/runs/${encodeURIComponent(runId)}/tasks/${encodeURIComponent(taskId)}", run_html)
        self.assertIn("/runs/${encodeURIComponent(runId)}/processes", run_html)
        self.assertIn("/runs/${encodeURIComponent(currentRunId)}/stop", run_html)
        self.assertIn("stopCurrentRun", run_html)


if __name__ == "__main__":
    unittest.main()
