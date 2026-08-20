"""Console rendering helpers for HyperAgent run output."""
from __future__ import annotations

import json
import logging
import shutil
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, TextIO

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

    @property
    def elapsed_seconds(self) -> int:
        if self.started_at is None:
            return 0
        return max(0, int(time.monotonic() - self.started_at))

    @property
    def context_percent(self) -> float:
        return (self.context_tokens / self.context_cap * 100.0) if self.context_cap else 0.0


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
        if not self.enabled or not self._ansi_enabled:
            return
        with self._lock:
            self.state.started_at = time.monotonic()
            self._footer_active = True
            self._render_footer_locked()

    def finish(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            if self._ansi_enabled and self._footer_active:
                self.stream.write("\0337\033[999;1H\033[2K\0338")
                self.stream.flush()
            self._footer_active = False

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

    def write_line(self, text: Any, *, kind: str = "info", collapse: bool = True) -> None:
        if not self.enabled:
            return
        line = truncate_preview(text, self.preview_chars) if collapse else str(text)
        with self._lock:
            self._clear_footer_locked()
            self.stream.write(f"{style(line, kind, enabled=self._ansi_enabled)}\n")
            self._render_footer_locked()
            self.stream.flush()

    def write_inline(self, text: Any, *, kind: str = "assistant") -> None:
        if not self.enabled:
            return
        with self._lock:
            self._clear_footer_locked()
            self.stream.write(style(str(text), kind, enabled=self._ansi_enabled))
            self.stream.flush()
            self._render_footer_locked()

    def assistant_label(self) -> None:
        self.set_activity("assistant")
        self.write_inline("💬 assistant ", kind="assistant")

    def thinking(self, text: Any = "") -> None:
        self.set_activity("thinking")
        preview = truncate_preview(text, self.preview_chars) if str(text).strip() else "thinking"
        self.write_line(f"🧠 {preview}", kind="thinking")

    def tool_call(self, name: str, args: Any = "") -> None:
        self.set_activity("tool")
        args_preview = preview_json_or_text(args, max_chars=self.preview_chars)
        self.write_line(f"🛠 tool {name}({args_preview})", kind="tool")

    def tool_result(self, content: Any, *, is_error: bool = False) -> None:
        self.set_activity("tool error" if is_error else "tool result")
        marker = "x" if is_error else "="
        kind = "error" if is_error else "ok"
        self.write_line(f"  {marker} {truncate_preview(content, self.preview_chars)}", kind=kind, collapse=False)

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
