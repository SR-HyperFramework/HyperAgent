import unittest

from core.artifact_registry import ArtifactRegistry
from core.finding_store import FindingStore
from core.output_normalizer import build_public_run_summary, normalize_agent_result
from core.pipeline_logger import PipelineLogger
from core.result_models import AgentResult, ArtifactNode, Finding, RunContext, TaskSession, TaskStatus
from core.task_runtime import create_child_task_scope, executor_kind_for_stage


class ResultModelTests(unittest.TestCase):
    def test_task_session_defaults_to_pending_local_execution(self):
        task = TaskSession(run_id="run-1", stage_key="identify", title="Identify file")

        self.assertEqual(task.run_id, "run-1")
        self.assertEqual(task.stage_key, "identify")
        self.assertEqual(task.title, "Identify file")
        self.assertEqual(task.status, TaskStatus.PENDING)
        self.assertIsNone(task.terminal_state)
        self.assertEqual(task.executor_kind, "local")
        self.assertTrue(task.task_id)
        self.assertTrue(task.session_id)

    def test_run_context_can_carry_task_scope(self):
        context = RunContext(
            run_id="run-1",
            root_file_path="C:/sample.exe",
            task_id="task-1",
            session_id="session-1",
            parent_task_id="task-0",
            executor_kind="claude",
        )

        self.assertEqual(context.task_id, "task-1")
        self.assertEqual(context.session_id, "session-1")
        self.assertEqual(context.parent_task_id, "task-0")
        self.assertEqual(context.executor_kind, "claude")

    def test_pipeline_logger_can_bind_task_scope_without_breaking_event_shape(self):
        logger = PipelineLogger(run_id="run-1")
        logger.bind_task(task_id="task-1", session_id="session-1", parent_task_id="task-0", executor_kind="local")

        event = logger.log("identify", "started", "Detecting file type")

        self.assertEqual(event["run_id"], "run-1")
        self.assertEqual(event["stage"], "identify")
        self.assertEqual(event["state"], "started")
        self.assertEqual(event["status_label"], "started")
        self.assertEqual(event["display_stage"], "Identify")
        self.assertEqual(
            event["data"],
            {
                "task_id": "task-1",
                "session_id": "session-1",
                "parent_task_id": "task-0",
                "executor_kind": "local",
            },
        )

    def test_pipeline_logger_child_inherits_and_overrides_task_scope(self):
        logger = PipelineLogger(run_id="run-1", task_id="task-1", session_id="session-1", executor_kind="local")

        child = logger.child(task_id="task-2", parent_task_id="task-1", executor_kind="claude")
        event = child.log("agent", "started", "Agent analysis started")

        self.assertEqual(event["data"]["task_id"], "task-2")
        self.assertEqual(event["data"]["session_id"], "session-1")
        self.assertEqual(event["data"]["parent_task_id"], "task-1")
        self.assertEqual(event["data"]["executor_kind"], "claude")

    def test_pipeline_logger_tracks_task_outputs_and_events(self):
        logger = PipelineLogger(run_id="run-1", task_id="task-1", session_id="session-1", parent_task_id="task-0", executor_kind="claude")

        logger.log("claude_runner", "started", "Launching Claude Code command")
        logger.record_task_output({"stdout": "ok", "exit_code": 0}, output_kind="claude_command")
        logger.log("claude_runner", "completed", "Claude Code command completed")

        output = logger.task_output()

        self.assertEqual(output["output_kind"], "claude_command")
        self.assertEqual(output["result"], {"stdout": "ok", "exit_code": 0})
        self.assertEqual(output["status"], "completed")
        self.assertEqual(output["terminal_state"], "success")
        self.assertEqual(output["summary"], "Claude Code command completed")
        self.assertEqual(output["session_id"], "session-1")
        self.assertEqual(output["parent_task_id"], "task-0")
        self.assertEqual(output["executor_kind"], "claude")
        self.assertEqual(len(output["events"]), 2)

    def test_pipeline_logger_notifies_task_output_listeners(self):
        logger = PipelineLogger(run_id="run-1", task_id="task-1", session_id="session-1", executor_kind="claude")
        updates: list[tuple[str, dict]] = []

        logger.subscribe_task_output(lambda task_id, payload: updates.append((task_id, payload)))
        logger.record_task_output({"stdout": "partial"}, output_kind="claude_command")
        logger.sync_task_output_status(status="processing", summary="Streaming")

        self.assertEqual(updates[-1][0], "task-1")
        self.assertEqual(updates[-1][1]["result"]["stdout"], "partial")
        self.assertEqual(updates[-1][1]["status"], "processing")
        self.assertEqual(updates[-1][1]["summary"], "Streaming")

    def test_task_scoped_logger_record_output_uses_child_task_id(self):
        root_logger = PipelineLogger(run_id="run-1", task_id="task-parent", session_id="session-parent", executor_kind="local")
        task, child_logger = create_child_task_scope(
            root_logger,
            stage_key="claude_runner",
            title="Launch Claude Code command",
        )

        child_logger.record_output({"stdout": "child-output"}, output_kind="claude_command")

        self.assertIsNone(root_logger.task_output(task_id="task-parent"))
        self.assertEqual(
            root_logger.task_output(task_id=task.task_id),
            {
                "output_kind": "claude_command",
                "result": {"stdout": "child-output"},
            },
        )

    def test_task_scoped_logger_seed_output_preserves_task_scope(self):
        root_logger = PipelineLogger(run_id="run-1", task_id="task-parent", session_id="session-parent", executor_kind="local")
        task, child_logger = create_child_task_scope(
            root_logger,
            stage_key="script_agent.extract",
            title="Extract archive",
        )

        child_logger.seed_output(stage_key="script_agent.extract", title="Extract archive")

        output = root_logger.task_output(task_id=task.task_id)
        self.assertEqual(output["stage_key"], "script_agent.extract")
        self.assertEqual(output["title"], "Extract archive")
        self.assertEqual(output["session_id"], task.session_id)
        self.assertEqual(output["parent_task_id"], "task-parent")
        self.assertEqual(output["executor_kind"], "local")

    def test_executor_kind_for_stage_marks_claude_and_local_steps(self):
        self.assertEqual(executor_kind_for_stage("native_agent.claude"), "claude")
        self.assertEqual(executor_kind_for_stage("script_agent.extract"), "local")
        self.assertEqual(executor_kind_for_stage("report_synthesizer"), "local")

    def test_create_child_task_scope_creates_distinct_child_task_with_parent_link(self):
        logger = PipelineLogger(run_id="run-1", task_id="task-parent", session_id="session-parent", executor_kind="local")

        task, child_logger = create_child_task_scope(
            logger,
            stage_key="claude_runner",
            title="Launch Claude Code command",
        )
        event = child_logger.log("claude_runner", "started", "Launching Claude Code command")

        self.assertNotEqual(task.task_id, "task-parent")
        self.assertNotEqual(task.session_id, "session-parent")
        self.assertEqual(task.parent_task_id, "task-parent")
        self.assertEqual(task.executor_kind, "claude")
        self.assertEqual(event["data"]["task_id"], task.task_id)
        self.assertEqual(event["data"]["session_id"], task.session_id)
        self.assertEqual(event["data"]["parent_task_id"], "task-parent")
        self.assertEqual(event["data"]["executor_kind"], "claude")

    def test_artifact_registry_stores_and_queries_artifacts(self):
        registry = ArtifactRegistry()
        artifact = ArtifactNode(path="C:/sample.exe", sha256="abc")

        registry.add(artifact)

        self.assertIs(registry.get(artifact.id), artifact)
        self.assertIs(registry.get_by_path("C:/sample.exe"), artifact)
        self.assertEqual(registry.get_by_sha256("abc"), [artifact])
        self.assertEqual(registry.all(), [artifact])

    def test_finding_store_groups_findings_by_artifact(self):
        store = FindingStore()
        finding_a = Finding(artifact_id="artifact-1", category="ioc", summary="A")
        finding_b = Finding(artifact_id="artifact-1", category="behavior", summary="B")
        finding_c = Finding(artifact_id="artifact-2", category="ioc", summary="C")

        store.add_many([finding_a, finding_b, finding_c])

        self.assertEqual(store.get("artifact-1"), [finding_a, finding_b])
        self.assertEqual(store.get("artifact-2"), [finding_c])
        self.assertEqual(store.all(), [finding_a, finding_b, finding_c])

    def test_artifact_registry_tracks_parent_child_relationships(self):
        registry = ArtifactRegistry()
        parent = ArtifactNode(path="C:/parent.exe", sha256="parent")
        child = ArtifactNode(path="C:/child.exe", sha256="child", parent_id=parent.id)

        registry.add(parent)
        registry.add(child)

        self.assertEqual(registry.get_children(parent.id), [child])
        self.assertEqual(registry.get(child.id).parent_id, parent.id)

    def test_artifact_registry_can_assign_parent_after_insert(self):
        registry = ArtifactRegistry()
        parent = ArtifactNode(path="C:/parent.exe", sha256="parent")
        child = ArtifactNode(path="C:/child.exe", sha256="child")

        registry.add(parent)
        registry.add(child)
        registry.set_parent(child.id, parent.id)

        self.assertEqual(registry.get_children(parent.id), [child])
        self.assertEqual(registry.get(child.id).parent_id, parent.id)

    def test_normalize_agent_result_serializes_agent_result_legacy_payload(self):
        result = AgentResult(
            artifact_id="artifact-1",
            legacy_payload={"file_name": "sample.exe", "ai_analysis_report": "ok"},
            findings=[
                Finding(
                    artifact_id="artifact-1",
                    category="behavior",
                    summary="Creates process",
                    metadata={"evidence_refs": [{"kind": "legacy_payload_field", "field": "ai_analysis_report"}]},
                ),
                Finding(
                    artifact_id="artifact-1",
                    category="obfuscation",
                    summary="Detected packer indicators",
                    metadata={
                        "labels": ["packer"],
                        "evidence_refs": [{"kind": "legacy_payload_field", "field": "ai_analysis_report"}],
                    },
                ),
            ],
            metadata={"risk_score": 90},
        )

        normalized = normalize_agent_result(result)

        self.assertEqual(normalized, {"file_name": "sample.exe", "ai_analysis_report": "ok"})
        self.assertIsNot(normalized, result.legacy_payload)
        self.assertNotIn("findings", normalized)
        self.assertNotIn("metadata", normalized)
        self.assertNotIn("risk_score", normalized)

    def test_build_public_run_summary_serializes_phase5_root_fields(self):
        root = ArtifactNode(path="C:/sample.exe", sha256="abc", kind="native_input", id="artifact-1")
        findings = [
            Finding(
                artifact_id="artifact-1",
                category="analysis_report",
                summary="Native analysis report generated",
                confidence=1.0,
                id="finding-analysis",
            ),
            Finding(
                artifact_id="artifact-1",
                category="ioc",
                summary="Extracted IOCs",
                confidence=0.7,
                metadata={"ioc_values": ["https://c2.example.com", "10.20.30.40"]},
                id="finding-ioc",
            ),
            Finding(
                artifact_id="artifact-1",
                category="report_synthesis",
                summary="Synthesized final structured report",
                evidence="# Final Analysis Report",
                confidence=0.8,
                id="finding-report",
            ),
            Finding(
                artifact_id="artifact-1",
                category="risk_assessment",
                summary="Assigned critical risk assessment from structured findings",
                confidence=0.75,
                metadata={
                    "risk_level": "critical",
                    "risk_score": 85,
                    "reasons": ["Capability mapping flagged command and control"],
                },
                id="finding-risk",
            ),
        ]

        summary = build_public_run_summary(
            artifacts=[root],
            findings=findings,
            root_artifact_id="artifact-1",
        )

        self.assertEqual(
            summary["artifacts"],
            [
                {
                    "id": "artifact-1",
                    "path": "C:/sample.exe",
                    "kind": "native_input",
                    "parent_id": None,
                    "depth": 0,
                    "sha256": "abc",
                }
            ],
        )
        self.assertEqual(
            [finding["category"] for finding in summary["findings"]],
            ["analysis_report", "ioc", "report_synthesis", "risk_assessment"],
        )
        self.assertEqual(
            summary["iocs"],
            [
                {"artifact_id": "artifact-1", "type": "url", "value": "https://c2.example.com"},
                {"artifact_id": "artifact-1", "type": "ip_address", "value": "10.20.30.40"},
            ],
        )
        self.assertEqual(
            summary["verdict"],
            {
                "level": "critical",
                "score": 85,
                "reasons": ["Capability mapping flagged command and control"],
                "summary": "Assigned critical risk assessment from structured findings",
            },
        )
        self.assertEqual(summary["final_report_markdown"], "# Final Analysis Report")


if __name__ == "__main__":
    unittest.main()
