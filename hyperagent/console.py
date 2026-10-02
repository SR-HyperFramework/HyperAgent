"""Console rendering helpers for HyperAgent run output."""
from __future__ import annotations

import json
import logging
import re
import shutil
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from .console_log import ConsoleTranscript, console_log_path

logger = logging.getLogger(__name__)

_RESET = "\033[0m"
_STYLES = {
    "stage": "\033[95m",
    "assistant": "\033[32m",
    "thinking": "\033[35m",
    "tool": "\033[36m",
    "ok": "\033[32m",
    "warn": "\033[33m",
    "error": "\033[31m",
    "muted": "\033[2m",
}


class ConsoleLogHandler(logging.Handler):
    """Route logging records through a :class:`RunConsole`."""

    def __init__(self, console: "RunConsole") -> None:
        super().__init__()
        self.console = console

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if getattr(record, "run_console_skip", False):
                return
            message = self.format(record)
            if not message:
                return
            if record.levelno >= logging.ERROR:
                kind = "error"
            elif record.levelno >= logging.WARNING:
                kind = "warn"
            elif record.levelno >= logging.INFO:
                kind = "muted"
            else:
                kind = "muted"
            self.console.write_line(message, kind=kind)
        except Exception:
            self.handleError(record)


@dataclass
class RunConsoleState:
    """Mutable state shown in the minimal-mode footer."""

    stage_index: int = 0
    stage_total: int = 0
    stage_id: str = ""
    stage_name: str = ""
    attempt: int = 0
    turn: int = 0
    max_turns: int = 0
    context_tokens: int = 0
    context_cap: int = 0
    activity: str = "idle"
    started_at: float | None = None
    finished_at: float | None = None

    @property
    def elapsed_seconds(self) -> int:
        if self.started_at is None:
            return 0
        end = self.finished_at if self.finished_at is not None else time.monotonic()
        return max(0, int(end - self.started_at))

    @property
    def context_percent(self) -> float:
        return (self.context_tokens / self.context_cap * 100.0) if self.context_cap else 0.0


@dataclass(frozen=True)
class RunBinding:
    """The sample run a console is attached to, set once the launcher knows it."""

    sample_sha256: str
    report_dir: Path
    stage_ids: tuple[str, ...]
    model: str = ""


@dataclass
class ConsoleEvent:
    """One entry of what the console showed: a line, or a streamed block."""

    seq: int
    kind: str
    text: str
    timestamp: float = field(default_factory=time.time)
    #: Tool name on ``tool`` and result events, so a result can be paired
    #: with its call when the trace collapses tool bursts.
    tool: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "kind": self.kind,
            "text": self.text,
            "clock": datetime.fromtimestamp(self.timestamp).strftime("%H:%M:%S"),
            "tool": self.tool,
        }


class ConsoleEventLog:
    """Bounded, thread-safe record of console output.

    Terminal renderers and the browser dashboard both read from this, so the
    two views show the same run history. Streamed assistant text grows the
    newest event in place until the next line closes it.
    """

    #: A single streamed block is capped so one runaway response cannot pin
    #: megabytes in memory; the head is dropped, the latest text is kept.
    MAX_EVENT_CHARS = 20_000

    def __init__(self, maxlen: int = 2000) -> None:
        self._events: deque[ConsoleEvent] = deque(maxlen=maxlen)
        self._seq = 0
        self._open = False
        self._lock = threading.Lock()

    def _append_locked(self, kind: str, text: str, tool: str = "") -> None:
        self._seq += 1
        self._events.append(ConsoleEvent(seq=self._seq, kind=kind, text=text, tool=tool))

    def add(self, kind: str, text: str, *, tool: str = "") -> None:
        with self._lock:
            self._open = False
            self._append_locked(kind, text, tool)

    def begin(self, kind: str) -> None:
        """Start a streamed block that later :meth:`extend` calls grow."""
        with self._lock:
            self._append_locked(kind, "")
            self._open = True

    def extend(self, text: str, *, kind: str = "assistant") -> None:
        with self._lock:
            if not self._open or not self._events or self._events[-1].kind != kind:
                self._append_locked(kind, "")
                self._open = True
            event = self._events[-1]
            event.text += text
            if len(event.text) > self.MAX_EVENT_CHARS:
                event.text = "…" + event.text[-self.MAX_EVENT_CHARS:]

    def closed_since(self, seq: int, *, include_open: bool = False) -> list[ConsoleEvent]:
        """Copies of events newer than *seq* that will not change any more.

        The streamed block still being extended is left out unless
        *include_open* (the run is over and nothing will extend it).
        """
        with self._lock:
            newer: list[ConsoleEvent] = []
            for event in reversed(self._events):
                if event.seq <= seq:
                    break
                newer.append(event)
            newer.reverse()
            if newer and self._open and not include_open and newer[-1] is self._events[-1]:
                newer.pop()
            return [replace(event) for event in newer]

    def tail(self, limit: int | None = None) -> list[ConsoleEvent]:
        """Copies of the newest events, oldest first."""
        with self._lock:
            events = list(self._events)
        if limit is not None:
            events = events[-limit:] if limit > 0 else []
        return [replace(event) for event in events]


# C0/C1 controls (minus tab and newline) and the bidi overrides. Report text is
# derived from the analyzed sample, so an embedded ESC sequence must not reach
# the terminal as a live command or a spoofed line.
_UNSAFE_TERMINAL_CHARS = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")


def sanitize_terminal_text(text: Any) -> str:
    """Render control characters visibly (``\\x1b``) instead of executing them."""

    def visible(match: re.Match[str]) -> str:
        code = ord(match.group())
        return f"\\x{code:02x}" if code <= 0xFF else f"\\u{code:04x}"

    value = str(text).replace("\r\n", "\n").replace("\r", "\n")
    return _UNSAFE_TERMINAL_CHARS.sub(visible, value)


def supports_ansi(stream: TextIO | None = None) -> bool:
    """Return whether *stream* appears to support ANSI cursor/color output."""

    stream = stream or sys.stderr
    is_tty = getattr(stream, "isatty", lambda: False)
    try:
        return bool(is_tty())
    except Exception:
        return False


def style(text: str, kind: str, *, enabled: bool = True) -> str:
    """Apply a small ANSI style when enabled."""

    if not enabled:
        return text
    color = _STYLES.get(kind)
    return f"{color}{text}{_RESET}" if color else text


def collapse_whitespace(text: Any) -> str:
    """Collapse runs of whitespace into one space for compact console previews."""

    return " ".join(str(text).strip().split())


def truncate_preview(text: Any, max_chars: int = 200) -> str:
    """Return a compact preview with an explicit collapsed suffix when truncated."""

    preview = collapse_whitespace(text)
    if max_chars <= 0 or len(preview) <= max_chars:
        return preview

    suffix = f" ... (collapsed, {len(preview):,} chars)"
    if len(suffix) >= max_chars:
        return preview[:max_chars].rstrip()
    return f"{preview[: max_chars - len(suffix)].rstrip()}{suffix}"


def preview_json_or_text(value: Any, max_chars: int = 200) -> str:
    """Serialize JSON-like values compactly, falling back to ``str(value)``."""

    if isinstance(value, str):
        raw = value
    else:
        try:
            raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
        except TypeError:
            raw = str(value)
    return truncate_preview(raw, max_chars=max_chars)


def format_elapsed(seconds: int) -> str:
    """Return a compact HH:MM:SS or MM:SS elapsed-time string."""
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


class RunConsole:
    """Minimal run renderer with an optional bottom status footer."""

    def __init__(
        self,
        *,
        stream: TextIO | None = None,
        enabled: bool = True,
        force_tty: bool = False,
        preview_chars: int = 200,
    ) -> None:
        self.stream = stream or sys.stderr
        self.enabled = enabled
        self.preview_chars = preview_chars
        self.state = RunConsoleState()
        self.events = ConsoleEventLog()
        self.run: RunBinding | None = None
        #: Browser dashboard state: "off", "running", or "failed".
        self.viewer_status = "off"
        self.viewer_url: str | None = None
        self.viewer_detail = ""
        self.finished = False
        self._transcript: ConsoleTranscript | None = None
        self._persisted_seq = 0
        self._lock = threading.RLock()
        self._ansi_enabled = enabled and (force_tty or supports_ansi(self.stream))
        self._footer_active = False

    @property
    def ansi_enabled(self) -> bool:
        return self._ansi_enabled

    @property
    def footer_active(self) -> bool:
        return self._footer_active

    def start(self) -> None:
        with self._lock:
            if self.state.started_at is None:
                self.state.started_at = time.monotonic()
        if not self.enabled or not self._ansi_enabled:
            return
        with self._lock:
            self._footer_active = True
            self._render_footer_locked()

    def finish(self) -> None:
        with self._lock:
            if not self.finished:
                self.finished = True
                self.state.finished_at = time.monotonic()
        self._close_transcript()
        if not self.enabled:
            return
        with self._lock:
            if self._ansi_enabled and self._footer_active:
                self.stream.write("\0337\033[999;1H\033[2K\0338")
                self.stream.flush()
            self._footer_active = False

    # --- run binding and the browser dashboard ---------------------------------

    def bind_run(
        self,
        *,
        sample_sha256: str,
        report_dir: Path,
        stage_ids: tuple[str, ...] | list[str],
        model: str = "",
    ) -> None:
        """Attach the console to the run the launcher is about to execute.

        From here on the console also appends what it shows to the run's
        ``console.jsonl`` (see :mod:`hyperagent.console_log`), starting with
        anything already said before the run was bound.
        """
        with self._lock:
            self.run = RunBinding(
                sample_sha256=sample_sha256.lower(),
                report_dir=Path(report_dir),
                stage_ids=tuple(stage_ids),
                model=model,
            )
            if self.enabled:
                if self._transcript is not None:
                    self._transcript.close()
                self._transcript = ConsoleTranscript(console_log_path(report_dir))
                header = f"Console session · {len(self.run.stage_ids)} stages"
                if model:
                    header += f" · {model}"
                self._transcript.open(sanitize_terminal_text(header), timestamp=time.time())
                self._persist_locked()
        if self.viewer_status == "running":
            self.write_line(
                f"▶ Watch live in browser: {self.viewer_run_url}", kind="ok", collapse=False
            )

    def set_viewer(self, status: str, *, url: str | None = None, detail: str = "") -> None:
        with self._lock:
            self.viewer_status = status
            self.viewer_url = url.rstrip("/") if url else None
            self.viewer_detail = detail
        if status == "failed":
            self.write_line(
                f"Live dashboard unavailable: {detail or 'failed to start'}", kind="warn"
            )

    @property
    def viewer_run_url(self) -> str | None:
        """Deep link to this run's live page, or the dashboard root before binding."""
        with self._lock:
            if not self.viewer_url:
                return None
            if self.run is None:
                return self.viewer_url
            return f"{self.viewer_url}/live/{self.run.sample_sha256}"

    def report_dir_for(self, sha256: str) -> Path | None:
        """Live-feed hook: where the attached run writes its artifacts."""
        with self._lock:
            if self.run is not None and self.run.sample_sha256 == sha256.lower():
                return self.run.report_dir
        return None

    def active_runs(self) -> list[dict[str, Any]]:
        """Live-feed hook: the run this console is attached to, if any."""
        with self._lock:
            if self.run is None:
                return []
            return [
                {
                    "sha256": self.run.sample_sha256,
                    "stage_id": self.state.stage_id or None,
                    "activity": self.state.activity,
                    "finished": self.finished,
                }
            ]

    def live_status(self, sha256: str, *, event_limit: int = 200) -> dict[str, Any] | None:
        """Live-feed hook: runtime state plus recent console events for one run."""
        with self._lock:
            if self.run is None or self.run.sample_sha256 != sha256.lower():
                return None
            state = self.state
            return {
                "attached": True,
                "finished": self.finished,
                "activity": state.activity,
                # "" = the run is over, so no stage is live (see load_snapshot).
                "active_stage_id": "" if self.finished else (state.stage_id or None),
                "stage_id": state.stage_id or None,
                "stage_index": state.stage_index,
                "stage_total": state.stage_total,
                "attempt": state.attempt,
                "elapsed_seconds": state.elapsed_seconds,
                "elapsed": format_elapsed(state.elapsed_seconds),
                "turn": state.turn,
                "max_turns": state.max_turns,
                "context_tokens": state.context_tokens,
                "context_cap": state.context_cap,
                "context_percent": round(state.context_percent, 1),
                "model": self.run.model,
                "stage_ids": list(self.run.stage_ids),
                "events": [event.to_dict() for event in self.events.tail(event_limit)],
            }

    def set_stage(
        self,
        *,
        index: int,
        total: int,
        stage_id: str,
        stage_name: str = "",
        attempt: int = 0,
    ) -> None:
        with self._lock:
            self.state.stage_index = index
            self.state.stage_total = total
            self.state.stage_id = stage_id
            self.state.stage_name = stage_name or stage_id
            self.state.attempt = attempt
            self._render_footer_locked()

    def set_context(self, *, turn: int, max_turns: int, tokens: int, cap: int) -> None:
        with self._lock:
            self.state.turn = turn
            self.state.max_turns = max_turns
            self.state.context_tokens = tokens
            self.state.context_cap = cap
            self._render_footer_locked()

    def set_activity(self, activity: str) -> None:
        with self._lock:
            self.state.activity = activity
            self._render_footer_locked()

    def stage_transition(
        self,
        *,
        index: int,
        total: int,
        stage_id: str,
        stage_name: str = "",
        attempt: int = 0,
        guarded: bool | None = None,
    ) -> None:
        self.set_stage(index=index, total=total, stage_id=stage_id, stage_name=stage_name, attempt=attempt)
        detail = f"Stage {index}/{total} → {stage_id}"
        if stage_name and stage_name != stage_id:
            detail += f" ({stage_name})"
        if attempt:
            detail += f" attempt {attempt}"
        if guarded is not None:
            detail += f" guarded={guarded}"
        self.write_line(detail, kind="stage")

    # --- output -----------------------------------------------------------------
    # Every public writer records a semantic event (what happened) and then
    # emits a display line (how this renderer shows it). Subclasses that draw
    # their own screen override the ``_emit_*`` hooks and read ``self.events``.

    def write_line(self, text: Any, *, kind: str = "info", collapse: bool = True) -> None:
        if not self.enabled:
            return
        line = truncate_preview(text, self.preview_chars) if collapse else str(text)
        self._record_and_emit(kind, sanitize_terminal_text(line))

    def write_inline(self, text: Any, *, kind: str = "assistant") -> None:
        if not self.enabled:
            return
        chunk = sanitize_terminal_text(text)
        with self._lock:
            self.events.extend(chunk, kind=kind)
            self._persist_locked()
            self._emit_inline_locked(chunk, kind)

    def assistant_label(self) -> None:
        self.set_activity("assistant")
        if not self.enabled:
            return
        with self._lock:
            self.events.begin("assistant")
            self._persist_locked()
            self._emit_inline_locked("💬 assistant ", "assistant")

    def thinking(self, text: Any = "") -> None:
        self.set_activity("thinking")
        if not self.enabled:
            return
        raw = truncate_preview(text, self.preview_chars) if str(text).strip() else "thinking"
        preview = sanitize_terminal_text(raw)
        self._record_and_emit("thinking", preview, display=f"🧠 {preview}")

    def tool_call(self, name: str, args: Any = "") -> None:
        self.set_activity("tool")
        if not self.enabled:
            return
        args_preview = preview_json_or_text(args, max_chars=self.preview_chars)
        call = sanitize_terminal_text(f"{name}({args_preview})")
        self._record_and_emit(
            "tool", call, display=f"🛠 tool {call}", tool=sanitize_terminal_text(name)
        )

    def tool_result(self, content: Any, *, is_error: bool = False, name: str = "") -> None:
        self.set_activity("tool error" if is_error else "tool result")
        if not self.enabled:
            return
        preview = sanitize_terminal_text(truncate_preview(content, self.preview_chars))
        marker = "x" if is_error else "="
        self._record_and_emit(
            "result_error" if is_error else "result",
            preview,
            display=f"  {marker} {preview}",
            style_kind="error" if is_error else "ok",
            tool=sanitize_terminal_text(name),
        )

    def _record_and_emit(
        self,
        kind: str,
        text: str,
        *,
        display: str | None = None,
        style_kind: str | None = None,
        tool: str = "",
    ) -> None:
        with self._lock:
            self.events.add(kind, text, tool=tool)
            self._persist_locked()
            self._emit_line_locked(text if display is None else display, style_kind or kind)

    # --- transcript ----------------------------------------------------------------

    def _persist_locked(self, *, include_open: bool = False) -> None:
        """Append events that are final to the run's transcript, once each."""
        transcript = self._transcript
        if transcript is None:
            return
        for event in self.events.closed_since(self._persisted_seq, include_open=include_open):
            transcript.write(
                seq=event.seq,
                kind=event.kind,
                text=event.text,
                timestamp=event.timestamp,
                tool=event.tool,
            )
            self._persisted_seq = event.seq

    def _close_transcript(self) -> None:
        with self._lock:
            if self._transcript is None:
                return
            self._persist_locked(include_open=True)
            self._transcript.close()
            self._transcript = None

    def _emit_line_locked(self, line: str, kind: str) -> None:
        self._clear_footer_locked()
        self.stream.write(f"{style(line, kind, enabled=self._ansi_enabled)}\n")
        self._render_footer_locked()
        self.stream.flush()

    def _emit_inline_locked(self, text: str, kind: str) -> None:
        self._clear_footer_locked()
        self.stream.write(style(text, kind, enabled=self._ansi_enabled))
        self.stream.flush()
        self._render_footer_locked()

    def _footer_text(self) -> str:
        stage = "Stage --/--"
        if self.state.stage_index and self.state.stage_total:
            stage = f"Stage {self.state.stage_index:02d}/{self.state.stage_total:02d} {self.state.stage_id}"
            if self.state.attempt:
                stage += f" attempt {self.state.attempt}"

        context = "Context --/--"
        if self.state.context_cap:
            context = (
                f"Context {self.state.context_tokens:,}/{self.state.context_cap:,} "
                f"{self.state.context_percent:.1f}%"
            )
            if self.state.turn and self.state.max_turns:
                context += f" turn {self.state.turn}/{self.state.max_turns}"
        return f" {stage} | Time {format_elapsed(self.state.elapsed_seconds)} | {context} | {self.state.activity} "

    def _terminal_width(self) -> int:
        try:
            return shutil.get_terminal_size((100, 24)).columns
        except Exception:
            return 100

    def _clear_footer_locked(self) -> None:
        if self._ansi_enabled and self._footer_active:
            self.stream.write("\0337\033[999;1H\033[2K\0338")

    def _render_footer_locked(self) -> None:
        if not self.enabled or not self._ansi_enabled:
            return
        try:
            self._footer_active = True
            footer = truncate_preview(self._footer_text(), self._terminal_width() - 1)
            self.stream.write(f"\0337\033[999;1H\033[2K{style(footer, 'muted', enabled=True)}\0338")
            self.stream.flush()
        except Exception:  # pragma: no cover - best-effort fallback
            self._ansi_enabled = False
            self._footer_active = False
            return


def create_run_console(*, stream: TextIO | None = None, prefer_tui: bool = True) -> RunConsole:
    """The richest console *stream* supports.

    A capable terminal gets the full-screen sidebar console; anything else
    (piped output, a legacy Windows console, ``rich`` not installed, or
    ``prefer_tui=False``) gets the line console with its one-line footer.
    """
    stream = stream or sys.stderr
    if prefer_tui and supports_ansi(stream):
        try:
            from .tui import SidebarConsole, tui_supported
        except ImportError:
            logger.debug("rich is unavailable; using the line console", exc_info=True)
        else:
            if tui_supported(stream):
                return SidebarConsole(stream=stream, read_input=True)
    return RunConsole(stream=stream)
