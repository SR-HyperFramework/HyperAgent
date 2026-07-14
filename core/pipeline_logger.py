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
    task_id: str | None = None
    session_id: str | None = None
    parent_task_id: str | None = None
    executor_kind: str | None = None
    events: list[PipelineEvent] = field(default_factory=list)
    listeners: list[PipelineListener] = field(default_factory=list)
    task_outputs: dict[str, Any] = field(default_factory=dict)
    _sequence: int = 0

    def bind_task(
        self,
        *,
        task_id: str | None = None,
        session_id: str | None = None,
        parent_task_id: str | None = None,
        executor_kind: str | None = None,
    ) -> None:
        if task_id is not None:
            self.task_id = task_id
        if session_id is not None:
            self.session_id = session_id
        if parent_task_id is not None:
            self.parent_task_id = parent_task_id
        if executor_kind is not None:
            self.executor_kind = executor_kind

    def _task_scope_data(self) -> dict[str, Any]:
        scoped: dict[str, Any] = {}
        if self.task_id is not None:
            scoped["task_id"] = self.task_id
        if self.session_id is not None:
            scoped["session_id"] = self.session_id
        if self.parent_task_id is not None:
            scoped["parent_task_id"] = self.parent_task_id
        if self.executor_kind is not None:
            scoped["executor_kind"] = self.executor_kind
        return scoped

    def task_snapshot(self) -> dict[str, Any]:
        return self._task_scope_data().copy()

    def child(
        self,
        *,
        task_id: str | None = None,
        session_id: str | None = None,
        parent_task_id: str | None = None,
        executor_kind: str | None = None,
    ) -> "PipelineLogger":
        return PipelineLogger(
            run_id=self.run_id,
            task_id=task_id if task_id is not None else self.task_id,
            session_id=session_id if session_id is not None else self.session_id,
            parent_task_id=parent_task_id if parent_task_id is not None else self.parent_task_id,
            executor_kind=executor_kind if executor_kind is not None else self.executor_kind,
            listeners=self.listeners,
            task_outputs=self.task_outputs,
        )

    def record_task_output(
        self,
        payload: Any,
        *,
        task_id: str | None = None,
        output_kind: str | None = None,
        merge: bool = False,
    ) -> dict[str, Any]:
        scoped_task_id = task_id if task_id is not None else self.task_id
        if not isinstance(scoped_task_id, str) or not scoped_task_id:
            raise ValueError("Task output requires a task_id")

        record = self.task_outputs.get(scoped_task_id)
        if not isinstance(record, dict):
            record = {}
            self.task_outputs[scoped_task_id] = record

        if output_kind is not None:
            record["output_kind"] = output_kind

        if merge and isinstance(record.get("result"), dict) and isinstance(payload, dict):
            record["result"] = {**record["result"], **deepcopy(payload)}
        else:
            record["result"] = deepcopy(payload)
        return deepcopy(record)

    def task_outputs_snapshot(self) -> dict[str, Any]:
        return deepcopy(self.task_outputs)

    def append_task_output_event(self, event: PipelineEvent, *, task_id: str | None = None) -> None:
        scoped_task_id = task_id if task_id is not None else self.task_id
        if not isinstance(scoped_task_id, str) or not scoped_task_id:
            return
        record = self.task_outputs.get(scoped_task_id)
        if not isinstance(record, dict):
            record = {}
            self.task_outputs[scoped_task_id] = record
        events = record.setdefault("events", [])
        if isinstance(events, list):
            events.append(deepcopy(event))

    def record_task_error(self, error: str, *, task_id: str | None = None) -> None:
        scoped_task_id = task_id if task_id is not None else self.task_id
        if not isinstance(scoped_task_id, str) or not scoped_task_id:
            return
        record = self.task_outputs.get(scoped_task_id)
        if not isinstance(record, dict):
            record = {}
            self.task_outputs[scoped_task_id] = record
        record["error"] = error

    def sync_task_output_status(
        self,
        *,
        task_id: str | None = None,
        status: str | None = None,
        terminal_state: str | None = None,
        summary: str | None = None,
    ) -> None:
        scoped_task_id = task_id if task_id is not None else self.task_id
        if not isinstance(scoped_task_id, str) or not scoped_task_id:
            return
        record = self.task_outputs.get(scoped_task_id)
        if not isinstance(record, dict):
            record = {}
            self.task_outputs[scoped_task_id] = record
        if status is not None:
            record["status"] = status
        if terminal_state is not None:
            record["terminal_state"] = terminal_state
        if summary is not None:
            record["summary"] = summary
        if self.session_id is not None:
            record.setdefault("session_id", self.session_id)
        if self.parent_task_id is not None:
            record.setdefault("parent_task_id", self.parent_task_id)
        if self.executor_kind is not None:
            record.setdefault("executor_kind", self.executor_kind)

    def seed_task_output(self, *, task_id: str | None = None, **fields: Any) -> None:
        scoped_task_id = task_id if task_id is not None else self.task_id
        if not isinstance(scoped_task_id, str) or not scoped_task_id:
            return
        record = self.task_outputs.get(scoped_task_id)
        if not isinstance(record, dict):
            record = {}
            self.task_outputs[scoped_task_id] = record
        for key, value in fields.items():
            if value is not None and key not in record:
                record[key] = deepcopy(value)
        record.setdefault("events", [])
        if self.session_id is not None:
            record.setdefault("session_id", self.session_id)
        if self.parent_task_id is not None:
            record.setdefault("parent_task_id", self.parent_task_id)
        if self.executor_kind is not None:
            record.setdefault("executor_kind", self.executor_kind)

    def task_output(self, *, task_id: str | None = None) -> dict[str, Any] | None:
        scoped_task_id = task_id if task_id is not None else self.task_id
        if not isinstance(scoped_task_id, str) or not scoped_task_id:
            return None
        record = self.task_outputs.get(scoped_task_id)
        if not isinstance(record, dict):
            return None
        return deepcopy(record)

    def _sync_task_output_for_event(self, event: PipelineEvent, normalized_data: dict[str, Any]) -> None:
        task_id = normalized_data.get("task_id") if isinstance(normalized_data.get("task_id"), str) else self.task_id
        if not isinstance(task_id, str) or not task_id:
            return
        self.seed_task_output(
            task_id=task_id,
            session_id=normalized_data.get("session_id") if isinstance(normalized_data.get("session_id"), str) else self.session_id,
            parent_task_id=normalized_data.get("parent_task_id") if isinstance(normalized_data.get("parent_task_id"), str) else self.parent_task_id,
            executor_kind=normalized_data.get("executor_kind") if isinstance(normalized_data.get("executor_kind"), str) else self.executor_kind,
            stage_key=event.get("stage"),
        )
        self.append_task_output_event(event, task_id=task_id)
        state = event.get("state")
        summary = event.get("message") if isinstance(event.get("message"), str) else None
        if state == "started":
            self.sync_task_output_status(task_id=task_id, status="processing", summary=summary)
        elif state == "completed":
            self.sync_task_output_status(task_id=task_id, status="completed", terminal_state="success", summary=summary)
        elif state == "failed":
            self.sync_task_output_status(task_id=task_id, status="completed", terminal_state="failed", summary=summary)
            if isinstance(normalized_data.get("error"), str):
                self.record_task_error(normalized_data["error"], task_id=task_id)
        elif state == "skipped":
            self.sync_task_output_status(task_id=task_id, status="completed", terminal_state="skipped", summary=summary)
        elif state == "cancelled":
            self.sync_task_output_status(task_id=task_id, status="completed", terminal_state="cancelled", summary=summary)
        elif state == "queued":
            self.sync_task_output_status(task_id=task_id, status="pending", summary=summary)

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
        normalized_data = {**self._task_scope_data(), **dict(data)}
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
        self._sync_task_output_for_event(event, normalized_data)

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
