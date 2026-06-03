from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List


@dataclass
class PipelineLogger:
    run_id: str
    events: List[Dict[str, Any]] = field(default_factory=list)

    def log(self, stage: str, state: str, message: str, **data: Any) -> Dict[str, Any]:
        event: Dict[str, Any] = {
            "run_id": self.run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "state": state,
            "message": message,
        }
        if data:
            event["data"] = data
        self.events.append(event)

        line = f"[PIPELINE][{self.run_id}][{stage}][{state}] {message}"
        if data:
            rendered = ", ".join(f"{key}={value}" for key, value in data.items())
            line = f"{line} | {rendered}"
        print(line)
        return event

    def snapshot(self) -> List[Dict[str, Any]]:
        return list(self.events)
