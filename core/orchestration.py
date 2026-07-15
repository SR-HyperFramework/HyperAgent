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
from core.result_models import AgentResult, Finding, RunContext, TaskSession
from core.task_runtime import TaskScopedPipelineLogger, bind_process_scope, executor_kind_for_stage
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

    def _root_request_task(self, run_id: str) -> TaskSession:
        snapshot = self.pipeline_logger.task_snapshot()
        task_kwargs: dict[str, Any] = {}
        if isinstance(snapshot.get("task_id"), str) and snapshot["task_id"]:
            task_kwargs["task_id"] = snapshot["task_id"]
        if isinstance(snapshot.get("session_id"), str) and snapshot["session_id"]:
            task_kwargs["session_id"] = snapshot["session_id"]
        parent_task_id = snapshot.get("parent_task_id") if isinstance(snapshot.get("parent_task_id"), str) else None
        executor_kind = snapshot.get("executor_kind") if isinstance(snapshot.get("executor_kind"), str) else "local"
        return TaskSession(
            run_id=run_id,
            stage_key="request",
            title="Run request",
            parent_task_id=parent_task_id,
            executor_kind=executor_kind,
            **task_kwargs,
        )

    def _create_task(
        self,
        *,
        run_id: str,
        stage_key: str,
        title: str,
        parent_task_id: str | None = None,
        executor_kind: str | None = None,
    ) -> TaskSession:
        return TaskSession(
            run_id=run_id,
            stage_key=stage_key,
            title=title,
            parent_task_id=parent_task_id,
            executor_kind=executor_kind or executor_kind_for_stage(stage_key),
        )

    def _task_logger(self, task: TaskSession) -> TaskScopedPipelineLogger:
        return TaskScopedPipelineLogger(self.pipeline_logger, task)

    def _annotate_findings(self, findings: list[Finding], *, task: TaskSession, origin_stage: str | None = None) -> list[Finding]:
        stage_name = origin_stage or task.stage_key
        for finding in findings:
            finding.producer_task_id = task.task_id
            finding.origin_stage = stage_name
        return findings

    def _annotate_agent_result(self, raw_result: Any, *, task: TaskSession) -> None:
        if not isinstance(raw_result, AgentResult):
            return
        raw_result.task_id = task.task_id
        raw_result.session_id = task.session_id
        raw_result.executor_kind = task.executor_kind
        for artifact in raw_result.artifacts:
            artifact.producer_task_id = task.task_id
            artifact.origin_stage = task.stage_key
        self._annotate_findings(raw_result.findings, task=task)

    def _next_stage_candidates(
        self,
        *,
        artifact_id: str | None,
        analysis_data: dict[str, Any],
        pipeline_logger: PipelineLogger | TaskScopedPipelineLogger | None = None,
    ) -> list[dict[str, Any]]:
        return self.next_stage_hunter.analyze(
            artifact_id=artifact_id,
            artifact_registry=self.artifact_registry,
            analysis_data=analysis_data,
            pipeline_logger=pipeline_logger,
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

    def _run_specialists(
        self,
        *,
        run_id: str,
        parent_task_id: str | None,
        artifact_id: str | None,
        analysis_type: AnalysisType,
        analysis_data: Any,
        raw_result: Any,
    ) -> list[Finding]:
        existing_findings = self.finding_store.get(artifact_id) if artifact_id else []
        specialist_steps = [
            ("behavior_analyzer", "Behavior analysis", self.behavior_analyzer.analyze, {}),
            ("obfuscation_analyzer", "Obfuscation analysis", self.obfuscation_analyzer.analyze, {}),
            ("config_extractor", "Config extraction", self.config_extractor.analyze, {}),
            ("ioc_extractor", "IOC extraction", self.ioc_extractor.analyze, {}),
            ("capability_mapper", "Capability mapping", self.capability_mapper.analyze, {}),
        ]

        findings: list[Finding] = []
        for stage_name, title, analyzer, extra_kwargs in specialist_steps:
            task = self._create_task(
                run_id=run_id,
                stage_key=stage_name,
                title=title,
                parent_task_id=parent_task_id,
            )
            task_logger = self._task_logger(task)
            task_logger.log(
                stage_name,
                "queued",
                f"Queued {title.lower()}",
                artifact_id=artifact_id,
                detected_type=analysis_type.name,
                target_stage=self._SPECIALIST_STAGE_LABELS.get(stage_name, stage_name.replace("_", " ").title()),
            )
            kwargs = {
                "artifact_id": artifact_id,
                "analysis_type": analysis_type,
                "analysis_data": analysis_data,
                "pipeline_logger": task_logger,
                **extra_kwargs,
            }
            if stage_name == "capability_mapper":
                kwargs["artifact_findings"] = [*existing_findings, *findings]
            try:
                step_findings = analyzer(**kwargs)
            except Exception as exc:
                task_logger.log(
                    stage_name,
                    "failed",
                    f"{title} failed",
                    artifact_id=artifact_id,
                    detected_type=analysis_type.name,
                    error=str(exc),
                )
                raise
            if step_findings:
                self._annotate_findings(step_findings, task=task, origin_stage=stage_name)
                task_logger.record_output(
                    {
                        "artifact_id": artifact_id,
                        "findings": [
                            {
                                "id": finding.id,
                                "artifact_id": finding.artifact_id,
                                "category": finding.category,
                                "summary": finding.summary,
                                "confidence": finding.confidence,
                            }
                            for finding in step_findings
                        ],
                    },
                    output_kind="findings",
                )
                findings.extend(step_findings)
            else:
                task_logger.log(
                    stage_name,
                    "completed",
                    f"{title} completed",
                    artifact_id=artifact_id,
                    detected_type=analysis_type.name,
                    finding_count=0,
                )

        if not findings:
            return []
        self.finding_store.add_many(findings)
        if isinstance(raw_result, AgentResult):
            raw_result.findings.extend(findings)
        return findings

    def _run_report_synthesis(self, *, run_id: str, parent_task_id: str | None, root_artifact_id: str | None) -> list[Finding]:
        task = self._create_task(
            run_id=run_id,
            stage_key="report_synthesizer",
            title="Report synthesis",
            parent_task_id=parent_task_id,
        )
        task_logger = self._task_logger(task)
        task_logger.log(
            "report_synthesizer",
            "queued",
            "Queued report synthesis",
            artifact_id=root_artifact_id,
            target_stage="Synthesize",
        )
        try:
            findings = self.report_synthesizer.analyze(
                root_artifact_id=root_artifact_id,
                artifact_registry=self.artifact_registry,
                finding_store=self.finding_store,
                pipeline_logger=task_logger,
            )
        except Exception as exc:
            task_logger.log(
                "report_synthesizer",
                "failed",
                "Report synthesis failed",
                artifact_id=root_artifact_id,
                error=str(exc),
                target_stage="Synthesize",
            )
            raise
        if findings:
            self._annotate_findings(findings, task=task, origin_stage="report_synthesizer")
            task_logger.record_output(
                {
                    "artifact_id": root_artifact_id,
                    "findings": [
                        {
                            "id": finding.id,
                            "artifact_id": finding.artifact_id,
                            "category": finding.category,
                            "summary": finding.summary,
                            "confidence": finding.confidence,
                        }
                        for finding in findings
                    ],
                },
                output_kind="findings",
            )
            self.finding_store.add_many(findings)
        return findings

    def _run_risk_scoring(self, *, run_id: str, parent_task_id: str | None, root_artifact_id: str | None) -> list[Finding]:
        task = self._create_task(
            run_id=run_id,
            stage_key="risk_scoring",
            title="Risk scoring",
            parent_task_id=parent_task_id,
        )
        task_logger = self._task_logger(task)
        task_logger.log(
            "risk_scoring",
            "queued",
            "Queued risk scoring",
            artifact_id=root_artifact_id,
            target_stage="Score",
        )
        try:
            findings = self.risk_scoring_agent.analyze(
                root_artifact_id=root_artifact_id,
                artifact_registry=self.artifact_registry,
                finding_store=self.finding_store,
                pipeline_logger=task_logger,
            )
        except Exception as exc:
            task_logger.log(
                "risk_scoring",
                "failed",
                "Risk scoring failed",
                artifact_id=root_artifact_id,
                error=str(exc),
                target_stage="Score",
            )
            raise
        if findings:
            self._annotate_findings(findings, task=task, origin_stage="risk_scoring")
            task_logger.record_output(
                {
                    "artifact_id": root_artifact_id,
                    "findings": [
                        {
                            "id": finding.id,
                            "artifact_id": finding.artifact_id,
                            "category": finding.category,
                            "summary": finding.summary,
                            "confidence": finding.confidence,
                        }
                        for finding in findings
                    ],
                },
                output_kind="findings",
            )
            self.finding_store.add_many(findings)
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

    def _queue_next_stage_candidate(
        self,
        *,
        task: TaskSession,
        parent_path: str,
        parent_artifact_id: str | None,
        candidate: dict[str, Any],
        candidate_path: str,
        depth: int,
    ) -> None:
        source_stage = self._infer_transition_source_stage(candidate)
        self._task_logger(task).log(
            "next_stage",
            "queued",
            "Queued next-stage artifact analysis",
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

    def _log_next_stage_started(
        self,
        *,
        task: TaskSession,
        parent_path: str,
        parent_artifact_id: str | None,
        candidate: dict[str, Any],
        candidate_path: str,
        depth: int,
    ) -> None:
        source_stage = self._infer_transition_source_stage(candidate)
        self._task_logger(task).log(
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
        task: TaskSession,
        file_path: str,
        parent_path: str,
        parent_artifact_id: str | None,
        artifact_id: str | None,
    ) -> None:
        self._task_logger(task).log(
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
        root_request_task = self._root_request_task(run_id)
        root_request_logger = self._task_logger(root_request_task)

        if root_abs_path in seen_paths:
            root_request_logger.log("request", "skipped", "File already analyzed in this run", file_path=root_abs_path)
            return {"run_id": run_id, "file_path": root_abs_path, "skipped": "already_analyzed"}

        queue = WorkQueue()
        queue.enqueue(WorkItem(path=root_abs_path, depth=initial_depth, parent_task_id=root_request_task.task_id))
        seen_paths.add(root_abs_path)
        root_request_logger.log("request", "started", "Analysis request accepted", file_path=root_abs_path, depth=initial_depth)

        records_by_path: dict[str, dict[str, Any]] = {}
        children_by_path: dict[str, list[str]] = {}

        while queue:
            item = queue.dequeue()
            abs_path = os.path.abspath(item.path)

            if item.transition_task is not None and item.parent_path:
                self._log_next_stage_started(
                    task=item.transition_task,
                    parent_path=item.parent_path,
                    parent_artifact_id=item.parent_artifact_id,
                    candidate=item.transition_candidate or {},
                    candidate_path=abs_path,
                    depth=item.depth,
                )

            identify_task = self._create_task(
                run_id=run_id,
                stage_key="identify",
                title="Identify file",
                parent_task_id=item.parent_task_id,
            )
            identify_logger = self._task_logger(identify_task)
            identify_logger.log("identify", "started", "Detecting file type", file_path=abs_path, depth=item.depth)
            try:
                with bind_process_scope(pipeline_logger=identify_logger):
                    classification = self.file_classifier.analyze(abs_path)
            except Exception as exc:
                identify_logger.log("identify", "failed", "File type detection failed", file_path=abs_path, depth=item.depth, error=str(exc))
                raise
            die_data = classification.die_data
            analysis_type = classification.analysis_type
            identify_logger.record_output(
                {
                    "file_path": abs_path,
                    "detected_type": analysis_type.name,
                    "depth": item.depth,
                    "die": dict(die_data),
                },
                output_kind="classification",
            )
            identify_logger.log(
                "identify",
                "completed",
                "File type detected",
                file_path=abs_path,
                detected_type=analysis_type.name,
                depth=item.depth,
            )

            route_task = self._create_task(
                run_id=run_id,
                stage_key="route",
                title="Route analysis",
                parent_task_id=item.parent_task_id,
            )
            route_logger = self._task_logger(route_task)
            route_logger.log(
                "route",
                "started",
                "Selecting analysis agent",
                file_path=abs_path,
                detected_type=analysis_type.name,
                depth=item.depth,
            )
            try:
                agent = self.agent_factory(analysis_type)
            except Exception as exc:
                route_logger.log(
                    "route",
                    "failed",
                    "Agent selection failed",
                    file_path=abs_path,
                    detected_type=analysis_type.name,
                    depth=item.depth,
                    error=str(exc),
                )
                raise

            agent_log_data = self._build_agent_log_data(
                file_path=abs_path,
                analysis_type=analysis_type,
                agent=agent,
                parent_artifact_id=item.parent_artifact_id,
                depth=item.depth,
            )
            route_logger.record_output(
                {
                    "file_path": abs_path,
                    "detected_type": analysis_type.name,
                    "agent": agent.__class__.__name__,
                    "parent_artifact_id": item.parent_artifact_id,
                    "depth": item.depth,
                },
                output_kind="route_selection",
            )
            route_logger.log("route", "completed", "Agent selected", **agent_log_data)

            agent_task = self._create_task(
                run_id=run_id,
                stage_key="agent",
                title="Run coarse analysis",
                parent_task_id=item.parent_task_id,
            )
            agent_logger = self._task_logger(agent_task)
            run_context = RunContext(
                run_id=run_id,
                root_file_path=root_abs_path,
                detected_type=analysis_type.name,
                depth=item.depth,
                pipeline_logger=agent_logger,
                artifact_registry=self.artifact_registry,
                finding_store=self.finding_store,
                task_id=agent_task.task_id,
                session_id=agent_task.session_id,
                parent_task_id=agent_task.parent_task_id,
                executor_kind=agent_task.executor_kind,
            )

            agent_logger.log("agent", "started", "Agent analysis started", **agent_log_data)
            try:
                raw_result = await agent.analyze(
                    abs_path,
                    pipeline_logger=agent_logger,
                    run_context=run_context,
                )
            except Exception as exc:
                agent_logger.log("agent", "failed", "Agent analysis failed", error=str(exc), **agent_log_data)
                raise
            self._annotate_agent_result(raw_result, task=agent_task)
            current_artifact_id = self._link_result_parent(raw_result, item.parent_artifact_id)
            analysis_data = normalize_agent_result(raw_result)
            specialist_findings = self._run_specialists(
                run_id=run_id,
                parent_task_id=agent_task.task_id,
                artifact_id=current_artifact_id,
                analysis_type=analysis_type,
                analysis_data=analysis_data,
                raw_result=raw_result,
            )
            agent_output = {
                "artifact_id": current_artifact_id,
                "analysis_data": analysis_data,
            }
            if isinstance(raw_result, AgentResult):
                agent_output["artifacts"] = [
                    {
                        "id": artifact.id,
                        "path": artifact.path,
                        "kind": artifact.kind,
                        "parent_id": artifact.parent_id,
                        "depth": artifact.depth,
                        "sha256": artifact.sha256,
                    }
                    for artifact in raw_result.artifacts
                ]
                agent_output["findings"] = [
                    {
                        "id": finding.id,
                        "artifact_id": finding.artifact_id,
                        "category": finding.category,
                        "summary": finding.summary,
                        "confidence": finding.confidence,
                    }
                    for finding in raw_result.findings
                ]
            if specialist_findings:
                agent_output["specialist_findings"] = [
                    {
                        "id": finding.id,
                        "artifact_id": finding.artifact_id,
                        "category": finding.category,
                        "summary": finding.summary,
                        "confidence": finding.confidence,
                    }
                    for finding in specialist_findings
                ]
            agent_logger.record_output(agent_output, output_kind="agent_result")
            agent_logger.log(
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
            if item.transition_task is not None and item.parent_path:
                self._log_next_stage_completed(
                    task=item.transition_task,
                    file_path=abs_path,
                    parent_path=item.parent_path,
                    parent_artifact_id=item.parent_artifact_id,
                    artifact_id=current_artifact_id,
                )

            if isinstance(analysis_data, dict) and item.depth < self.max_depth:
                hunt_task = self._create_task(
                    run_id=run_id,
                    stage_key="next_stage_hunter",
                    title="Hunt next stage",
                    parent_task_id=agent_task.task_id,
                )
                hunt_logger = self._task_logger(hunt_task)
                try:
                    candidates = self._next_stage_candidates(
                        artifact_id=current_artifact_id,
                        analysis_data=analysis_data,
                        pipeline_logger=hunt_logger,
                    )
                    hunt_logger.record_output(
                        {
                            "artifact_id": current_artifact_id,
                            "candidates": [dict(candidate) for candidate in candidates],
                        },
                        output_kind="next_stage_candidates",
                    )
                except Exception as exc:
                    hunt_logger.log(
                        "next_stage_hunter",
                        "failed",
                        "Next-stage candidate scan failed",
                        artifact_id=current_artifact_id,
                        detected_type=analysis_type.name,
                        error=str(exc),
                    )
                    raise

                for candidate in candidates:
                    candidate_path = candidate.get("path")
                    if not isinstance(candidate_path, str):
                        continue
                    canonical_path = candidate.get("canonical_path")
                    candidate_key = canonical_path if isinstance(canonical_path, str) else candidate_path
                    if candidate_path == abs_path or candidate_key in seen_paths:
                        continue
                    transition_task = self._create_task(
                        run_id=run_id,
                        stage_key="next_stage",
                        title="Analyze next stage",
                        parent_task_id=agent_task.task_id,
                    )
                    self._queue_next_stage_candidate(
                        task=transition_task,
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
                            parent_task_id=transition_task.task_id,
                            priority=candidate_priority if isinstance(candidate_priority, int) else 0,
                            transition_task=transition_task,
                            transition_candidate=dict(candidate),
                        )
                    )
                    seen_paths.add(candidate_key)
                    seen_paths.add(candidate_path)

        root_artifact = self.artifact_registry.get_by_path(root_abs_path)
        self._run_report_synthesis(
            run_id=run_id,
            parent_task_id=root_request_task.task_id,
            root_artifact_id=root_artifact.id if root_artifact else None,
        )
        self._run_risk_scoring(
            run_id=run_id,
            parent_task_id=root_request_task.task_id,
            root_artifact_id=root_artifact.id if root_artifact else None,
        )
        root_request_logger.log("response", "completed", "Final response assembled", file_path=root_abs_path, target_stage="Complete")
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
