from __future__ import annotations

import hashlib
import os
from typing import Any

from core.artifact_registry import ArtifactRegistry
from core.pipeline_logger import PipelineLogger


class NextStageHunterAgent:
    _SUPPORTED_EXTENSIONS = (".exe", ".dll", ".scr", ".sys", ".py", ".pyc", ".pyo")
    _STRUCTURED_SIGNAL_PRIORITIES = {
        "artifact_registry": 30,
        "extracted_candidates": 20,
        "priority_pyasm_files": 10,
    }
    _IGNORED_DIRECTORY_NAMES = {
        "__pycache__",
        "site-packages",
        "dist-packages",
        ".git",
        ".venv",
        "venv",
    }
    _IGNORED_DIRECTORY_SUFFIXES = (".dist-info", ".egg-info")

    def _should_skip_directory(self, directory_name: str) -> bool:
        lowered = directory_name.lower()
        return lowered in self._IGNORED_DIRECTORY_NAMES or lowered.endswith(self._IGNORED_DIRECTORY_SUFFIXES)

    def _prune_noise_directories(self, directories: list[str]) -> None:
        directories[:] = [directory for directory in directories if not self._should_skip_directory(directory)]

    def _fallback_directory_sources(self, analysis_data: dict[str, Any]) -> list[tuple[str, str]]:
        sources: list[tuple[str, str]] = []
        for source_key in ("extract_dir", "source_directory"):
            source_path = analysis_data.get(source_key)
            if not isinstance(source_path, str) or not os.path.isdir(source_path):
                continue
            sources.append((source_key, source_path))
        return sources

    def _should_skip_low_value_fallback_file(self, file_name: str, sibling_names: set[str]) -> bool:
        lowered = file_name.lower()
        if lowered.endswith((".pyc", ".pyo")):
            stem, _ = os.path.splitext(lowered)
            return f"{stem}.py" in sibling_names
        return False

    def _fallback_candidates_for_source(
        self,
        candidates_by_path: dict[str, dict[str, Any]],
        *,
        source_key: str,
        source_path: str,
        artifact_registry: ArtifactRegistry | None,
    ) -> None:
        for root, directories, files in os.walk(source_path):
            self._prune_noise_directories(directories)
            sibling_names = {name.lower() for name in files}
            for name in files:
                if self._should_skip_low_value_fallback_file(name, sibling_names):
                    continue
                self._add_candidate(
                    candidates_by_path,
                    path=os.path.join(root, name),
                    provenance=source_key,
                    priority=0,
                    artifact_registry=artifact_registry,
                )

    def _supports_path(self, path: str) -> bool:
        return os.path.isfile(path) and path.lower().endswith(self._SUPPORTED_EXTENSIONS)

    def _get_candidate_sha256(
        self,
        path: str,
        *,
        artifact_registry: ArtifactRegistry | None,
    ) -> str | None:
        artifact = artifact_registry.get_by_path(path) if artifact_registry else None
        if artifact and artifact.sha256:
            return artifact.sha256
        try:
            sha256_hash = hashlib.sha256()
            with open(path, "rb") as handle:
                for byte_block in iter(lambda: handle.read(65536), b""):
                    sha256_hash.update(byte_block)
        except OSError:
            return None
        return sha256_hash.hexdigest()

    def _add_candidate(
        self,
        candidates_by_path: dict[str, dict[str, Any]],
        *,
        path: str,
        provenance: str,
        priority: int,
        artifact_registry: ArtifactRegistry | None,
    ) -> None:
        abs_path = os.path.abspath(path)
        if not self._supports_path(abs_path):
            return

        canonical_path = os.path.normcase(abs_path)
        sha256 = self._get_candidate_sha256(abs_path, artifact_registry=artifact_registry)
        candidate = candidates_by_path.get(canonical_path)
        if candidate is None:
            candidates_by_path[canonical_path] = {
                "path": abs_path,
                "canonical_path": canonical_path,
                "sha256": sha256,
                "priority": priority,
                "provenance": [provenance],
            }
            return

        candidate["priority"] = max(candidate["priority"], priority)
        if sha256 and not candidate.get("sha256"):
            candidate["sha256"] = sha256
        if provenance not in candidate["provenance"]:
            candidate["provenance"].append(provenance)

    def _deduplicate_by_sha256(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduplicated: list[dict[str, Any]] = []
        candidates_by_sha256: dict[str, dict[str, Any]] = {}

        for candidate in candidates:
            sha256 = candidate.get("sha256")
            if not isinstance(sha256, str) or not sha256:
                deduplicated.append(candidate)
                continue

            existing = candidates_by_sha256.get(sha256)
            if existing is None:
                candidates_by_sha256[sha256] = candidate
                deduplicated.append(candidate)
                continue

            existing_priority = existing["priority"]
            incoming_priority = candidate["priority"]
            should_replace = incoming_priority > existing_priority or (
                incoming_priority == existing_priority and candidate["path"] < existing["path"]
            )

            existing["priority"] = max(existing_priority, incoming_priority)
            if should_replace:
                existing["path"] = candidate["path"]
                existing["canonical_path"] = candidate["canonical_path"]
            for provenance in candidate["provenance"]:
                if provenance not in existing["provenance"]:
                    existing["provenance"].append(provenance)

        return sorted(deduplicated, key=lambda candidate: (-candidate["priority"], candidate["path"]))

    def _add_artifact_registry_candidates(
        self,
        candidates_by_path: dict[str, dict[str, Any]],
        *,
        artifact_id: str | None,
        artifact_registry: ArtifactRegistry | None,
    ) -> None:
        if not artifact_id or artifact_registry is None:
            return

        stack = [artifact_id]
        seen_artifact_ids: set[str] = set()
        while stack:
            current_artifact_id = stack.pop()
            if current_artifact_id in seen_artifact_ids:
                continue
            seen_artifact_ids.add(current_artifact_id)

            for child in artifact_registry.get_children(current_artifact_id):
                stack.append(child.id)
                self._add_candidate(
                    candidates_by_path,
                    path=child.path,
                    provenance="artifact_registry",
                    priority=self._STRUCTURED_SIGNAL_PRIORITIES["artifact_registry"],
                    artifact_registry=artifact_registry,
                )

    def _add_structured_field_candidates(
        self,
        candidates_by_path: dict[str, dict[str, Any]],
        *,
        analysis_data: dict[str, Any],
        field: str,
        artifact_registry: ArtifactRegistry | None,
    ) -> None:
        values = analysis_data.get(field)
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            return

        for value in values:
            if not isinstance(value, str):
                continue
            self._add_candidate(
                candidates_by_path,
                path=value,
                provenance=field,
                priority=self._STRUCTURED_SIGNAL_PRIORITIES[field],
                artifact_registry=artifact_registry,
            )

    def _add_directory_scan_candidates(
        self,
        candidates_by_path: dict[str, dict[str, Any]],
        *,
        analysis_data: dict[str, Any],
        artifact_registry: ArtifactRegistry | None,
    ) -> None:
        for source_key, source_path in self._fallback_directory_sources(analysis_data):
            self._fallback_candidates_for_source(
                candidates_by_path,
                source_key=source_key,
                source_path=source_path,
                artifact_registry=artifact_registry,
            )

    def analyze(
        self,
        *,
        analysis_data: Any,
        artifact_id: str | None = None,
        artifact_registry: ArtifactRegistry | None = None,
        pipeline_logger: PipelineLogger | None = None,
    ) -> list[dict[str, Any]]:
        if not isinstance(analysis_data, dict):
            return []

        if pipeline_logger:
            pipeline_logger.log(
                "next_stage_hunter",
                "started",
                "Scanning next-stage candidate directories",
            )

        candidates_by_path: dict[str, dict[str, Any]] = {}
        self._add_artifact_registry_candidates(
            candidates_by_path,
            artifact_id=artifact_id,
            artifact_registry=artifact_registry,
        )
        self._add_structured_field_candidates(
            candidates_by_path,
            analysis_data=analysis_data,
            field="extracted_candidates",
            artifact_registry=artifact_registry,
        )
        self._add_structured_field_candidates(
            candidates_by_path,
            analysis_data=analysis_data,
            field="priority_pyasm_files",
            artifact_registry=artifact_registry,
        )
        if not candidates_by_path:
            self._add_directory_scan_candidates(
                candidates_by_path,
                analysis_data=analysis_data,
                artifact_registry=artifact_registry,
            )

        candidates = self._deduplicate_by_sha256(
            sorted(candidates_by_path.values(), key=lambda candidate: candidate["path"])
        )

        if pipeline_logger:
            pipeline_logger.log(
                "next_stage_hunter",
                "completed",
                "Next-stage candidate scan completed",
                candidate_count=len(candidates),
            )

        return candidates
