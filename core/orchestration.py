from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from agents.behavior_analyzer_agent import BehaviorAnalyzerAgent
from agents.capability_mapper_agent import CapabilityMapperAgent
from agents.config_extractor_agent import ConfigExtractorAgent
from agents.file_classifier_agent import FileClassifierAgent
from agents.ioc_extractor_agent import IOCExtractorAgent
from agents.next_stage_hunter_agent import NextStageHunterAgent
from agents.obfuscation_analyzer_agent import ObfuscationAnalyzerAgent
from agents.report_synthesizer_agent import ReportSynthesizerAgent
from agents.risk_scoring_agent import RiskScoringAgent
from core.artifact_registry import ArtifactRegistry
from core.die_handler import AnalysisType, DIEHandler
from core.finding_store import FindingStore
from core.output_normalizer import build_orchestrator_response, build_public_run_summary, normalize_agent_result
from core.pipeline_logger import PipelineLogger
from core.result_models import AgentResult, Finding, RunContext
from core.work_queue import WorkItem, WorkQueue


class ArtifactGraphOrchestrator:
    _NEXT_STAGE_LABELS = {
        "artifact_registry": "Analyze",
        "extract_dir": "Unpack",
        "source_directory": "Decompile",
        "extracted_candidates": "Unpack",
        "priority_pyasm_files": "Disassemble",
    }
    _SPECIALIST_STAGE_LABELS = {
        "behavior_analyzer": "Behavior",
        "obfuscation_analyzer": "Obfuscation",
        "config_extractor": "Config",
        "ioc_extractor": "IOC",
        "capability_mapper": "Capability",
    }

    def __init__(
        self,
        config_path: str,
        die_handler: DIEHandler,
        pipeline_logger: PipelineLogger,
        artifact_registry: ArtifactRegistry,
        finding_store: FindingStore,
        agent_factory: Callable[[AnalysisType], Any],
        max_depth: int = 2,
    ):
        self.config_path = config_path
        self.die_handler = die_handler
        self.pipeline_logger = pipeline_logger
        self.artifact_registry = artifact_registry
        self.finding_store = finding_store
        self.agent_factory = agent_factory
        self.max_depth = max_depth
        self.file_classifier = FileClassifierAgent(config_path, die_handler=die_handler)
        self.behavior_analyzer = BehaviorAnalyzerAgent()
        self.obfuscation_analyzer = ObfuscationAnalyzerAgent()
        self.config_extractor = ConfigExtractorAgent()
        self.ioc_extractor = IOCExtractorAgent()
        self.capability_mapper = CapabilityMapperAgent()
        self.next_stage_hunter = NextStageHunterAgent()
        self.report_synthesizer = ReportSynthesizerAgent()
        self.risk_scoring_agent = RiskScoringAgent()

    def _next_stage_candidates(
        self,
        *,
        artifact_id: str | None,
        analysis_data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return self.next_stage_hunter.analyze(
            artifact_id=artifact_id,
            artifact_registry=self.artifact_registry,
            analysis_data=analysis_data,
            pipeline_logger=self.pipeline_logger,
        )[:10]

    def _link_result_parent(self, raw_result: Any, parent_artifact_id: str | None) -> str | None:
        if not isinstance(raw_result, AgentResult):
            return None
        if raw_result.artifact_id and parent_artifact_id:
            self.artifact_registry.set_parent(raw_result.artifact_id, parent_artifact_id)
        return raw_result.artifact_id

    def _infer_transition_source_stage(self, candidate: dict[str, Any]) -> str:
        provenance = candidate.get("provenance")
        if isinstance(provenance, list):
            for key in provenance:
                if isinstance(key, str) and key in self._NEXT_STAGE_LABELS:
                    return self._NEXT_STAGE_LABELS[key]
        return "Analyze"

    def _build_agent_log_data(
        self,
        *,
        file_path: str,
        analysis_type: AnalysisType,
        agent: Any,
        parent_artifact_id: str | None,
        depth: int,
    ) -> dict[str, Any]:
        return {
            "file_path": file_path,
            "detected_type": analysis_type.name,
            "agent": agent.__class__.__name__,
            "parent_artifact_id": parent_artifact_id,
            "depth": depth,
            "target_stage": "Analyze",
        }

    def _log_specialist_phase(self, stage: str, state: str, *, artifact_id: str | None, analysis_type: AnalysisType) -> None:
        self.pipeline_logger.log(
            stage,
            state,
            f"{stage.replace('_', ' ').title()} phase {state}",
            artifact_id=artifact_id,
            detected_type=analysis_type.name,
            target_stage=self._SPECIALIST_STAGE_LABELS.get(stage, stage.replace("_", " ").title()),
        )

    def _run_specialists(
        self,
        *,
        artifact_id: str | None,
        analysis_type: AnalysisType,
        analysis_data: Any,
        raw_result: Any,
    ) -> list[Finding]:
        existing_findings = self.finding_store.get(artifact_id) if artifact_id else []
        specialist_steps = [
            ("behavior_analyzer", self.behavior_analyzer.analyze, {}),
            ("obfuscation_analyzer", self.obfuscation_analyzer.analyze, {}),
            ("config_extractor", self.config_extractor.analyze, {}),
            ("ioc_extractor", self.ioc_extractor.analyze, {}),
            ("capability_mapper", self.capability_mapper.analyze, {}),
        ]

        findings: list[Finding] = []
        for stage_name, analyzer, extra_kwargs in specialist_steps:
            self._log_specialist_phase(stage_name, "started", artifact_id=artifact_id, analysis_type=analysis_type)
            kwargs = {
                "artifact_id": artifact_id,
                "analysis_type": analysis_type,
                "analysis_data": analysis_data,
                "pipeline_logger": self.pipeline_logger,
                **extra_kwargs,
            }
            if stage_name == "capability_mapper":
                kwargs["artifact_findings"] = [*existing_findings, *findings]
            step_findings = analyzer(**kwargs)
            if step_findings:
                findings.extend(step_findings)
            self._log_specialist_phase(stage_name, "completed", artifact_id=artifact_id, analysis_type=analysis_type)

        if not findings:
            return []
        self.finding_store.add_many(findings)
        if isinstance(raw_result, AgentResult):
            raw_result.findings.extend(findings)
        return findings

    def _run_report_synthesis(self, root_artifact_id: str | None) -> list[Finding]:
        self.pipeline_logger.log(
            "report_synthesizer",
            "started",
            "Report synthesis started",
            artifact_id=root_artifact_id,
            target_stage="Synthesize",
        )
        findings = self.report_synthesizer.analyze(
            root_artifact_id=root_artifact_id,
            artifact_registry=self.artifact_registry,
            finding_store=self.finding_store,
            pipeline_logger=self.pipeline_logger,
        )
        if findings:
            self.finding_store.add_many(findings)
        self.pipeline_logger.log(
            "report_synthesizer",
            "completed",
            "Report synthesis completed",
            artifact_id=root_artifact_id,
            finding_count=len(findings),
            target_stage="Synthesize",
        )
        return findings

    def _run_risk_scoring(self, root_artifact_id: str | None) -> list[Finding]:
        self.pipeline_logger.log(
            "risk_scoring",
            "started",
            "Risk scoring started",
            artifact_id=root_artifact_id,
            target_stage="Score",
        )
        findings = self.risk_scoring_agent.analyze(
            root_artifact_id=root_artifact_id,
            artifact_registry=self.artifact_registry,
            finding_store=self.finding_store,
            pipeline_logger=self.pipeline_logger,
        )
        if findings:
            self.finding_store.add_many(findings)
        self.pipeline_logger.log(
            "risk_scoring",
            "completed",
            "Risk scoring completed",
            artifact_id=root_artifact_id,
            finding_count=len(findings),
            target_stage="Score",
        )
        return findings

    def _collect_artifact_chain(self, root_artifact_id: str | None) -> list[Any]:
        if not root_artifact_id:
            return []

        ordered: list[Any] = []

        def visit(artifact_id: str) -> None:
            artifact = self.artifact_registry.get(artifact_id)
            if artifact is None:
                return
            ordered.append(artifact)
            for child in self.artifact_registry.get_children(artifact_id):
                visit(child.id)

        visit(root_artifact_id)
        return ordered

    def _log_next_stage_candidate(
        self,
        *,
        parent_path: str,
        parent_artifact_id: str | None,
        candidate: dict[str, Any],
        candidate_path: str,
        depth: int,
    ) -> None:
        source_stage = self._infer_transition_source_stage(candidate)
        self.pipeline_logger.log(
            "next_stage",
            "started",
            "Analyzing extracted next-stage artifact",
            file_path=candidate_path,
            parent_path=parent_path,
            parent_artifact_id=parent_artifact_id,
            candidate_depth=depth,
            priority=candidate.get("priority"),
            provenance=candidate.get("provenance"),
            source_stage=source_stage,
            target_stage="Analyze",
            transition_label=f"{source_stage} DONE -> Analyze",
        )

    def _log_next_stage_completed(
        self,
        *,
        file_path: str,
        parent_path: str,
        parent_artifact_id: str | None,
        artifact_id: str | None,
    ) -> None:
        self.pipeline_logger.log(
            "next_stage",
            "completed",
            "Next-stage artifact analysis completed",
            file_path=file_path,
            parent_path=parent_path,
            parent_artifact_id=parent_artifact_id,
            artifact_id=artifact_id,
            source_stage="Analyze",
            target_stage="Analyze",
        )

    async def analyze(
        self,
        file_path: str,
        run_id: str,
        initial_depth: int = 0,
        seen: set[str] | None = None,
    ) -> dict[str, Any]:
        root_abs_path = os.path.abspath(file_path)
        seen_paths = seen or set()
        if root_abs_path in seen_paths:
            self.pipeline_logger.log("request", "skipped", "File already analyzed in this run", file_path=root_abs_path)
            return {"run_id": run_id, "file_path": root_abs_path, "skipped": "already_analyzed"}

        queue = WorkQueue()
        queue.enqueue(WorkItem(path=root_abs_path, depth=initial_depth))
        seen_paths.add(root_abs_path)

        records_by_path: dict[str, dict[str, Any]] = {}
        children_by_path: dict[str, list[str]] = {}

        while queue:
            item = queue.dequeue()
            abs_path = os.path.abspath(item.path)
            self.pipeline_logger.log("request", "started", "Analysis request accepted", file_path=abs_path, depth=item.depth)
            self.pipeline_logger.log("identify", "started", "Detecting file type", file_path=abs_path, depth=item.depth)
            classification = self.file_classifier.analyze(abs_path)
            die_data = classification.die_data
            analysis_type = classification.analysis_type
            self.pipeline_logger.log(
                "identify",
                "completed",
                "File type detected",
                file_path=abs_path,
                detected_type=analysis_type.name,
                depth=item.depth,
            )

            run_context = RunContext(
                run_id=run_id,
                root_file_path=root_abs_path,
                detected_type=analysis_type.name,
                depth=item.depth,
                pipeline_logger=self.pipeline_logger,
                artifact_registry=self.artifact_registry,
                finding_store=self.finding_store,
            )

            agent = self.agent_factory(analysis_type)
            agent_log_data = self._build_agent_log_data(
                file_path=abs_path,
                analysis_type=analysis_type,
                agent=agent,
                parent_artifact_id=item.parent_artifact_id,
                depth=item.depth,
            )
            self.pipeline_logger.log(
                "route",
                "completed",
                "Agent selected",
                **agent_log_data,
            )
            self.pipeline_logger.log(
                "agent",
                "started",
                "Agent analysis started",
                **agent_log_data,
            )
            raw_result = await agent.analyze(
                abs_path,
                pipeline_logger=self.pipeline_logger,
                run_context=run_context,
            )
            current_artifact_id = self._link_result_parent(raw_result, item.parent_artifact_id)
            analysis_data = normalize_agent_result(raw_result)
            self._run_specialists(
                artifact_id=current_artifact_id,
                analysis_type=analysis_type,
                analysis_data=analysis_data,
                raw_result=raw_result,
            )
            self.pipeline_logger.log(
                "agent",
                "completed",
                "Agent analysis completed",
                artifact_id=current_artifact_id,
                **agent_log_data,
            )

            records_by_path[abs_path] = {
                "detected_type": analysis_type.name,
                "die": dict(die_data),
                "analysis_data": analysis_data,
            }
            if item.parent_path:
                children_by_path.setdefault(item.parent_path, []).append(abs_path)
                self._log_next_stage_completed(
                    file_path=abs_path,
                    parent_path=item.parent_path,
                    parent_artifact_id=item.parent_artifact_id,
                    artifact_id=current_artifact_id,
                )

            if isinstance(analysis_data, dict) and item.depth < self.max_depth:
                for candidate in self._next_stage_candidates(
                    artifact_id=current_artifact_id,
                    analysis_data=analysis_data,
                ):
                    candidate_path = candidate.get("path")
                    if not isinstance(candidate_path, str):
                        continue
                    canonical_path = candidate.get("canonical_path")
                    candidate_key = canonical_path if isinstance(canonical_path, str) else candidate_path
                    if candidate_path == abs_path or candidate_key in seen_paths:
                        continue
                    self._log_next_stage_candidate(
                        parent_path=abs_path,
                        parent_artifact_id=current_artifact_id,
                        candidate=candidate,
                        candidate_path=candidate_path,
                        depth=item.depth + 1,
                    )
                    candidate_priority = candidate.get("priority")
                    queue.enqueue(
                        WorkItem(
                            path=candidate_path,
                            depth=item.depth + 1,
                            parent_path=abs_path,
                            parent_artifact_id=current_artifact_id,
                            priority=candidate_priority if isinstance(candidate_priority, int) else 0,
                        )
                    )
                    seen_paths.add(candidate_key)
                    seen_paths.add(candidate_path)

        root_artifact = self.artifact_registry.get_by_path(root_abs_path)
        self._run_report_synthesis(root_artifact.id if root_artifact else None)
        self._run_risk_scoring(root_artifact.id if root_artifact else None)
        self.pipeline_logger.log("response", "completed", "Final response assembled", file_path=root_abs_path, target_stage="Complete")
        pipeline_log = self.pipeline_logger.snapshot()

        def build_tree(path: str) -> dict[str, Any]:
            record = records_by_path[path]
            return build_orchestrator_response(
                run_id=run_id,
                file_path=path,
                detected_type=record["detected_type"],
                die_data=record["die"],
                analysis_data=record["analysis_data"],
                next_stage_results=[build_tree(child) for child in children_by_path.get(path, [])],
                pipeline_log=pipeline_log,
            )

        result = build_tree(root_abs_path)
        root_artifact_id = root_artifact.id if root_artifact else None
        artifact_chain = self._collect_artifact_chain(root_artifact_id)
        public_summary = build_public_run_summary(
            artifacts=artifact_chain,
            findings=[finding for artifact in artifact_chain for finding in self.finding_store.get(artifact.id)],
            root_artifact_id=root_artifact_id,
        )
        result.update(public_summary)
        return result
