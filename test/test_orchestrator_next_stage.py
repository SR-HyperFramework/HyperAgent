import hashlib
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from agents.next_stage_hunter_agent import NextStageHunterAgent
from core.artifact_registry import ArtifactRegistry
from core.die_handler import AnalysisType
from core.finding_store import FindingStore
from core.pipeline_logger import PipelineLogger
from core.result_models import AgentResult, ArtifactNode, Finding
from main import HyperAgentOrchestrator


def build_native_agent_result(path: str, depth: int) -> AgentResult:
    artifact = ArtifactNode(path=os.path.abspath(path), sha256="native-hash", depth=depth, kind="native_input")
    finding = Finding(
        artifact_id=artifact.id,
        category="analysis_report",
        summary="Native analysis report generated",
        evidence="**Start of Analysis**\nOK\n**End of Analysis**",
        confidence=1.0,
    )
    return AgentResult(
        artifact_id=artifact.id,
        legacy_payload={"ai_analysis_report": "**Start of Analysis**\nOK\n**End of Analysis**"},
        artifacts=[artifact],
        findings=[finding],
    )


def build_script_agent_result(path: str, extract_dir: str, depth: int) -> AgentResult:
    artifact = ArtifactNode(path=os.path.abspath(path), sha256="script-hash", depth=depth, kind="script_input")
    finding = Finding(
        artifact_id=artifact.id,
        category="analysis_report",
        summary="Script analysis report generated",
        evidence="**Start of Analysis**\nOK\n**End of Analysis**",
        confidence=1.0,
    )
    return AgentResult(
        artifact_id=artifact.id,
        legacy_payload={"extract_dir": extract_dir, "ai_analysis_report": "**Start of Analysis**\nOK\n**End of Analysis**"},
        artifacts=[artifact],
        findings=[finding],
    )


def build_orchestrator() -> HyperAgentOrchestrator:
    orchestrator = HyperAgentOrchestrator.__new__(HyperAgentOrchestrator)
    orchestrator.config_path = "config.yaml"
    orchestrator.config = {}
    orchestrator.die_handler = Mock()
    return orchestrator


def build_run_context_support():
    return ArtifactRegistry(), FindingStore(), PipelineLogger("test-run")


def register_agent_result(result: AgentResult, registry: ArtifactRegistry, store: FindingStore):
    for artifact in result.artifacts:
        registry.add(artifact)
    store.add_many(result.findings)
    return result


def agent_result_side_effect(path: str, registry: ArtifactRegistry, store: FindingStore):
    def build(*args, run_context=None, **kwargs):
        if path.endswith(".exe"):
            result = build_native_agent_result(path, run_context.depth if run_context else 0)
        else:
            extract_dir = kwargs.get("extract_dir") or args[0] if args else os.path.dirname(path)
            result = build_script_agent_result(path, extract_dir, run_context.depth if run_context else 0)
        if run_context and run_context.artifact_registry and run_context.finding_store:
            register_agent_result(result, run_context.artifact_registry, run_context.finding_store)
        return result

    return build


def async_agent_result(builder):
    async def _run(*args, **kwargs):
        return builder(*args, **kwargs)

    return _run


def build_native_result_for_path(path: str):
    def builder(*args, run_context=None, **kwargs):
        result = build_native_agent_result(path, run_context.depth if run_context else 0)
        if run_context and run_context.artifact_registry and run_context.finding_store:
            register_agent_result(result, run_context.artifact_registry, run_context.finding_store)
        return result

    return async_agent_result(builder)


def build_script_result_for_path(path: str, extract_dir: str):
    def builder(*args, run_context=None, **kwargs):
        result = build_script_agent_result(path, extract_dir, run_context.depth if run_context else 0)
        if run_context and run_context.artifact_registry and run_context.finding_store:
            register_agent_result(result, run_context.artifact_registry, run_context.finding_store)
        return result

    return async_agent_result(builder)


def count_categories(store: FindingStore, artifact_id: str) -> list[str]:
    return [finding.category for finding in store.get(artifact_id)]


class SpecialistIntegrationHarness(unittest.IsolatedAsyncioTestCase):
    async def test_specialist_stage_adds_behavior_finding_without_changing_payload(self):
        from core.orchestration import ArtifactGraphOrchestrator

        with tempfile.NamedTemporaryFile("wb", suffix=".exe", delete=False) as temp_file:
            temp_file.write(b"MZnative")
            file_path = temp_file.name

        try:
            registry, store, logger = build_run_context_support()
            die_handler = Mock()
            die_handler.identify.return_value = ({"compiler": "msvc"}, AnalysisType.NATIVE)
            native_agent = Mock()
            native_agent.analyze = AsyncMock(side_effect=build_native_result_for_path(file_path))
            engine = ArtifactGraphOrchestrator(
                config_path="config.yaml",
                die_handler=die_handler,
                pipeline_logger=logger,
                artifact_registry=registry,
                finding_store=store,
                agent_factory=lambda analysis_type: native_agent,
            )

            result = await engine.analyze(file_path, run_id="test-run")

            artifact = registry.get_by_path(os.path.abspath(file_path))
            self.assertIsNotNone(artifact)
            self.assertEqual(result["result"], {"ai_analysis_report": "**Start of Analysis**\nOK\n**End of Analysis**"})
            self.assertEqual(result["artifacts"], [
                {
                    "id": artifact.id,
                    "path": os.path.abspath(file_path),
                    "kind": "native_input",
                    "parent_id": None,
                    "depth": 0,
                    "sha256": "native-hash",
                }
            ])
            self.assertEqual(
                [finding["category"] for finding in result["findings"]],
                ["analysis_report", "behavior", "report_synthesis", "risk_assessment"],
            )
            self.assertEqual(result["iocs"], [])
            self.assertEqual(result["verdict"]["level"], "low")
            self.assertEqual(result["verdict"]["score"], 10)
            self.assertEqual(result["verdict"]["summary"], "Assigned low risk assessment from structured findings")
            self.assertIn("# Final Analysis Report", result["final_report_markdown"])
            self.assertEqual(count_categories(store, artifact.id), ["analysis_report", "behavior", "report_synthesis", "risk_assessment"])
            behavior_finding = store.get(artifact.id)[1]
            report_finding = store.get(artifact.id)[2]
            risk_finding = store.get(artifact.id)[3]
            self.assertEqual(report_finding.metadata["source"], "ReportSynthesizerAgent")
            self.assertEqual(risk_finding.metadata["source"], "RiskScoringAgent")
            self.assertEqual(behavior_finding.metadata["source"], "BehaviorAnalyzerAgent")
            self.assertEqual(
                behavior_finding.metadata["evidence_refs"],
                [{"kind": "legacy_payload_field", "field": "ai_analysis_report"}],
            )
        finally:
            os.unlink(file_path)

    async def test_specialist_stage_adds_obfuscation_finding_without_changing_payload(self):
        from core.orchestration import ArtifactGraphOrchestrator

        with tempfile.NamedTemporaryFile("wb", suffix=".exe", delete=False) as temp_file:
            temp_file.write(b"MZnative")
            file_path = temp_file.name

        def build_obfuscation_finding(*, artifact_id: str | None, **kwargs):
            if not artifact_id:
                return []
            return [
                Finding(
                    artifact_id=artifact_id,
                    category="obfuscation",
                    summary="Detected packed loader indicators",
                    metadata={
                        "source": "ObfuscationAnalyzerAgent",
                        "labels": ["packer", "loader"],
                        "evidence_refs": [{"kind": "legacy_payload_field", "field": "ai_analysis_report"}],
                    },
                )
            ]

        try:
            registry, store, logger = build_run_context_support()
            die_handler = Mock()
            die_handler.identify.return_value = ({"compiler": "msvc"}, AnalysisType.NATIVE)
            native_agent = Mock()
            native_agent.analyze = AsyncMock(side_effect=build_native_result_for_path(file_path))
            engine = ArtifactGraphOrchestrator(
                config_path="config.yaml",
                die_handler=die_handler,
                pipeline_logger=logger,
                artifact_registry=registry,
                finding_store=store,
                agent_factory=lambda analysis_type: native_agent,
            )

            with patch(
                "agents.obfuscation_analyzer_agent.ObfuscationAnalyzerAgent.analyze",
                side_effect=build_obfuscation_finding,
            ):
                result = await engine.analyze(file_path, run_id="test-run")

            artifact = registry.get_by_path(os.path.abspath(file_path))
            self.assertIsNotNone(artifact)
            self.assertEqual(result["result"], {"ai_analysis_report": "**Start of Analysis**\nOK\n**End of Analysis**"})
            self.assertEqual(count_categories(store, artifact.id), ["analysis_report", "behavior", "obfuscation", "capability", "report_synthesis", "risk_assessment"])
            obfuscation_finding = store.get(artifact.id)[2]
            self.assertEqual(obfuscation_finding.metadata["source"], "ObfuscationAnalyzerAgent")
            self.assertEqual(obfuscation_finding.metadata["labels"], ["packer", "loader"])
            capability_finding = store.get(artifact.id)[3]
            self.assertEqual(capability_finding.metadata["source"], "CapabilityMapperAgent")
            self.assertEqual(capability_finding.metadata["capability_labels"], ["defense_evasion"])
            report_finding = store.get(artifact.id)[4]
            risk_finding = store.get(artifact.id)[5]
            self.assertEqual(report_finding.metadata["source"], "ReportSynthesizerAgent")
            self.assertEqual(risk_finding.metadata["source"], "RiskScoringAgent")
        finally:
            os.unlink(file_path)

    async def test_specialist_stage_closes_obfuscation_task_when_no_findings(self):
        from core.orchestration import ArtifactGraphOrchestrator

        with tempfile.NamedTemporaryFile("wb", suffix=".exe", delete=False) as temp_file:
            temp_file.write(b"MZnative")
            file_path = temp_file.name

        try:
            registry, store, logger = build_run_context_support()
            die_handler = Mock()
            die_handler.identify.return_value = ({"compiler": "msvc"}, AnalysisType.NATIVE)
            native_agent = Mock()
            native_agent.analyze = AsyncMock(side_effect=build_native_result_for_path(file_path))
            engine = ArtifactGraphOrchestrator(
                config_path="config.yaml",
                die_handler=die_handler,
                pipeline_logger=logger,
                artifact_registry=registry,
                finding_store=store,
                agent_factory=lambda analysis_type: native_agent,
            )

            with patch(
                "agents.obfuscation_analyzer_agent.ObfuscationAnalyzerAgent.analyze",
                return_value=[],
            ):
                await engine.analyze(file_path, run_id="test-run")

            obfuscation_events = [
                event
                for event in logger.snapshot()
                if event["stage"] == "obfuscation_analyzer"
            ]
            self.assertEqual(
                [event["state"] for event in obfuscation_events],
                ["queued", "completed"],
            )
            self.assertEqual(
                obfuscation_events[-1]["message"],
                "Obfuscation analysis completed",
            )
            self.assertEqual(obfuscation_events[-1]["data"]["finding_count"], 0)
        finally:
            os.unlink(file_path)

    async def test_specialist_stage_adds_config_finding_without_changing_payload(self):
        from core.orchestration import ArtifactGraphOrchestrator

        with tempfile.NamedTemporaryFile("wb", suffix=".exe", delete=False) as temp_file:
            temp_file.write(b"MZnative")
            file_path = temp_file.name

        def build_config_finding(*, artifact_id: str | None, **kwargs):
            if not artifact_id:
                return []
            return [
                Finding(
                    artifact_id=artifact_id,
                    category="config",
                    summary="Extracted config indicators: https://c2.example.com",
                    metadata={
                        "source": "ConfigExtractorAgent",
                        "config_items": ["config_reference", "c2"],
                        "config_values": ["https://c2.example.com"],
                        "evidence_refs": [{"kind": "legacy_payload_field", "field": "ai_analysis_report"}],
                    },
                )
            ]

        try:
            registry, store, logger = build_run_context_support()
            die_handler = Mock()
            die_handler.identify.return_value = ({"compiler": "msvc"}, AnalysisType.NATIVE)
            native_agent = Mock()
            native_agent.analyze = AsyncMock(side_effect=build_native_result_for_path(file_path))
            engine = ArtifactGraphOrchestrator(
                config_path="config.yaml",
                die_handler=die_handler,
                pipeline_logger=logger,
                artifact_registry=registry,
                finding_store=store,
                agent_factory=lambda analysis_type: native_agent,
            )

            with patch(
                "agents.config_extractor_agent.ConfigExtractorAgent.analyze",
                side_effect=build_config_finding,
            ):
                result = await engine.analyze(file_path, run_id="test-run")

            artifact = registry.get_by_path(os.path.abspath(file_path))
            self.assertIsNotNone(artifact)
            self.assertEqual(result["result"], {"ai_analysis_report": "**Start of Analysis**\nOK\n**End of Analysis**"})
            self.assertEqual(count_categories(store, artifact.id), ["analysis_report", "behavior", "config", "capability", "report_synthesis", "risk_assessment"])
            config_finding = store.get(artifact.id)[2]
            self.assertEqual(config_finding.metadata["source"], "ConfigExtractorAgent")
            self.assertEqual(config_finding.metadata["config_values"], ["https://c2.example.com"])
            capability_finding = store.get(artifact.id)[3]
            self.assertEqual(capability_finding.metadata["source"], "CapabilityMapperAgent")
            self.assertEqual(capability_finding.metadata["capability_labels"], ["command_and_control"])
            report_finding = store.get(artifact.id)[4]
            risk_finding = store.get(artifact.id)[5]
            self.assertEqual(report_finding.metadata["source"], "ReportSynthesizerAgent")
            self.assertEqual(risk_finding.metadata["source"], "RiskScoringAgent")
        finally:
            os.unlink(file_path)

    async def test_specialist_stage_adds_ioc_finding_without_changing_payload(self):
        from core.orchestration import ArtifactGraphOrchestrator

        with tempfile.NamedTemporaryFile("wb", suffix=".exe", delete=False) as temp_file:
            temp_file.write(b"MZnative")
            file_path = temp_file.name

        def build_ioc_finding(*, artifact_id: str | None, **kwargs):
            if not artifact_id:
                return []
            return [
                Finding(
                    artifact_id=artifact_id,
                    category="ioc",
                    summary="Extracted IOCs: https://c2.example.com, 10.20.30.40",
                    metadata={
                        "source": "IOCExtractorAgent",
                        "ioc_items": ["url", "ip_address"],
                        "ioc_values": ["https://c2.example.com", "10.20.30.40"],
                        "evidence_refs": [{"kind": "legacy_payload_field", "field": "ai_analysis_report"}],
                    },
                )
            ]

        try:
            registry, store, logger = build_run_context_support()
            die_handler = Mock()
            die_handler.identify.return_value = ({"compiler": "msvc"}, AnalysisType.NATIVE)
            native_agent = Mock()
            native_agent.analyze = AsyncMock(side_effect=build_native_result_for_path(file_path))
            engine = ArtifactGraphOrchestrator(
                config_path="config.yaml",
                die_handler=die_handler,
                pipeline_logger=logger,
                artifact_registry=registry,
                finding_store=store,
                agent_factory=lambda analysis_type: native_agent,
            )

            with patch(
                "agents.ioc_extractor_agent.IOCExtractorAgent.analyze",
                side_effect=build_ioc_finding,
            ):
                result = await engine.analyze(file_path, run_id="test-run")

            artifact = registry.get_by_path(os.path.abspath(file_path))
            self.assertIsNotNone(artifact)
            self.assertEqual(result["result"], {"ai_analysis_report": "**Start of Analysis**\nOK\n**End of Analysis**"})
            self.assertEqual(count_categories(store, artifact.id), ["analysis_report", "behavior", "ioc", "capability", "report_synthesis", "risk_assessment"])
            ioc_finding = store.get(artifact.id)[2]
            self.assertEqual(ioc_finding.metadata["source"], "IOCExtractorAgent")
            self.assertEqual(ioc_finding.metadata["ioc_values"], ["https://c2.example.com", "10.20.30.40"])
            capability_finding = store.get(artifact.id)[3]
            self.assertEqual(capability_finding.metadata["source"], "CapabilityMapperAgent")
            self.assertEqual(capability_finding.metadata["capability_labels"], ["command_and_control"])
            report_finding = store.get(artifact.id)[4]
            risk_finding = store.get(artifact.id)[5]
            self.assertEqual(report_finding.metadata["source"], "ReportSynthesizerAgent")
            self.assertEqual(risk_finding.metadata["source"], "RiskScoringAgent")
        finally:
            os.unlink(file_path)

    async def test_specialist_stage_adds_capability_finding_without_changing_payload(self):
        from core.orchestration import ArtifactGraphOrchestrator

        with tempfile.NamedTemporaryFile("wb", suffix=".exe", delete=False) as temp_file:
            temp_file.write(b"MZnative")
            file_path = temp_file.name

        def build_capability_finding(*, artifact_id: str | None, **kwargs):
            if not artifact_id:
                return []
            return [
                Finding(
                    artifact_id=artifact_id,
                    category="capability",
                    summary="Mapped capability indicators: defense evasion, command and control",
                    metadata={
                        "source": "CapabilityMapperAgent",
                        "capability_labels": ["defense_evasion", "command_and_control"],
                        "evidence_refs": [
                            {"kind": "legacy_payload_field", "field": "ai_analysis_report"},
                            {"kind": "finding", "id": "finding-obf", "category": "obfuscation"},
                        ],
                    },
                )
            ]

        try:
            registry, store, logger = build_run_context_support()
            die_handler = Mock()
            die_handler.identify.return_value = ({"compiler": "msvc"}, AnalysisType.NATIVE)
            native_agent = Mock()
            native_agent.analyze = AsyncMock(side_effect=build_native_result_for_path(file_path))
            engine = ArtifactGraphOrchestrator(
                config_path="config.yaml",
                die_handler=die_handler,
                pipeline_logger=logger,
                artifact_registry=registry,
                finding_store=store,
                agent_factory=lambda analysis_type: native_agent,
            )

            with patch(
                "agents.capability_mapper_agent.CapabilityMapperAgent.analyze",
                side_effect=build_capability_finding,
            ):
                result = await engine.analyze(file_path, run_id="test-run")

            artifact = registry.get_by_path(os.path.abspath(file_path))
            self.assertIsNotNone(artifact)
            self.assertEqual(result["result"], {"ai_analysis_report": "**Start of Analysis**\nOK\n**End of Analysis**"})
            self.assertEqual(count_categories(store, artifact.id), ["analysis_report", "behavior", "capability", "report_synthesis", "risk_assessment"])
            capability_finding = store.get(artifact.id)[2]
            self.assertEqual(capability_finding.metadata["source"], "CapabilityMapperAgent")
            self.assertEqual(capability_finding.metadata["capability_labels"], ["defense_evasion", "command_and_control"])
            report_finding = store.get(artifact.id)[3]
            risk_finding = store.get(artifact.id)[4]
            self.assertEqual(report_finding.metadata["source"], "ReportSynthesizerAgent")
            self.assertEqual(risk_finding.metadata["source"], "RiskScoringAgent")
        finally:
            os.unlink(file_path)


class NextStageHunterTests(unittest.TestCase):
    def test_hunter_returns_sorted_unique_candidates_with_provenance(self):
        hunter = NextStageHunterAgent()

        with tempfile.TemporaryDirectory() as extract_dir:
            payload_path = os.path.join(extract_dir, "payload.exe")
            script_path = os.path.join(extract_dir, "helper.py")
            nested_dir = os.path.join(extract_dir, "pkg")
            os.makedirs(nested_dir)
            nested_payload_path = os.path.join(nested_dir, "module.pyc")
            ignored_path = os.path.join(extract_dir, "notes.txt")

            for path, content in (
                (payload_path, b"MZpayload"),
                (script_path, b"print('hi')"),
                (nested_payload_path, b"\x00\x00"),
                (ignored_path, b"ignore"),
            ):
                with open(path, "wb") as f:
                    f.write(content)

            candidates = hunter.analyze(
                analysis_data={
                    "extract_dir": extract_dir,
                    "source_directory": extract_dir,
                }
            )

        self.assertEqual([candidate["path"] for candidate in candidates], sorted([os.path.abspath(payload_path), os.path.abspath(script_path), os.path.abspath(nested_payload_path)]))
        self.assertEqual(candidates[0]["priority"], 0)
        self.assertEqual(candidates[0]["canonical_path"], os.path.normcase(candidates[0]["path"]))
        self.assertEqual(candidates[0]["provenance"], ["extract_dir", "source_directory"])

    def test_hunter_prefers_structured_signals_and_merges_provenance(self):
        hunter = NextStageHunterAgent()
        registry = ArtifactRegistry()

        with tempfile.TemporaryDirectory() as extract_dir:
            payload_path = os.path.join(extract_dir, "payload.exe")
            with open(payload_path, "wb") as f:
                f.write(b"MZpayload")

            root = ArtifactNode(path=os.path.join(extract_dir, "root.py"), sha256="root")
            child = ArtifactNode(path=os.path.abspath(payload_path), sha256="payload", parent_id=root.id)
            registry.add(root)
            registry.add(child)

            candidates = hunter.analyze(
                artifact_id=root.id,
                artifact_registry=registry,
                analysis_data={
                    "extract_dir": extract_dir,
                    "extracted_candidates": [payload_path],
                    "priority_pyasm_files": [payload_path],
                },
            )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["path"], os.path.abspath(payload_path))
        self.assertEqual(candidates[0]["priority"], 30)
        self.assertEqual(
            candidates[0]["provenance"],
            ["artifact_registry", "extracted_candidates", "priority_pyasm_files"],
        )

    def test_hunter_deduplicates_same_hash_candidates_across_different_paths(self):
        hunter = NextStageHunterAgent()
        registry = ArtifactRegistry()

        with tempfile.TemporaryDirectory() as extract_dir:
            alpha_path = os.path.join(extract_dir, "alpha.exe")
            beta_path = os.path.join(extract_dir, "beta.exe")
            payload_bytes = b"MZsame-payload"
            payload_hash = hashlib.sha256(payload_bytes).hexdigest()
            for path in (alpha_path, beta_path):
                with open(path, "wb") as f:
                    f.write(payload_bytes)

            root = ArtifactNode(path=os.path.join(extract_dir, "root.py"), sha256="root")
            child = ArtifactNode(path=os.path.abspath(alpha_path), sha256=payload_hash, parent_id=root.id)
            registry.add(root)
            registry.add(child)

            candidates = hunter.analyze(
                artifact_id=root.id,
                artifact_registry=registry,
                analysis_data={
                    "extracted_candidates": [beta_path],
                },
            )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["path"], os.path.abspath(alpha_path))
        self.assertEqual(candidates[0]["priority"], 30)
        self.assertEqual(candidates[0]["provenance"], ["artifact_registry", "extracted_candidates"])
        self.assertEqual(candidates[0]["sha256"], payload_hash)

    def test_hunter_skips_noise_directories_during_fallback_scan(self):
        hunter = NextStageHunterAgent()

        with tempfile.TemporaryDirectory() as extract_dir:
            noise_dir = os.path.join(extract_dir, "__pycache__")
            site_packages_dir = os.path.join(extract_dir, "site-packages")
            dist_info_dir = os.path.join(extract_dir, "sample.dist-info")
            signal_dir = os.path.join(extract_dir, "pkg")
            os.makedirs(noise_dir)
            os.makedirs(site_packages_dir)
            os.makedirs(dist_info_dir)
            os.makedirs(signal_dir)

            skipped_paths = [
                os.path.join(noise_dir, "cached.pyc"),
                os.path.join(site_packages_dir, "vendor.py"),
                os.path.join(dist_info_dir, "metadata.py"),
            ]
            kept_path = os.path.join(signal_dir, "payload.py")

            for path, content in [
                *[(path, b"noise") for path in skipped_paths],
                (kept_path, b"print('payload')"),
            ]:
                with open(path, "wb") as f:
                    f.write(content)

            candidates = hunter.analyze(
                analysis_data={
                    "extract_dir": extract_dir,
                }
            )

        self.assertEqual([candidate["path"] for candidate in candidates], [os.path.abspath(kept_path)])
        self.assertEqual(candidates[0]["provenance"], ["extract_dir"])

    def test_hunter_falls_back_when_structured_signals_contain_only_noise(self):
        hunter = NextStageHunterAgent()

        with tempfile.TemporaryDirectory() as extract_dir:
            noise_dir = os.path.join(extract_dir, "__pycache__")
            signal_dir = os.path.join(extract_dir, "pkg")
            os.makedirs(noise_dir)
            os.makedirs(signal_dir)

            noise_path = os.path.join(noise_dir, "cached.txt")
            kept_path = os.path.join(signal_dir, "payload.py")
            for path, content in ((noise_path, b"noise"), (kept_path, b"print('payload')")):
                with open(path, "wb") as f:
                    f.write(content)

            candidates = hunter.analyze(
                analysis_data={
                    "extract_dir": extract_dir,
                    "extracted_candidates": [noise_path],
                }
            )

        self.assertEqual([candidate["path"] for candidate in candidates], [os.path.abspath(kept_path)])
        self.assertEqual(candidates[0]["provenance"], ["extract_dir"])

    def test_hunter_skips_low_value_fallback_bytecode_when_source_exists(self):
        hunter = NextStageHunterAgent()

        with tempfile.TemporaryDirectory() as extract_dir:
            source_path = os.path.join(extract_dir, "payload.py")
            bytecode_path = os.path.join(extract_dir, "payload.pyc")
            retained_bytecode_path = os.path.join(extract_dir, "module.pyc")
            for path, content in (
                (source_path, b"print('payload')"),
                (bytecode_path, b"compiled"),
                (retained_bytecode_path, b"compiled-module"),
            ):
                with open(path, "wb") as f:
                    f.write(content)

            candidates = hunter.analyze(
                analysis_data={
                    "extract_dir": extract_dir,
                }
            )

        self.assertEqual(
            [candidate["path"] for candidate in candidates],
            sorted([os.path.abspath(source_path), os.path.abspath(retained_bytecode_path)]),
        )
        self.assertNotIn(os.path.abspath(bytecode_path), [candidate["path"] for candidate in candidates])


class OrchestratorNextStageTests(unittest.IsolatedAsyncioTestCase):

    async def test_analyze_recurses_into_artifact_registry_next_stage_artifacts(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".py", delete=False) as initial_file:
            initial_file.write(b"print('root')")
            initial_path = initial_file.name

        with tempfile.TemporaryDirectory() as extract_dir:
            payload_path = os.path.join(extract_dir, "payload.exe")
            with open(payload_path, "wb") as f:
                f.write(b"MZpayload")

            try:
                orchestrator = build_orchestrator()
                orchestrator.die_handler.identify.side_effect = [
                    ({"packer": "pyinstaller"}, AnalysisType.PYTHON_SCRIPT),
                    ({"compiler": "msvc"}, AnalysisType.NATIVE),
                ]

                script_agent = Mock()
                script_agent.analyze = AsyncMock(side_effect=build_script_result_for_path(initial_path, extract_dir))
                native_agent = Mock()
                native_agent.analyze = AsyncMock(side_effect=build_native_result_for_path(payload_path))

                with patch("main.ScriptAgent", return_value=script_agent), patch("main.NativeAgent", return_value=native_agent):
                    result = await orchestrator.analyze(initial_path, run_id="test-run")

                self.assertEqual(len(result["next_stage_results"]), 1)
                self.assertEqual(result["next_stage_results"][0]["file_path"], os.path.abspath(payload_path))
                self.assertEqual(result["next_stage_results"][0]["detected_type"], "NATIVE")

                next_stage_events = [event for event in result["pipeline_log"] if event["stage"] == "next_stage"]
                self.assertEqual([event["state"] for event in next_stage_events], ["queued", "started", "completed"])
                queued_event, started_event, completed_event = next_stage_events
                self.assertEqual(queued_event["display_stage"], "Analyze")
                self.assertEqual(queued_event["data"]["source_stage"], "Unpack")
                self.assertEqual(queued_event["data"]["target_stage"], "Analyze")
                self.assertEqual(queued_event["data"]["transition_label"], "Unpack DONE -> Analyze")
                self.assertEqual(queued_event["data"]["parent_path"], os.path.abspath(initial_path))
                self.assertEqual(queued_event["data"]["file_path"], os.path.abspath(payload_path))
                self.assertEqual(started_event["state"], "started")
                self.assertEqual(started_event["display_stage"], "Analyze")
                self.assertEqual(started_event["data"]["source_stage"], "Unpack")
                self.assertEqual(started_event["data"]["target_stage"], "Analyze")
                self.assertEqual(started_event["data"]["transition_label"], "Unpack DONE -> Analyze")
                self.assertEqual(started_event["data"]["parent_path"], os.path.abspath(initial_path))
                self.assertEqual(started_event["data"]["file_path"], os.path.abspath(payload_path))
                self.assertEqual(completed_event["state"], "completed")
                self.assertEqual(completed_event["data"]["parent_path"], os.path.abspath(initial_path))
                self.assertEqual(completed_event["data"]["file_path"], os.path.abspath(payload_path))
                self.assertEqual(queued_event["data"]["task_id"], started_event["data"]["task_id"])
                self.assertEqual(started_event["data"]["task_id"], completed_event["data"]["task_id"])
                self.assertLess(queued_event["sequence"], started_event["sequence"])
                self.assertLess(started_event["sequence"], completed_event["sequence"])
                self.assertEqual(started_event["data"]["parent_task_id"], queued_event["data"]["parent_task_id"])
                self.assertEqual(completed_event["data"]["parent_task_id"], queued_event["data"]["parent_task_id"])
                self.assertEqual(started_event["data"]["session_id"], queued_event["data"]["session_id"])
                self.assertEqual(completed_event["data"]["session_id"], queued_event["data"]["session_id"])
                self.assertEqual(started_event["data"]["executor_kind"], "local")
                self.assertEqual(completed_event["data"]["executor_kind"], "local")
                self.assertEqual(started_event["data"]["parent_task_id"], completed_event["data"]["parent_task_id"])
                self.assertEqual(completed_event["data"]["artifact_id"], result["next_stage_results"][0]["artifacts"][0]["id"] if "artifacts" in result["next_stage_results"][0] else completed_event["data"]["artifact_id"])
                self.assertNotIn("artifacts", result["next_stage_results"][0])
                self.assertNotIn("findings", result["next_stage_results"][0])
                self.assertNotIn("iocs", result["next_stage_results"][0])
                self.assertNotIn("verdict", result["next_stage_results"][0])
                self.assertNotIn("final_report_markdown", result["next_stage_results"][0])
                native_agent.analyze.assert_awaited_once()
            finally:
                os.unlink(initial_path)

    async def test_analyze_recurses_into_extracted_next_stage_artifacts(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".exe", delete=False) as initial_file:
            initial_file.write(b"MZinitial")
            initial_path = initial_file.name

        with tempfile.TemporaryDirectory() as extract_dir:
            payload_path = os.path.join(extract_dir, "payload.exe")
            with open(payload_path, "wb") as f:
                f.write(b"MZpayload")

            try:
                orchestrator = HyperAgentOrchestrator.__new__(HyperAgentOrchestrator)
                orchestrator.config_path = "config.yaml"
                orchestrator.config = {}
                orchestrator.die_handler = Mock()
                orchestrator.die_handler.identify.side_effect = [
                    ({"packer": "pyinstaller"}, AnalysisType.PYTHON_SCRIPT),
                    ({"compiler": "msvc"}, AnalysisType.NATIVE),
                ]

                script_agent = AsyncMock()
                script_agent.analyze.return_value = {"extract_dir": extract_dir}
                native_agent = AsyncMock()
                native_agent.analyze.return_value = {"ai_analysis_report": "**Start of Analysis**\nOK\n**End of Analysis**"}

                with patch("main.ScriptAgent", return_value=script_agent), patch("main.NativeAgent", return_value=native_agent):
                    result = await orchestrator.analyze(initial_path, run_id="test-run")

                self.assertEqual(len(result["next_stage_results"]), 1)
                self.assertEqual(result["next_stage_results"][0]["file_path"], os.path.abspath(payload_path))
                self.assertEqual(result["next_stage_results"][0]["detected_type"], "NATIVE")
                self.assertNotIn("artifacts", result["next_stage_results"][0])
                self.assertNotIn("findings", result["next_stage_results"][0])
                self.assertNotIn("iocs", result["next_stage_results"][0])
                self.assertNotIn("verdict", result["next_stage_results"][0])
                self.assertNotIn("final_report_markdown", result["next_stage_results"][0])
                native_agent.analyze.assert_awaited_once()
            finally:
                os.unlink(initial_path)

    async def test_analyze_deduplicates_next_stage_candidates(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".py", delete=False) as initial_file:
            initial_file.write(b"print('root')")
            initial_path = initial_file.name

        with tempfile.TemporaryDirectory() as extract_dir:
            payload_path = os.path.join(extract_dir, "payload.exe")
            with open(payload_path, "wb") as f:
                f.write(b"MZpayload")

            try:
                orchestrator = HyperAgentOrchestrator.__new__(HyperAgentOrchestrator)
                orchestrator.config_path = "config.yaml"
                orchestrator.config = {}
                orchestrator.die_handler = Mock()
                orchestrator.die_handler.identify.side_effect = [
                    ({"packer": "pyinstaller"}, AnalysisType.PYTHON_SCRIPT),
                    ({"compiler": "msvc"}, AnalysisType.NATIVE),
                ]

                script_agent = AsyncMock()
                script_agent.analyze.return_value = {"extract_dir": extract_dir, "source_directory": extract_dir}
                native_agent = AsyncMock()
                native_agent.analyze.return_value = {"ai_analysis_report": "**Start of Analysis**\nOK\n**End of Analysis**"}

                with patch("main.ScriptAgent", return_value=script_agent), patch("main.NativeAgent", return_value=native_agent):
                    result = await orchestrator.analyze(initial_path, run_id="test-run")

                self.assertEqual(len(result["next_stage_results"]), 1)
                self.assertEqual(result["next_stage_results"][0]["file_path"], os.path.abspath(payload_path))
                native_agent.analyze.assert_awaited_once()
            finally:
                os.unlink(initial_path)

    async def test_analyze_deduplicates_next_stage_candidates_by_hash(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".py", delete=False) as initial_file:
            initial_file.write(b"print('root')")
            initial_path = initial_file.name

        with tempfile.TemporaryDirectory() as extract_dir:
            alpha_path = os.path.join(extract_dir, "alpha.exe")
            beta_path = os.path.join(extract_dir, "beta.exe")
            payload_bytes = b"MZsame-payload"
            payload_hash = hashlib.sha256(payload_bytes).hexdigest()
            for path in (alpha_path, beta_path):
                with open(path, "wb") as f:
                    f.write(payload_bytes)

            async def build_script_result(*args, run_context=None, **kwargs):
                input_artifact = ArtifactNode(
                    path=os.path.abspath(initial_path),
                    sha256="script-hash",
                    depth=run_context.depth if run_context else 0,
                    kind="script_input",
                )
                child_artifact = ArtifactNode(
                    path=os.path.abspath(alpha_path),
                    sha256=payload_hash,
                    parent_id=input_artifact.id,
                    depth=(run_context.depth + 1) if run_context else 1,
                    kind="native_input",
                )
                result = AgentResult(
                    artifact_id=input_artifact.id,
                    legacy_payload={
                        "extracted_candidates": [beta_path],
                        "ai_analysis_report": "**Start of Analysis**\nOK\n**End of Analysis**",
                    },
                    artifacts=[input_artifact, child_artifact],
                    findings=[],
                )
                if run_context and run_context.artifact_registry:
                    run_context.artifact_registry.add(input_artifact)
                    run_context.artifact_registry.add(child_artifact)
                return result

            try:
                orchestrator = build_orchestrator()
                orchestrator.die_handler.identify.side_effect = [
                    ({"packer": "pyinstaller"}, AnalysisType.PYTHON_SCRIPT),
                    ({"compiler": "msvc"}, AnalysisType.NATIVE),
                ]

                script_agent = Mock()
                script_agent.analyze = AsyncMock(side_effect=build_script_result)
                native_agent = Mock()
                native_agent.analyze = AsyncMock(side_effect=build_native_result_for_path(alpha_path))

                with patch("main.ScriptAgent", return_value=script_agent), patch("main.NativeAgent", return_value=native_agent):
                    result = await orchestrator.analyze(initial_path, run_id="test-run")

                self.assertEqual(len(result["next_stage_results"]), 1)
                self.assertEqual(result["next_stage_results"][0]["file_path"], os.path.abspath(alpha_path))
                native_agent.analyze.assert_awaited_once()
            finally:
                os.unlink(initial_path)

    async def test_analyze_prioritizes_high_signal_candidates_before_top_ten_cap(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".py", delete=False) as initial_file:
            initial_file.write(b"print('root')")
            initial_path = initial_file.name

        with tempfile.TemporaryDirectory() as extract_dir:
            registry_path = os.path.join(extract_dir, "z-registry.exe")
            with open(registry_path, "wb") as f:
                f.write(b"MZregistry")

            extracted_paths = []
            for index in range(10):
                path = os.path.join(extract_dir, f"a{index:02d}.exe")
                with open(path, "wb") as f:
                    f.write(f"MZ{index}".encode())
                extracted_paths.append(path)

            async def build_script_result(*args, run_context=None, **kwargs):
                input_artifact = ArtifactNode(
                    path=os.path.abspath(initial_path),
                    sha256="script-hash",
                    depth=run_context.depth if run_context else 0,
                    kind="script_input",
                )
                child_artifact = ArtifactNode(
                    path=os.path.abspath(registry_path),
                    sha256="registry-hash",
                    parent_id=input_artifact.id,
                    depth=(run_context.depth + 1) if run_context else 1,
                    kind="native_input",
                )
                result = AgentResult(
                    artifact_id=input_artifact.id,
                    legacy_payload={
                        "extracted_candidates": extracted_paths,
                        "ai_analysis_report": "**Start of Analysis**\nOK\n**End of Analysis**",
                    },
                    artifacts=[input_artifact, child_artifact],
                    findings=[],
                )
                if run_context and run_context.artifact_registry:
                    run_context.artifact_registry.add(input_artifact)
                    run_context.artifact_registry.add(child_artifact)
                return result

            def identify(path):
                if os.path.abspath(path) == os.path.abspath(initial_path):
                    return ({"packer": "pyinstaller"}, AnalysisType.PYTHON_SCRIPT)
                return ({"compiler": "msvc"}, AnalysisType.NATIVE)

            async def build_native_result(path, run_context=None, **kwargs):
                return build_native_agent_result(path, run_context.depth if run_context else 0)

            try:
                orchestrator = build_orchestrator()
                orchestrator.die_handler.identify.side_effect = identify

                script_agent = Mock()
                script_agent.analyze = AsyncMock(side_effect=build_script_result)
                native_agent = Mock()
                native_agent.analyze = AsyncMock(side_effect=build_native_result)

                with patch("main.ScriptAgent", return_value=script_agent), patch("main.NativeAgent", return_value=native_agent):
                    result = await orchestrator.analyze(initial_path, run_id="test-run")

                next_stage_paths = [child["file_path"] for child in result["next_stage_results"]]
                self.assertEqual(len(next_stage_paths), 10)
                self.assertIn(os.path.abspath(registry_path), next_stage_paths)
                self.assertNotIn(os.path.abspath(extracted_paths[-1]), next_stage_paths)
                self.assertEqual(next_stage_paths[0], os.path.abspath(registry_path))
                self.assertEqual(native_agent.analyze.await_count, 10)
            finally:
                os.unlink(initial_path)

    async def test_queue_prioritizes_high_signal_artifact_from_later_branch(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".py", delete=False) as initial_file:
            initial_file.write(b"print('root')")
            initial_path = initial_file.name

        with tempfile.TemporaryDirectory() as extract_dir:
            low_path = os.path.join(extract_dir, "a-low.exe")
            high_path = os.path.join(extract_dir, "z-high.exe")
            for path, content in ((low_path, b"MZlow"), (high_path, b"MZhigh")):
                with open(path, "wb") as f:
                    f.write(content)

            analysis_order: list[str] = []

            async def build_root_result(*args, run_context=None, **kwargs):
                artifact = ArtifactNode(
                    path=os.path.abspath(initial_path),
                    sha256="root-hash",
                    depth=run_context.depth if run_context else 0,
                    kind="script_input",
                )
                result = AgentResult(
                    artifact_id=artifact.id,
                    legacy_payload={
                        "extracted_candidates": [low_path],
                        "ai_analysis_report": "**Start of Analysis**\nOK\n**End of Analysis**",
                    },
                    artifacts=[artifact],
                    findings=[],
                )
                if run_context and run_context.artifact_registry:
                    run_context.artifact_registry.add(artifact)
                return result

            async def build_low_result(path, run_context=None, **kwargs):
                analysis_order.append(os.path.abspath(path))
                artifact = ArtifactNode(
                    path=os.path.abspath(path),
                    sha256="low-hash",
                    depth=run_context.depth if run_context else 0,
                    kind="native_input",
                )
                result = AgentResult(
                    artifact_id=artifact.id,
                    legacy_payload={
                        "extracted_candidates": [high_path],
                        "ai_analysis_report": "**Start of Analysis**\nOK\n**End of Analysis**",
                    },
                    artifacts=[artifact],
                    findings=[],
                )
                if run_context and run_context.artifact_registry:
                    run_context.artifact_registry.add(artifact)
                return result

            async def build_high_result(path, run_context=None, **kwargs):
                analysis_order.append(os.path.abspath(path))
                artifact = ArtifactNode(
                    path=os.path.abspath(path),
                    sha256="high-hash",
                    depth=run_context.depth if run_context else 0,
                    kind="native_input",
                )
                result = AgentResult(
                    artifact_id=artifact.id,
                    legacy_payload={
                        "ai_analysis_report": "**Start of Analysis**\nOK\n**End of Analysis**",
                        "priority_pyasm_files": [high_path],
                    },
                    artifacts=[artifact],
                    findings=[],
                )
                if run_context and run_context.artifact_registry:
                    run_context.artifact_registry.add(artifact)
                return result

            def identify(path):
                if os.path.abspath(path) == os.path.abspath(initial_path):
                    return ({"packer": "pyinstaller"}, AnalysisType.PYTHON_SCRIPT)
                return ({"compiler": "msvc"}, AnalysisType.NATIVE)

            async def run_native(path, run_context=None, **kwargs):
                abs_path = os.path.abspath(path)
                if abs_path == os.path.abspath(low_path):
                    return await build_low_result(path, run_context=run_context, **kwargs)
                return await build_high_result(path, run_context=run_context, **kwargs)

            try:
                orchestrator = build_orchestrator()
                orchestrator.die_handler.identify.side_effect = identify

                script_agent = Mock()
                script_agent.analyze = AsyncMock(side_effect=build_root_result)
                native_agent = Mock()
                native_agent.analyze = AsyncMock(side_effect=run_native)

                with patch("main.ScriptAgent", return_value=script_agent), patch("main.NativeAgent", return_value=native_agent):
                    result = await orchestrator.analyze(initial_path, run_id="test-run")

                self.assertEqual(analysis_order, [os.path.abspath(low_path), os.path.abspath(high_path)])
                self.assertEqual(
                    [child["file_path"] for child in result["next_stage_results"]],
                    [os.path.abspath(low_path)],
                )
                self.assertEqual(
                    [child["file_path"] for child in result["next_stage_results"][0]["next_stage_results"]],
                    [os.path.abspath(high_path)],
                )
            finally:
                os.unlink(initial_path)


if __name__ == "__main__":
    unittest.main()
