"""The run console's transcript on disk: ``<report_dir>/console.jsonl``.

The console keeps only a bounded in-memory log, and the full-screen view
disappears with the process, so every finished console event is also
appended here. The dashboard reads it back to show a run's output after the
CLI has exited, or from a separately started ``webui/app.py``.

Each line is one JSON object::

    {"session": "<id>", "seq": 12, "kind": "tool", "text": "...",
     "ts": "2026-10-02T01:24:32Z", "clock": "08:24:32"}

A ``kind: "session"`` record opens every console attach, so a resumed run
appends a new session to the same file rather than overwriting the old one.
Text is stored as the console showed it: previews already truncated and
terminal control characters already neutralized.

Stdlib only: ``webui`` imports the reader without the rest of HyperAgent.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

logger = logging.getLogger(__name__)

CONSOLE_LOG_NAME = "console.jsonl"
SESSION_KIND = "session"
#: The dashboard reads at most this much from the end of a transcript.
READ_TAIL_BYTES = 4 * 1024 * 1024


def console_log_path(report_dir: Path | str) -> Path:
    return Path(report_dir) / CONSOLE_LOG_NAME


def event_record(
    *, session: str, seq: int, kind: str, text: str, timestamp: float, tool: str = ""
) -> dict[str, Any]:
    moment = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    record = {
        "session": session,
        "seq": seq,
        "kind": kind,
        "text": text,
        "ts": moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "clock": moment.astimezone().strftime("%H:%M:%S"),
    }
    if tool:
        record["tool"] = tool
    return record


class ConsoleTranscript:
    """Append-only writer for one console session.

    Write failures are logged once and then ignored: a full disk or a locked
    file must never take the analysis run down with it.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.session = uuid.uuid4().hex[:12]
        self._handle: TextIO | None = None
        self._failed = False

    def open(self, header: str, *, timestamp: float) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self.path.open("a", encoding="utf-8", newline="\n")
        except OSError as exc:
            self._fail(exc)
            return
        self.write(seq=0, kind=SESSION_KIND, text=header, timestamp=timestamp)

    def write(self, *, seq: int, kind: str, text: str, timestamp: float, tool: str = "") -> None:
        if self._handle is None:
            return
        record = event_record(
            session=self.session, seq=seq, kind=kind, text=text, timestamp=timestamp, tool=tool
        )
        try:
            self._handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._handle.flush()
        except (OSError, ValueError) as exc:
            self._fail(exc)

    def close(self) -> None:
        handle, self._handle = self._handle, None
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass

    def _fail(self, exc: Exception) -> None:
        if not self._failed:
            logger.warning("Console transcript disabled (%s): %s", self.path, exc)
        self._failed = True
        self.close()


@dataclass(frozen=True)
class SavedConsole:
    """A transcript read back for display."""

    events: list[dict[str, Any]] = field(default_factory=list)
    #: Records in the part of the file that was read; when ``truncated`` the
    #: file holds more than this.
    total: int = 0
    truncated: bool = False
    sessions: int = 0

    @property
    def exists(self) -> bool:
        return self.total > 0


def read_console_log(
    report_dir: Path | str,
    *,
    limit: int | None = 500,
    tail_bytes: int = READ_TAIL_BYTES,
) -> SavedConsole:
    """The newest *limit* records of a run's transcript (all when None).

    Only the last *tail_bytes* of a large file are read, and malformed lines
    -- a write cut off by a crash -- are skipped.
    """
    path = console_log_path(report_dir)
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            truncated = size > tail_bytes
            if truncated:
                handle.seek(size - tail_bytes)
                handle.readline()  # drop the partial first line
            raw = handle.read()
    except OSError:
        return SavedConsole()

    records: list[dict[str, Any]] = []
    for line in raw.decode("utf-8", "replace").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict) or not isinstance(record.get("text"), str):
            continue
        kind = record.get("kind")
        records.append(
            {
                "session": str(record.get("session") or ""),
                "seq": record.get("seq") if isinstance(record.get("seq"), int) else 0,
                "kind": kind if isinstance(kind, str) and kind else "info",
                "text": record["text"],
                "ts": str(record.get("ts") or ""),
                "clock": str(record.get("clock") or ""),
                "tool": str(record.get("tool") or ""),
            }
        )
    sessions = sum(1 for record in records if record["kind"] == SESSION_KIND)
    shown = records if limit is None else records[-limit:] if limit > 0 else []
    return SavedConsole(
        events=shown,
        total=len(records),
        truncated=truncated or len(shown) < len(records),
        sessions=sessions,
    )


def has_console_log(report_dir: Path | str) -> bool:
    try:
        return os.path.getsize(console_log_path(report_dir)) > 0
    except OSError:
        return False
