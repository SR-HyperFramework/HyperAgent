import unittest
from unittest.mock import Mock

from agents.behavior_analyzer_agent import BehaviorAnalyzerAgent
from agents.capability_mapper_agent import CapabilityMapperAgent
from agents.config_extractor_agent import ConfigExtractorAgent
from agents.ioc_extractor_agent import IOCExtractorAgent
from agents.obfuscation_analyzer_agent import ObfuscationAnalyzerAgent
from agents.report_synthesizer_agent import ReportSynthesizerAgent
from agents.risk_scoring_agent import RiskScoringAgent
from core.artifact_registry import ArtifactRegistry
from core.die_handler import AnalysisType
from core.finding_store import FindingStore
from core.result_models import ArtifactNode


class BehaviorAnalyzerAgentTests(unittest.TestCase):
    def test_behavior_analyzer_emits_native_finding_with_internal_evidence_refs(self):
        agent = BehaviorAnalyzerAgent()
        pipeline_logger = Mock()

        findings = agent.analyze(
            artifact_id="artifact-1",
            analysis_type=AnalysisType.NATIVE,
            analysis_data={"ai_analysis_report": "**Start of Analysis**\nCreates process\n**End of Analysis**"},
            pipeline_logger=pipeline_logger,
        )

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].artifact_id, "artifact-1")
        self.assertEqual(findings[0].category, "behavior")
        self.assertEqual(findings[0].summary, "Creates process")
        self.assertEqual(
            findings[0].metadata["evidence_refs"],
            [{"kind": "legacy_payload_field", "field": "ai_analysis_report"}],
        )
        pipeline_logger.log.assert_any_call(
            "behavior_analyzer",
            "started",
            "Running behavior specialist analyzer",
            artifact_id="artifact-1",
        )
        pipeline_logger.log.assert_any_call(
            "behavior_analyzer",
            "completed",
            "Behavior specialist analyzer completed",
            artifact_id="artifact-1",
            finding_count=1,
        )

    def test_behavior_analyzer_skips_non_native_or_missing_artifact(self):
        agent = BehaviorAnalyzerAgent()

        self.assertEqual(
            agent.analyze(
                artifact_id=None,
                analysis_type=AnalysisType.NATIVE,
                analysis_data={"ai_analysis_report": "ok"},
            ),
            [],
        )
        self.assertEqual(
            agent.analyze(
                artifact_id="artifact-1",
                analysis_type=AnalysisType.DOTNET,
                analysis_data={"ai_analysis_report": "ok"},
            ),
            [],
        )


class ObfuscationAnalyzerAgentTests(unittest.TestCase):
    def test_obfuscation_analyzer_emits_native_finding_when_report_has_obfuscation_signals(self):
        agent = ObfuscationAnalyzerAgent()
        pipeline_logger = Mock()

        findings = agent.analyze(
            artifact_id="artifact-1",
            analysis_type=AnalysisType.NATIVE,
            analysis_data={
                "ai_analysis_report": "**Start of Analysis**\nPacked loader with encrypted strings and import hashing\n**End of Analysis**"
            },
            pipeline_logger=pipeline_logger,
        )

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].artifact_id, "artifact-1")
        self.assertEqual(findings[0].category, "obfuscation")
        self.assertEqual(
            findings[0].metadata["labels"],
            ["packer", "loader", "string_encryption", "import_hashing"],
        )
        self.assertEqual(
            findings[0].metadata["evidence_refs"],
            [{"kind": "legacy_payload_field", "field": "ai_analysis_report"}],
        )
        pipeline_logger.log.assert_any_call(
            "obfuscation_analyzer",
            "started",
            "Running obfuscation specialist analyzer",
            artifact_id="artifact-1",
        )
        pipeline_logger.log.assert_any_call(
            "obfuscation_analyzer",
            "completed",
            "Obfuscation specialist analyzer completed",
            artifact_id="artifact-1",
            finding_count=1,
        )

    def test_obfuscation_analyzer_skips_without_native_artifact_or_signal(self):
        agent = ObfuscationAnalyzerAgent()

        self.assertEqual(
            agent.analyze(
                artifact_id=None,
                analysis_type=AnalysisType.NATIVE,
                analysis_data={"ai_analysis_report": "packed"},
            ),
            [],
        )
        self.assertEqual(
            agent.analyze(
                artifact_id="artifact-1",
                analysis_type=AnalysisType.DOTNET,
                analysis_data={"ai_analysis_report": "packed"},
            ),
            [],
        )
        self.assertEqual(
            agent.analyze(
                artifact_id="artifact-1",
                analysis_type=AnalysisType.NATIVE,
                analysis_data={"ai_analysis_report": "No suspicious indicators"},
            ),
            [],
        )


class ConfigExtractorAgentTests(unittest.TestCase):
    def test_config_extractor_emits_native_finding_when_report_has_config_signals(self):
        agent = ConfigExtractorAgent()
        pipeline_logger = Mock()

        findings = agent.analyze(
            artifact_id="artifact-1",
            analysis_type=AnalysisType.NATIVE,
            analysis_data={
                "ai_analysis_report": "**Start of Analysis**\nEmbedded config blob contains C2 https://c2.example.com and registry path HKEY_CURRENT_USER\\Software\\Badware\n**End of Analysis**"
            },
            pipeline_logger=pipeline_logger,
        )

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].artifact_id, "artifact-1")
        self.assertEqual(findings[0].category, "config")
        self.assertEqual(
            findings[0].metadata["config_items"],
            ["config_reference", "c2", "registry_path", "blob"],
        )
        self.assertEqual(
            findings[0].metadata["config_values"],
            ["https://c2.example.com", "HKEY_CURRENT_USER\\Software\\Badware"],
        )
        self.assertEqual(
            findings[0].metadata["evidence_refs"],
            [{"kind": "legacy_payload_field", "field": "ai_analysis_report"}],
        )
        pipeline_logger.log.assert_any_call(
            "config_extractor",
            "started",
            "Running config extraction specialist",
            artifact_id="artifact-1",
        )
        pipeline_logger.log.assert_any_call(
            "config_extractor",
            "completed",
            "Config extraction specialist completed",
            artifact_id="artifact-1",
            finding_count=1,
        )

    def test_config_extractor_skips_without_native_artifact_or_signal(self):
        agent = ConfigExtractorAgent()

        self.assertEqual(
            agent.analyze(
                artifact_id=None,
                analysis_type=AnalysisType.NATIVE,
                analysis_data={"ai_analysis_report": "config"},
            ),
            [],
        )
        self.assertEqual(
            agent.analyze(
                artifact_id="artifact-1",
                analysis_type=AnalysisType.DOTNET,
                analysis_data={"ai_analysis_report": "config"},
            ),
            [],
        )
        self.assertEqual(
            agent.analyze(
                artifact_id="artifact-1",
                analysis_type=AnalysisType.NATIVE,
                analysis_data={"ai_analysis_report": "No suspicious indicators"},
            ),
            [],
        )


class IOCExtractorAgentTests(unittest.TestCase):
    def test_ioc_extractor_emits_native_finding_when_report_has_ioc_signals(self):
        agent = IOCExtractorAgent()
        pipeline_logger = Mock()

        findings = agent.analyze(
            artifact_id="artifact-1",
            analysis_type=AnalysisType.NATIVE,
            analysis_data={
                "ai_analysis_report": "**Start of Analysis**\nConnects to https://c2.example.com at 10.20.30.40, sets mutex Global\\BadMutex, writes C:\\Users\\Public\\dropper.exe and registry key HKEY_CURRENT_USER\\Software\\Badware\n**End of Analysis**"
            },
            pipeline_logger=pipeline_logger,
        )

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].artifact_id, "artifact-1")
        self.assertEqual(findings[0].category, "ioc")
        self.assertEqual(
            findings[0].metadata["ioc_items"],
            ["url", "ip_address", "registry_key", "file_path", "mutex"],
        )
        self.assertEqual(
            findings[0].metadata["ioc_values"],
            [
                "https://c2.example.com",
                "10.20.30.40",
                "HKEY_CURRENT_USER\\Software\\Badware",
                "C:\\Users\\Public\\dropper.exe",
                "Global\\BadMutex",
            ],
        )
        self.assertEqual(
            findings[0].metadata["evidence_refs"],
            [{"kind": "legacy_payload_field", "field": "ai_analysis_report"}],
        )
        pipeline_logger.log.assert_any_call(
            "ioc_extractor",
            "started",
            "Running IOC extraction specialist",
            artifact_id="artifact-1",
        )
        pipeline_logger.log.assert_any_call(
            "ioc_extractor",
            "completed",
            "IOC extraction specialist completed",
            artifact_id="artifact-1",
            finding_count=1,
        )

    def test_ioc_extractor_skips_without_native_artifact_or_signal(self):
        agent = IOCExtractorAgent()

        self.assertEqual(
            agent.analyze(
                artifact_id=None,
                analysis_type=AnalysisType.NATIVE,
                analysis_data={"ai_analysis_report": "https://c2.example.com"},
            ),
            [],
        )
        self.assertEqual(
            agent.analyze(
                artifact_id="artifact-1",
                analysis_type=AnalysisType.DOTNET,
                analysis_data={"ai_analysis_report": "https://c2.example.com"},
            ),
            [],
        )
        self.assertEqual(
            agent.analyze(
                artifact_id="artifact-1",
                analysis_type=AnalysisType.NATIVE,
                analysis_data={"ai_analysis_report": "No suspicious indicators"},
            ),
            [],
        )


class CapabilityMapperAgentTests(unittest.TestCase):
    def test_capability_mapper_emits_native_finding_from_specialist_context(self):
        agent = CapabilityMapperAgent()
        pipeline_logger = Mock()
        behavior = BehaviorAnalyzerAgent().analyze(
            artifact_id="artifact-1",
            analysis_type=AnalysisType.NATIVE,
            analysis_data={"ai_analysis_report": "**Start of Analysis**\nCreates process and writes startup registry path\n**End of Analysis**"},
        )[0]
        obfuscation = ObfuscationAnalyzerAgent().analyze(
            artifact_id="artifact-1",
            analysis_type=AnalysisType.NATIVE,
            analysis_data={
                "ai_analysis_report": "**Start of Analysis**\nPacked loader with import hashing\n**End of Analysis**"
            },
        )[0]
        config = ConfigExtractorAgent().analyze(
            artifact_id="artifact-1",
            analysis_type=AnalysisType.NATIVE,
            analysis_data={
                "ai_analysis_report": "**Start of Analysis**\nEmbedded config blob contains C2 https://c2.example.com and startup registry path HKEY_CURRENT_USER\\Software\\Badware\n**End of Analysis**"
            },
        )[0]
        ioc = IOCExtractorAgent().analyze(
            artifact_id="artifact-1",
            analysis_type=AnalysisType.NATIVE,
            analysis_data={
                "ai_analysis_report": "**Start of Analysis**\nConnects to https://c2.example.com and 10.20.30.40\n**End of Analysis**"
            },
        )[0]

        findings = agent.analyze(
            artifact_id="artifact-1",
            analysis_type=AnalysisType.NATIVE,
            analysis_data={
                "ai_analysis_report": "**Start of Analysis**\nCreates process and writes startup registry path while contacting https://c2.example.com\n**End of Analysis**"
            },
            artifact_findings=[behavior, obfuscation, config, ioc],
            pipeline_logger=pipeline_logger,
        )

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].artifact_id, "artifact-1")
        self.assertEqual(findings[0].category, "capability")
        self.assertEqual(
            findings[0].metadata["capability_labels"],
            ["defense_evasion", "command_and_control", "execution", "persistence"],
        )
        self.assertEqual(findings[0].metadata["evidence_refs"][0], {"kind": "legacy_payload_field", "field": "ai_analysis_report"})
        self.assertTrue(any(ref.get("kind") == "finding" and ref.get("category") == "obfuscation" for ref in findings[0].metadata["evidence_refs"]))
        self.assertTrue(any(ref.get("kind") == "finding" and ref.get("category") == "config" for ref in findings[0].metadata["evidence_refs"]))
        self.assertTrue(any(ref.get("kind") == "finding" and ref.get("category") == "ioc" for ref in findings[0].metadata["evidence_refs"]))
        pipeline_logger.log.assert_any_call(
            "capability_mapper",
            "started",
            "Running capability mapping specialist",
            artifact_id="artifact-1",
        )
        pipeline_logger.log.assert_any_call(
            "capability_mapper",
            "completed",
            "Capability mapping specialist completed",
            artifact_id="artifact-1",
            finding_count=1,
        )

    def test_capability_mapper_skips_without_native_artifact_or_signal(self):
        agent = CapabilityMapperAgent()

        self.assertEqual(
            agent.analyze(
                artifact_id=None,
                analysis_type=AnalysisType.NATIVE,
                analysis_data={"ai_analysis_report": "Creates process"},
                artifact_findings=[],
            ),
            [],
        )
        self.assertEqual(
            agent.analyze(
                artifact_id="artifact-1",
                analysis_type=AnalysisType.DOTNET,
                analysis_data={"ai_analysis_report": "Creates process"},
                artifact_findings=[],
            ),
            [],
        )
        self.assertEqual(
            agent.analyze(
                artifact_id="artifact-1",
                analysis_type=AnalysisType.NATIVE,
                analysis_data={"ai_analysis_report": "No suspicious indicators"},
                artifact_findings=[],
            ),
            [],
        )


class ReportSynthesizerAgentTests(unittest.TestCase):
    def test_report_synthesizer_emits_root_level_finding_from_artifact_graph(self):
        registry = ArtifactRegistry()
        store = FindingStore()
        pipeline_logger = Mock()
        root = ArtifactNode(path="C:/samples/root.exe", sha256="hash-root", kind="native_input")
        child = ArtifactNode(path="C:/samples/payload.exe", sha256="hash-child", kind="native_input", parent_id=root.id, depth=1)
        registry.add(root)
        registry.add(child)

        coarse = BehaviorAnalyzerAgent().analyze(
            artifact_id=root.id,
            analysis_type=AnalysisType.NATIVE,
            analysis_data={"ai_analysis_report": "**Start of Analysis**\nRoot execution flow\n**End of Analysis**"},
        )[0]
        coarse.category = "analysis_report"
        behavior = BehaviorAnalyzerAgent().analyze(
            artifact_id=root.id,
            analysis_type=AnalysisType.NATIVE,
            analysis_data={"ai_analysis_report": "**Start of Analysis**\nCreates process\n**End of Analysis**"},
        )[0]
        ioc = IOCExtractorAgent().analyze(
            artifact_id=child.id,
            analysis_type=AnalysisType.NATIVE,
            analysis_data={
                "ai_analysis_report": "**Start of Analysis**\nConnects to https://c2.example.com and 10.20.30.40\n**End of Analysis**"
            },
        )[0]
        capability = CapabilityMapperAgent().analyze(
            artifact_id=root.id,
            analysis_type=AnalysisType.NATIVE,
            analysis_data={
                "ai_analysis_report": "**Start of Analysis**\nCreates process and connects to https://c2.example.com\n**End of Analysis**"
            },
            artifact_findings=[behavior, ioc],
        )[0]
        store.add(coarse)
        store.add(behavior)
        store.add(ioc)
        store.add(capability)

        findings = ReportSynthesizerAgent().analyze(
            root_artifact_id=root.id,
            artifact_registry=registry,
            finding_store=store,
            pipeline_logger=pipeline_logger,
        )

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].artifact_id, root.id)
        self.assertEqual(findings[0].category, "report_synthesis")
        self.assertEqual(findings[0].metadata["source"], "ReportSynthesizerAgent")
        self.assertEqual(findings[0].metadata["artifact_ids"], [root.id, child.id])
        self.assertEqual(findings[0].metadata["ioc_values"], ["https://c2.example.com", "10.20.30.40"])
        self.assertEqual(findings[0].metadata["capability_labels"], ["command_and_control", "execution"])
        self.assertIn("# Final Analysis Report", findings[0].evidence)
        self.assertIn("## Artifact Chain Summary", findings[0].evidence)
        self.assertIn("`C:/samples/root.exe`", findings[0].evidence)
        self.assertIn("`C:/samples/payload.exe`", findings[0].evidence)
        pipeline_logger.log.assert_any_call(
            "report_synthesizer",
            "started",
            "Running report synthesis",
            artifact_id=root.id,
        )
        pipeline_logger.log.assert_any_call(
            "report_synthesizer",
            "completed",
            "Report synthesis completed",
            artifact_id=root.id,
            finding_count=1,
        )

    def test_report_synthesizer_skips_without_root_or_findings(self):
        agent = ReportSynthesizerAgent()
        registry = ArtifactRegistry()
        store = FindingStore()
        root = ArtifactNode(path="C:/samples/root.exe", sha256="hash-root", kind="native_input")
        registry.add(root)

        self.assertEqual(
            agent.analyze(
                root_artifact_id=None,
                artifact_registry=registry,
                finding_store=store,
            ),
            [],
        )
        self.assertEqual(
            agent.analyze(
                root_artifact_id=root.id,
                artifact_registry=registry,
                finding_store=store,
            ),
            [],
        )


class RiskScoringAgentTests(unittest.TestCase):
    def test_risk_scoring_emits_root_level_finding_from_structured_findings(self):
        registry = ArtifactRegistry()
        store = FindingStore()
        pipeline_logger = Mock()
        root = ArtifactNode(path="C:/samples/root.exe", sha256="hash-root", kind="native_input")
        child = ArtifactNode(path="C:/samples/payload.exe", sha256="hash-child", kind="native_input", parent_id=root.id, depth=1)
        registry.add(root)
        registry.add(child)

        behavior = BehaviorAnalyzerAgent().analyze(
            artifact_id=root.id,
            analysis_type=AnalysisType.NATIVE,
            analysis_data={"ai_analysis_report": "**Start of Analysis**\nCreates process\n**End of Analysis**"},
        )[0]
        obfuscation = ObfuscationAnalyzerAgent().analyze(
            artifact_id=root.id,
            analysis_type=AnalysisType.NATIVE,
            analysis_data={"ai_analysis_report": "**Start of Analysis**\nPacked loader with import hashing\n**End of Analysis**"},
        )[0]
        ioc = IOCExtractorAgent().analyze(
            artifact_id=child.id,
            analysis_type=AnalysisType.NATIVE,
            analysis_data={
                "ai_analysis_report": "**Start of Analysis**\nConnects to https://c2.example.com and 10.20.30.40\n**End of Analysis**"
            },
        )[0]
        capability = CapabilityMapperAgent().analyze(
            artifact_id=root.id,
            analysis_type=AnalysisType.NATIVE,
            analysis_data={
                "ai_analysis_report": "**Start of Analysis**\nCreates process and writes startup registry path while contacting https://c2.example.com\n**End of Analysis**"
            },
            artifact_findings=[behavior, obfuscation, ioc],
        )[0]
        store.add(behavior)
        store.add(obfuscation)
        store.add(ioc)
        store.add(capability)

        report = ReportSynthesizerAgent().analyze(
            root_artifact_id=root.id,
            artifact_registry=registry,
            finding_store=store,
        )[0]
        store.add(report)

        findings = RiskScoringAgent().analyze(
            root_artifact_id=root.id,
            artifact_registry=registry,
            finding_store=store,
            pipeline_logger=pipeline_logger,
        )

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].artifact_id, root.id)
        self.assertEqual(findings[0].category, "risk_assessment")
        self.assertEqual(findings[0].metadata["source"], "RiskScoringAgent")
        self.assertEqual(findings[0].metadata["artifact_ids"], [root.id, child.id])
        self.assertEqual(findings[0].metadata["risk_level"], "critical")
        self.assertGreaterEqual(findings[0].metadata["risk_score"], 75)
        self.assertTrue(any("Obfuscation indicators" in reason for reason in findings[0].metadata["reasons"]))
        self.assertIn("# Risk Assessment", findings[0].evidence)
        pipeline_logger.log.assert_any_call(
            "risk_scoring",
            "started",
            "Running risk scoring synthesis",
            artifact_id=root.id,
        )
        pipeline_logger.log.assert_any_call(
            "risk_scoring",
            "completed",
            "Risk scoring synthesis completed",
            artifact_id=root.id,
            finding_count=1,
        )

    def test_risk_scoring_skips_without_root_or_findings(self):
        agent = RiskScoringAgent()
        registry = ArtifactRegistry()
        store = FindingStore()
        root = ArtifactNode(path="C:/samples/root.exe", sha256="hash-root", kind="native_input")
        registry.add(root)

        self.assertEqual(
            agent.analyze(
                root_artifact_id=None,
                artifact_registry=registry,
                finding_store=store,
            ),
            [],
        )
        self.assertEqual(
            agent.analyze(
                root_artifact_id=root.id,
                artifact_registry=registry,
                finding_store=store,
            ),
            [],
        )


class FindingStoreSpecialistTests(unittest.TestCase):
    def test_finding_store_preserves_coarse_and_specialist_findings_together(self):
        store = FindingStore()
        coarse = BehaviorAnalyzerAgent().analyze(
            artifact_id="artifact-1",
            analysis_type=AnalysisType.NATIVE,
            analysis_data={"ai_analysis_report": "**Start of Analysis**\nDoes X\n**End of Analysis**"},
        )[0]
        coarse.category = "analysis_report"
        behavior = BehaviorAnalyzerAgent().analyze(
            artifact_id="artifact-1",
            analysis_type=AnalysisType.NATIVE,
            analysis_data={"ai_analysis_report": "**Start of Analysis**\nCreates process\n**End of Analysis**"},
        )[0]
        obfuscation = ObfuscationAnalyzerAgent().analyze(
            artifact_id="artifact-1",
            analysis_type=AnalysisType.NATIVE,
            analysis_data={
                "ai_analysis_report": "**Start of Analysis**\nPacked loader with import hashing\n**End of Analysis**"
            },
        )[0]
        config = ConfigExtractorAgent().analyze(
            artifact_id="artifact-1",
            analysis_type=AnalysisType.NATIVE,
            analysis_data={
                "ai_analysis_report": "**Start of Analysis**\nEmbedded config blob contains C2 https://c2.example.com\n**End of Analysis**"
            },
        )[0]
        ioc = IOCExtractorAgent().analyze(
            artifact_id="artifact-1",
            analysis_type=AnalysisType.NATIVE,
            analysis_data={
                "ai_analysis_report": "**Start of Analysis**\nConnects to https://c2.example.com and 10.20.30.40\n**End of Analysis**"
            },
        )[0]
        capability = CapabilityMapperAgent().analyze(
            artifact_id="artifact-1",
            analysis_type=AnalysisType.NATIVE,
            analysis_data={
                "ai_analysis_report": "**Start of Analysis**\nCreates process and connects to https://c2.example.com\n**End of Analysis**"
            },
            artifact_findings=[behavior, obfuscation, config, ioc],
        )[0]

        store.add(coarse)
        store.add(behavior)
        store.add(obfuscation)
        store.add(config)
        store.add(ioc)
        store.add(capability)

        registry = ArtifactRegistry()
        registry.add(ArtifactNode(path="C:/samples/root.exe", id="artifact-1"))
        report = ReportSynthesizerAgent().analyze(
            root_artifact_id="artifact-1",
            artifact_registry=registry,
            finding_store=store,
        )[0]
        store.add(report)

        risk = RiskScoringAgent().analyze(
            root_artifact_id="artifact-1",
            artifact_registry=registry,
            finding_store=store,
        )[0]
        store.add(risk)

        stored = store.get("artifact-1")
        self.assertEqual(
            [finding.category for finding in stored],
            ["analysis_report", "behavior", "obfuscation", "config", "ioc", "capability", "report_synthesis", "risk_assessment"],
        )


if __name__ == "__main__":
    unittest.main()
