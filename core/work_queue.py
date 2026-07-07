from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass
class WorkItem:
    path: str
    depth: int = 0
    parent_path: str | None = None
    parent_artifact_id: str | None = None
    priority: int = 0


class WorkQueue:
    def __init__(self):
        self._items: deque[WorkItem] = deque()

    def enqueue(self, item: WorkItem) -> None:
        insert_at = len(self._items)
        for index, existing in enumerate(self._items):
            if item.priority > existing.priority:
                insert_at = index
                break
        self._items.insert(insert_at, item)

    def dequeue(self) -> WorkItem:
        return self._items.popleft()

    def __bool__(self) -> bool:
        return bool(self._items)
