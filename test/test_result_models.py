import unittest

from core.artifact_registry import ArtifactRegistry
from core.finding_store import FindingStore
from core.output_normalizer import build_public_run_summary, normalize_agent_result
from core.result_models import AgentResult, ArtifactNode, Finding


class ResultModelTests(unittest.TestCase):
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
