from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


PipelineEvent = dict[str, Any]
PipelineListener = Callable[[PipelineEvent], None]

_STAGE_LABELS = {
    "request": "Request",
    "identify": "Identify",
    "route": "Route",
    "agent": "Analyze",
    "next_stage": "Analyze",
    "next_stage_hunter": "Hunt",
    "response": "Complete",
    "claude_runner": "Analyze",
    "script_agent": "Analyze",
    "script_agent.extract": "Unpack",
    "script_agent.disassemble": "Disassemble",
    "script_agent.claude": "Analyze",
    "native_agent": "Analyze",
    "native_agent.claude": "Analyze",
    "native_agent.cleanup": "Cleanup",
    "dotnet_agent": "Analyze",
    "dotnet_agent.de4dot": "Cleanup",
    "dotnet_agent.decompile": "Decompile",
    "dotnet_agent.claude": "Analyze",
    "behavior_analyzer": "Behavior",
    "obfuscation_analyzer": "Obfuscation",
    "config_extractor": "Config",
    "ioc_extractor": "IOC",
    "capability_mapper": "Capability",
    "report_synthesizer": "Synthesize",
    "risk_scoring": "Score",
}


@dataclass
class PipelineLogger:
    run_id: str
    events: list[PipelineEvent] = field(default_factory=list)
    listeners: list[PipelineListener] = field(default_factory=list)
    _sequence: int = 0

    def subscribe(self, listener: PipelineListener) -> None:
        self.listeners.append(listener)

    def _display_stage(self, stage: str, data: dict[str, Any]) -> str:
        explicit = data.get("display_stage")
        if isinstance(explicit, str) and explicit:
            return explicit
        if stage in _STAGE_LABELS:
            return _STAGE_LABELS[stage]
        root_stage = stage.split(".", 1)[0]
        if root_stage in _STAGE_LABELS:
            return _STAGE_LABELS[root_stage]
        return root_stage.replace("_", " ").title()

    def _transition_label(self, data: dict[str, Any], state: str) -> str | None:
        explicit = data.get("transition_label")
        if isinstance(explicit, str) and explicit:
            return explicit

        source_stage = data.get("source_stage")
        target_stage = data.get("target_stage")
        if not isinstance(source_stage, str) or not isinstance(target_stage, str):
            return None

        source_status = data.get("source_status")
        if not isinstance(source_status, str) or not source_status:
            source_status = "DONE" if state == "started" else state.upper()
        return f"{source_stage} {source_status} -> {target_stage}"

    def log(self, stage: str, state: str, message: str, **data: Any) -> PipelineEvent:
        normalized_data = dict(data)
        self._sequence += 1

        event: PipelineEvent = {
            "run_id": self.run_id,
            "sequence": self._sequence,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "state": state,
            "status_label": state,
            "display_stage": self._display_stage(stage, normalized_data),
            "message": message,
        }

        transition_label = self._transition_label(normalized_data, state)
        if transition_label:
            normalized_data["transition_label"] = transition_label

        if normalized_data:
            event["data"] = normalized_data
        self.events.append(event)

        line = f"[PIPELINE][{self.run_id}][{stage}][{state}] {message}"
        if normalized_data:
            rendered = ", ".join(f"{key}={value}" for key, value in normalized_data.items())
            line = f"{line} | {rendered}"
        print(line)

        payload = deepcopy(event)
        for listener in list(self.listeners):
            try:
                listener(payload)
            except Exception:
                continue
        return event

    def snapshot(self) -> list[PipelineEvent]:
        return deepcopy(self.events)
