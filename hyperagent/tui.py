"""Full-screen run console: live trace on the left, run sidebar on the right.

Modelled on Strix's terminal UI. The trace fills a bordered pane with a
one-line status row under it; the sidebar stacks the browser-dashboard link
("Watch live in browser"), stage progress, indicators, evidence and run stats.

Everything is drawn by ``rich.live`` from two sources -- the console's event
log and a throttled :mod:`hyperagent.run_snapshot` read of the report
directory -- so pipeline code keeps calling the ordinary :class:`RunConsole`
methods and never needs to know which renderer is attached.
"""

from __future__ import annotations

import io
import logging
import sys
import threading
import time
from bisect import bisect_left
from dataclasses import dataclass, replace
from typing import Any, TextIO

from rich.console import Console, Group, RenderableType
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.style import Style
from rich.table import Table
from rich.text import Text

from . import __version__
from .console import (
    ConsoleEvent,
    RunBinding,
    RunConsole,
    RunConsoleState,
    format_elapsed,
    sanitize_terminal_text,
    style,
    supports_ansi,
)
from .console_actions import STATUS_ERROR, ActionGroup, group_events
from .run_snapshot import (
    STATUS_CHECKPOINTED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_RUNNING,
    FindingBrief,
    JsonFileCache,
    RunSnapshot,
    StageProgress,
    load_snapshot,
)
from .tui_input import (
    DOWN,
    END,
    EXPAND,
    HOME,
    PAGE_DOWN,
    PAGE_UP,
    UP,
    WHEEL_DOWN,
    WHEEL_UP,
    InputReader,
)

logger = logging.getLogger(__name__)

# Strix's palette (strix/interface/tui/internal/app/model.go), plus cyan and
# violet for the tool and stage accents HyperAgent's trace needs.
GREEN = "#22c55e"
RED = "#ef4444"
AMBER = "#d97706"
WHITE = "#fafaf9"
TEXT = "#d4d4d4"
DIM = "#737373"
DARK = "#333333"
CYAN = "#22d3ee"
VIOLET = "#a78bfa"
DARK_HINT = "#525252"

SPINNER_FRAMES = "◐◓◑◒"
#: Below this many columns the sidebar is dropped, as Strix does, so the trace
#: keeps a readable width.
SIDEBAR_MIN_TERMINAL_WIDTH = 100
#: How often the sidebar re-reads the report directory.
SNAPSHOT_INTERVAL_SECONDS = 1.0
#: Trace lines one mouse-wheel notch scrolls.
WHEEL_LINES = 3

_FINDING_GLYPHS = {
    "confirmed": ("●", GREEN),
    "observed": ("●", GREEN),
    "partial": ("◐", AMBER),
    "inferred": ("◐", AMBER),
    "hypothesized": ("◌", CYAN),
    "contradicted": ("✗", RED),
    "rejected": ("✗", RED),
}
_IOC_LABELS = {"network": ("NET ", CYAN), "host": ("HOST", AMBER), "persistence": ("PERS", VIOLET)}
_VERDICT_COLORS = {"malicious": RED, "suspicious": AMBER, "benign": GREEN}


def tui_supported(stream: TextIO) -> bool:
    """Whether *stream* is a terminal the full-screen console can drive."""
    if not supports_ansi(stream):
        return False
    probe = Console(file=stream)
    # A non-UTF-8 stream cannot encode the box and status glyphs; the failure
    # would surface inside Live's refresh thread and silently freeze the view.
    utf8 = probe.encoding.lower().replace("-", "").startswith("utf")
    return probe.is_terminal and utf8 and not probe.legacy_windows and not probe.is_dumb_terminal


def sidebar_width(total_width: int) -> int:
    """Sidebar columns for a terminal *total_width* wide; 0 hides it."""
    if total_width < SIDEBAR_MIN_TERMINAL_WIDTH:
        return 0
    return max(34, min(48, total_width // 4))


def _safe(value: Any) -> str:
    """Artifact text is sample-derived; never let it drive the terminal."""
    return " ".join(sanitize_terminal_text(value).split())


def _spread(left: Text, right: Text, width: int) -> Text:
    """One row with *left* flush left and *right* flush right, truncating left."""
    right_width = right.cell_len
    room = max(1, width - right_width - (1 if right_width else 0))
    if left.cell_len > room:
        left.truncate(room, overflow="ellipsis")
    gap = max(1 if right_width else 0, width - left.cell_len - right_width)
    return Text.assemble(left, " " * gap, right)


def _clip(text: Text, width: int) -> Text:
    text.truncate(max(1, width), overflow="ellipsis")
    return text


def format_event(event: ConsoleEvent) -> Text | None:
    """How one console event reads in the trace pane."""
    text = event.text.rstrip()
    if not text:
        return None
    kind = event.kind
    if kind == "stage":
        return Text.assemble("\n", ("▌ ", VIOLET), (text, f"bold {VIOLET}"))
    if kind == "assistant":
        return Text.assemble("\n", ("● ", GREEN), (text.strip(), WHITE))
    if kind == "thinking":
        return Text.assemble(("∴ ", VIOLET), (text, f"italic {DIM}"))
    if kind == "tool":
        name, paren, rest = text.partition("(")
        return Text.assemble(("→ ", CYAN), (name, f"bold {CYAN}"), (paren + rest, DIM))
    if kind == "result":
        return Text.assemble(("  ✓ ", GREEN), (text.strip(), DIM))
    if kind == "result_error":
        return Text.assemble(("  ✗ ", RED), (text.strip(), RED))
    if kind == "error":
        return Text.assemble(("✗ ", RED), (text, RED))
    if kind == "warn":
        return Text.assemble(("! ", AMBER), (text, AMBER))
    if kind == "ok":
        return Text(text, style=GREEN)
    if kind == "muted":
        return Text(text, style=DIM)
    return Text(text, style=TEXT)


def format_action_group(
    group: ActionGroup, *, expanded: bool, active: bool, hint: bool = False
) -> list[Text]:
    """A tool burst: one summary line, or every call and result when expanded."""
    if expanded:
        texts = [format_event(event) for event in group.events]
        return [text for text in texts if text is not None]
    line = Text.assemble(("◆ ", CYAN), (_safe(group.summary), TEXT))
    if group.failed:
        line.append(f" · {group.failed} failed", style=RED)
    if hint:
        line.append("  (ctrl+o to expand)", style=DARK_HINT)
    texts = [line]
    failures = [action for action in group.actions if action.status == STATUS_ERROR]
    for action in failures[-2:]:
        texts.append(
            Text.assemble(
                ("  ⎿ ✗ ", RED), (_safe(action.label), TEXT), (f"  {_safe(action.result)}", DIM)
            )
        )
    pending = group.pending
    if active and pending is not None:
        texts.append(Text.assemble(("  ⎿ ", DIM), (f"{_safe(pending.label)} …", DIM)))
    for text in texts[1:]:
        text.truncate(400, overflow="ellipsis")
    return texts


class TraceScroll:
    """Scroll position of the trace pane.

    Following (the default) pins the view to the newest line. Scrolling up
    anchors the top visible row to a specific event line instead of a
    distance from the bottom, so the view holds still while new output
    arrives and old events age out. Reaching the bottom again resumes
    following.

    Input handlers only queue a request; :meth:`window` applies it during the
    next redraw, when the wrapped rows and pane height are known.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._anchor: tuple[int, int] | None = None
        self._lines = 0
        self._pages = 0
        self._jump: str | None = None

    @property
    def following(self) -> bool:
        with self._lock:
            return self._anchor is None and not (self._lines or self._pages or self._jump)

    def scroll(self, lines: int) -> None:
        """Move by *lines* rows; negative scrolls back in time."""
        with self._lock:
            self._lines += lines

    def page(self, pages: int) -> None:
        with self._lock:
            self._pages += pages

    def home(self) -> None:
        with self._lock:
            self._jump, self._lines, self._pages = HOME, 0, 0

    def end(self) -> None:
        with self._lock:
            self._jump, self._lines, self._pages = END, 0, 0

    def window(self, keys: list[tuple[int, int]], height: int) -> tuple[int, int]:
        """``(top, below)``: first visible row index and rows hidden under the view."""
        total = len(keys)
        bottom = max(0, total - height)
        with self._lock:
            jump, lines, pages = self._jump, self._lines, self._pages
            self._jump, self._lines, self._pages = None, 0, 0
            if jump == END:
                top = bottom
            elif jump == HOME:
                top = 0
            elif self._anchor is None:
                top = bottom
            else:
                # Rows are ordered by (seq, line). If the anchored row is gone --
                # aged out of the log, or folded away by collapsing a tool burst --
                # the nearest row after it takes its place.
                top = bisect_left(keys, self._anchor)
            top += lines + pages * max(1, height - 1)
            top = min(max(top, 0), bottom)
            self._anchor = keys[top] if top < bottom else None
        return top, total - min(total, top + height)


@dataclass(frozen=True)
class _Frame:
    """Everything one redraw needs, copied out of the console under its lock."""

    state: RunConsoleState
    run: RunBinding | None
    events: list[ConsoleEvent]
    viewer_status: str
    viewer_url: str | None
    viewer_detail: str
    finished: bool


class _LineProxy(io.TextIOBase):
    """Stand-in for sys.stdout/sys.stderr while the full-screen view is up.

    A stray ``print`` would otherwise scribble over the drawn frame; instead
    each completed line becomes a trace event.
    """

    def __init__(self, console: RunConsole, original: TextIO, kind: str) -> None:
        super().__init__()
        self._console = console
        self._original = original
        self._kind = kind
        self._buffer = ""
        self._lock = threading.Lock()

    def writable(self) -> bool:
        return True

    def isatty(self) -> bool:
        return False

    def fileno(self) -> int:
        return self._original.fileno()

    @property
    def encoding(self) -> str:  # type: ignore[override]
        return getattr(self._original, "encoding", None) or "utf-8"

    def write(self, text: str) -> int:
        with self._lock:
            self._buffer += text
            lines = self._buffer.split("\n")
            self._buffer = lines.pop()
        for line in lines:
            if line.strip():
                self._console.write_line(line, kind=self._kind)
        return len(text)

    def flush(self) -> None:
        with self._lock:
            pending, self._buffer = self._buffer, ""
        if pending.strip():
            self._console.write_line(pending, kind=self._kind)


class SidebarConsole(RunConsole):
    """Strix-style full-screen console with a live run sidebar."""

    def __init__(
        self,
        *,
        stream: TextIO | None = None,
        preview_chars: int = 200,
        rich_console: Console | None = None,
        refresh_per_second: float = 4.0,
        read_input: bool = False,
    ) -> None:
        super().__init__(stream=stream, enabled=True, force_tty=True, preview_chars=preview_chars)
        self._rich = rich_console or Console(
            file=self.stream, force_terminal=True, highlight=False, emoji=False
        )
        self._refresh_per_second = refresh_per_second
        self._live: Live | None = None
        self._started_live = False
        self._saved_streams: tuple[TextIO, TextIO] | None = None
        self._snapshot_cache = JsonFileCache()
        self._snapshot_lock = threading.Lock()
        self._snapshot_value: RunSnapshot | None = None
        self._snapshot_key: tuple[Any, ...] | None = None
        self._snapshot_at = 0.0
        self.scroll = TraceScroll()
        #: Tool bursts show as one summary line unless expanded (Ctrl+O).
        self.actions_expanded = False
        #: Off unless asked for: the reader takes over the process's console
        #: input, which tests and embedded uses must not have happen.
        self._read_input = read_input
        self._input = InputReader(self._on_input, output=self.stream)
        self._input_active = False
        self._wrap_lock = threading.Lock()
        self._wrap_cache: dict[int, tuple[tuple[Any, ...], list[Text]]] = {}

    # --- lifecycle --------------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self.state.started_at is None:
                self.state.started_at = time.monotonic()
            if self._live is not None or self.finished:
                return
            live = Live(
                get_renderable=self._render,
                console=self._rich,
                screen=True,
                auto_refresh=True,
                refresh_per_second=self._refresh_per_second,
                redirect_stdout=False,
                redirect_stderr=False,
            )
            self._live = live
        # Never hold the console lock across Live.start/stop: the refresh
        # thread takes Live's lock and then ours, so the reverse order here
        # would deadlock.
        self._install_stream_proxies()
        try:
            live.start()
        except Exception:
            logger.warning(
                "Full-screen console failed to start; falling back to plain lines", exc_info=True
            )
            self._restore_streams()
            with self._lock:
                self._live = None
            return
        self._started_live = True
        if self._read_input:
            self._input_active = self._input.start()

    def finish(self) -> None:
        with self._lock:
            live, self._live = self._live, None
            if not self.finished:
                self.finished = True
                self.state.finished_at = time.monotonic()
        self._close_transcript()
        if live is None:
            return
        self._input.stop()
        self._input_active = False
        try:
            live.stop()
        finally:
            self._restore_streams()
        try:
            self._print_final_summary()
        except Exception:  # pragma: no cover - the run result matters more than the recap
            logger.debug("Could not print the final run summary", exc_info=True)

    def _install_stream_proxies(self) -> None:
        self._saved_streams = (sys.stdout, sys.stderr)
        sys.stdout = _LineProxy(self, sys.stdout, "muted")  # type: ignore[assignment]
        sys.stderr = _LineProxy(self, sys.stderr, "warn")  # type: ignore[assignment]

    def _restore_streams(self) -> None:
        if self._saved_streams is None:
            return
        for proxy in (sys.stdout, sys.stderr):
            if isinstance(proxy, _LineProxy):
                proxy.flush()
        sys.stdout, sys.stderr = self._saved_streams
        self._saved_streams = None

    def _on_input(self, action: str) -> None:
        if action == UP:
            self.scroll.scroll(-1)
        elif action == DOWN:
            self.scroll.scroll(1)
        elif action == WHEEL_UP:
            self.scroll.scroll(-WHEEL_LINES)
        elif action == WHEEL_DOWN:
            self.scroll.scroll(WHEEL_LINES)
        elif action == PAGE_UP:
            self.scroll.page(-1)
        elif action == PAGE_DOWN:
            self.scroll.page(1)
        elif action == HOME:
            self.scroll.home()
        elif action == END:
            self.scroll.end()
        elif action == EXPAND:
            self.actions_expanded = not self.actions_expanded
        else:
            return
        live = self._live
        if live is not None:
            live.refresh()  # answer the key now, not at the next 250 ms tick

    # --- output hooks -------------------------------------------------------------
    # While the full-screen view is up the frame is redrawn from ``self.events``;
    # before it starts and after it stops, lines print plainly so nothing said
    # outside the live window is lost.

    def _emit_line_locked(self, line: str, kind: str) -> None:
        if self._live is None:
            self.stream.write(f"{style(line, kind, enabled=True)}\n")
            self.stream.flush()

    def _emit_inline_locked(self, text: str, kind: str) -> None:
        if self._live is None:
            self.stream.write(style(text, kind, enabled=True))
            self.stream.flush()

    def _clear_footer_locked(self) -> None:
        return

    def _render_footer_locked(self) -> None:
        return

    # --- rendering ------------------------------------------------------------------

    def _frame(self) -> _Frame:
        with self._lock:
            return _Frame(
                state=replace(self.state),
                run=self.run,
                events=self.events.tail(),
                viewer_status=self.viewer_status,
                viewer_url=self.viewer_run_url,
                viewer_detail=self.viewer_detail,
                finished=self.finished,
            )

    def snapshot(self, *, force: bool = False) -> RunSnapshot | None:
        """The attached run's snapshot, re-read at most once a second."""
        with self._lock:
            run = self.run
            # "" = the run is over, so no stage is live (see load_snapshot).
            active = "" if self.finished else (self.state.stage_id or None)
        if run is None:
            return None
        key = (run, active)
        now = time.monotonic()
        with self._snapshot_lock:
            fresh = now - self._snapshot_at < SNAPSHOT_INTERVAL_SECONDS
            if (
                not force
                and fresh
                and self._snapshot_key == key
                and self._snapshot_value is not None
            ):
                return self._snapshot_value
            try:
                value = load_snapshot(
                    run.report_dir,
                    stage_ids=run.stage_ids,
                    active_stage_id=active,
                    cache=self._snapshot_cache,
                )
            except Exception:
                logger.debug("Run snapshot read failed", exc_info=True)
                value = self._snapshot_value
            self._snapshot_value, self._snapshot_key, self._snapshot_at = value, key, now
            return value

    def _render(self) -> RenderableType:
        try:
            return self.renderable()
        except Exception as exc:  # keep the refresh thread alive whatever happens
            logger.debug("Console frame failed to render", exc_info=True)
            return Text(f"console render error: {_safe(exc)}", style=RED)

    def renderable(self, *, width: int | None = None, height: int | None = None) -> RenderableType:
        """The whole screen for the current state (also used by tests)."""
        size = self._rich.size
        width = width or size.width
        height = height or size.height
        frame = self._frame()
        snapshot = self.snapshot()
        spinner = SPINNER_FRAMES[int(time.monotonic() * 4) % len(SPINNER_FRAMES)]

        side = sidebar_width(width)
        main_width = width - side
        main = Layout(name="main")
        main.split_column(
            Layout(self._trace_panel(frame, main_width, max(3, height - 1)), name="trace", ratio=1),
            Layout(self._status_row(frame, spinner), name="status", size=1),
        )
        if not side:
            return main
        root = Layout(name="root")
        root.split_row(
            main,
            Layout(
                self._sidebar(frame, snapshot, spinner, side, height), name="sidebar", size=side
            ),
        )
        return root

    def _trace_rows(
        self, events: list[ConsoleEvent], width: int, *, finished: bool = False
    ) -> list[tuple[int, int, Text]]:
        """The trace wrapped to *width*, as ``(seq, line, text)`` rows.

        Tool bursts fold into one :class:`ActionGroup` block keyed by its first
        event. Wrapping the whole log each frame would be slow, so each block's
        lines are cached until its content, the width, or the expand state changes.
        """
        items = group_events(events)
        expanded, hint = self.actions_expanded, self._input_active
        rows: list[tuple[int, int, Text]] = []
        with self._wrap_lock:
            cache = self._wrap_cache
            seen: set[int] = set()
            for position, item in enumerate(items):
                if isinstance(item, ActionGroup):
                    active = position == len(items) - 1 and not finished
                    content = tuple((event.seq, len(event.text)) for event in item.events)
                    key: tuple[Any, ...] = ("group", content, expanded, active, hint, width)
                else:
                    key = (item.kind, len(item.text), width)
                seq = item.seq
                seen.add(seq)
                cached = cache.get(seq)
                if cached is None or cached[0] != key:
                    if isinstance(item, ActionGroup):
                        texts = format_action_group(
                            item, expanded=expanded, active=active, hint=hint
                        )
                    else:
                        rendered = format_event(item)
                        texts = [rendered] if rendered is not None else []
                    lines = [
                        line
                        for text in texts
                        for line in text.wrap(self._rich, width, overflow="fold")
                    ]
                    cache[seq] = (key, lines)
                else:
                    lines = cached[1]
                rows.extend((seq, index, line) for index, line in enumerate(lines))
            for stale in [seq for seq in cache if seq not in seen]:
                del cache[stale]
        return rows

    def _trace_panel(self, frame: _Frame, width: int, height: int) -> Panel:
        inner_width = max(10, width - 4)
        inner_height = max(1, height - 2)
        rows = self._trace_rows(frame.events, inner_width, finished=frame.finished)
        top, below = self.scroll.window([(seq, line) for seq, line, _ in rows], inner_height)
        visible = [text for _, _, text in rows[top : top + inner_height]]
        while visible and not visible[0].plain.strip():
            visible.pop(0)
        body = (
            Text("\n").join(visible) if visible else Text("Waiting for the first stage…", style=DIM)
        )
        title = Text.assemble((" Hyper", WHITE), ("Agent ", f"bold {WHITE}"))
        if frame.run is not None:
            title.append_text(Text(f"· {frame.run.sample_sha256[:12]} ", style=DIM))
        subtitle = None
        if below:
            subtitle = Text.assemble(
                (f" ↓ {below} more line{'s' if below != 1 else ''} ", AMBER),
                ("· End to follow ", DIM),
            )
        return Panel(
            body,
            title=title,
            title_align="left",
            subtitle=subtitle,
            subtitle_align="right",
            border_style=DARK,
            padding=(0, 1),
        )

    def _status_row(self, frame: _Frame, spinner: str) -> Table:
        state = frame.state
        left = Text(" ")
        if frame.finished:
            left.append("■ ", style=DIM)
            left.append("finished", style=WHITE)
        else:
            left.append(f"{spinner} ", style=GREEN)
            left.append(_safe(state.activity) or "idle", style=WHITE)
        if state.stage_index and state.stage_total:
            left.append(f"  ·  Stage {state.stage_index:02d}/{state.stage_total:02d} ", style=DIM)
            left.append(state.stage_id, style=TEXT)
            if state.attempt > 1:
                left.append(f" attempt {state.attempt}", style=AMBER)
        left.append(f"  ·  {format_elapsed(state.elapsed_seconds)}", style=DIM)
        if state.context_cap:
            percent = state.context_percent
            color = RED if percent >= 90 else AMBER if percent >= 75 else DIM
            left.append(f"  ·  ctx {percent:.1f}%", style=color)
            if state.turn and state.max_turns:
                left.append(f" turn {state.turn}/{state.max_turns}", style=DIM)

        right = Text("")
        if self._input_active:
            right.append_text(Text.assemble(("↑↓ PgUp PgDn", WHITE), (" scroll  ", DIM)))
            label = "collapse" if self.actions_expanded else "expand"
            right.append_text(Text.assemble(("ctrl+o", WHITE), (f" {label}  ", DIM)))
        if not frame.finished:
            right.append_text(Text.assemble(("ctrl-c", WHITE), (" stop ", DIM)))
        grid = Table.grid(expand=True)
        grid.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
        grid.add_column(no_wrap=True, justify="right")
        grid.add_row(left, right)
        return grid

    # --- sidebar ---------------------------------------------------------------------

    def _sidebar(
        self,
        frame: _Frame,
        snapshot: RunSnapshot | None,
        spinner: str,
        width: int,
        height: int,
    ) -> Layout:
        inner = width - 4
        viewer_rows = self._viewer_rows(frame, inner)
        stage_rows = stage_rows_for(snapshot, frame.state, spinner, inner)
        stats_rows = self._stats_rows(frame, snapshot, inner)

        completed = snapshot.completed_count if snapshot else 0
        total = len(snapshot.stages) if snapshot else 0
        parts: list[tuple[str, Panel, int]] = [
            ("viewer", _box(viewer_rows), len(viewer_rows) + 2),
            ("stages", _box(stage_rows, f"Stages {completed}/{total}"), len(stage_rows) + 2),
        ]

        indicators = snapshot.indicators if snapshot else ()
        findings = snapshot.findings_newest_first if snapshot else []
        evidence_total = snapshot.evidence_total if snapshot else 0
        flex = height - parts[0][2] - parts[1][2] - (len(stats_rows) + 2)
        if flex >= 6:
            ioc_need = max(1, len(indicators)) + 2
            evidence_need = max(1, len(findings)) + 2
            ioc_height = (
                ioc_need if ioc_need + evidence_need <= flex else min(ioc_need, max(3, flex // 2))
            )
            evidence_height = flex - ioc_height
            parts.append(
                (
                    "iocs",
                    _box(ioc_rows(indicators, ioc_height - 2, inner), f"IoCs {len(indicators)}"),
                    ioc_height,
                )
            )
            parts.append(
                (
                    "evidence",
                    _box(
                        evidence_rows(findings, evidence_height - 2, inner),
                        f"Evidence {evidence_total} · {len(findings)} findings",
                    ),
                    evidence_height,
                )
            )
        elif flex >= 3:
            parts.append(
                (
                    "iocs",
                    _box(ioc_rows(indicators, flex - 2, inner), f"IoCs {len(indicators)}"),
                    flex,
                )
            )
        parts.append(("stats", _box(stats_rows), len(stats_rows) + 2))

        layout = Layout(name="sidebar")
        regions = [Layout(panel, name=name, size=size) for name, panel, size in parts]
        # The last region absorbs any rounding slack instead of leaving a gap.
        regions[-1] = Layout(parts[-1][1], name=parts[-1][0], ratio=1, minimum_size=1)
        layout.split_column(*regions)
        return layout

    def _viewer_rows(self, frame: _Frame, inner: int) -> list[Text]:
        if frame.viewer_status == "running" and frame.viewer_url:
            head = Text.assemble(("▶ ", GREEN), ("Watch live in browser", f"bold {WHITE}"))
            link = Text(
                frame.viewer_url, style=Style(color=CYAN, underline=True, link=frame.viewer_url)
            )
            return [head, *link.wrap(self._rich, inner, overflow="fold")]
        if frame.viewer_status == "failed":
            head = Text.assemble(("▶ ", RED), ("Live dashboard unavailable", RED))
            return [
                head,
                _clip(Text(_safe(frame.viewer_detail) or "failed to start", style=DIM), inner),
            ]
        return [
            Text.assemble(("▶ ", DIM), ("Watch live in browser", DIM)),
            Text("dashboard off (--no-dashboard)", style=DIM),
        ]

    def _stats_rows(self, frame: _Frame, snapshot: RunSnapshot | None, inner: int) -> list[Text]:
        rows: list[Text] = []
        if snapshot is not None and snapshot.verdict is not None:
            verdict = snapshot.verdict
            row = Text.assemble(
                ("Verdict ", DIM),
                (_safe(verdict.value).upper(), f"bold {_VERDICT_COLORS.get(verdict.value, TEXT)}"),
            )
            if verdict.confidence is not None:
                row.append(f" {verdict.confidence:.2f}", style=DIM)
            rows.append(_clip(row, inner))
        if frame.run is not None and frame.run.model:
            rows.append(_clip(Text(_safe(frame.run.model), style=WHITE), inner))
        if frame.run is not None:
            rows.append(_clip(Text(f"sha {frame.run.sample_sha256}", style=DIM), inner))
        if snapshot is not None and snapshot.last_error:
            rows.append(_clip(Text(_safe(snapshot.last_error), style=RED), inner))
        rows.append(Text(f"HyperAgent v{__version__}", style=DIM))
        return rows

    # --- final recap -----------------------------------------------------------------

    def _print_final_summary(self) -> None:
        """Leaving the alternate screen erases the frame, so restate the outcome."""
        frame = self._frame()
        snapshot = self.snapshot(force=True)
        width = min(self._rich.width, 100)
        inner = width - 4
        lines: list[Text] = []
        if snapshot is not None and snapshot.stages:
            lines.extend(stage_rows_for(snapshot, frame.state, "■", inner))
            lines.append(Text(""))
            facts = Text.assemble(("IoCs ", DIM), (str(len(snapshot.indicators)), WHITE))
            facts.append("  ·  Evidence ", style=DIM)
            facts.append(str(snapshot.evidence_total), style=WHITE)
            if snapshot.verdict is not None:
                facts.append("  ·  Verdict ", style=DIM)
                facts.append(
                    _safe(snapshot.verdict.value).upper(),
                    style=f"bold {_VERDICT_COLORS.get(snapshot.verdict.value, TEXT)}",
                )
            lines.append(facts)
            lines.append(_clip(Text(f"Report  {snapshot.report_dir}", style=DIM), inner))
            if snapshot.last_error:
                lines.append(Text(f"Last error  {_safe(snapshot.last_error)}", style=RED))
        else:
            lines.append(Text("The run ended before any stage started.", style=DIM))
        if frame.viewer_status == "running":
            lines.append(
                Text(
                    "The live dashboard stopped with this process; browse finished reports with "
                    "`python webui/app.py`.",
                    style=DIM,
                )
            )

        title = Text.assemble(
            (" HyperAgent ", f"bold {WHITE}"),
            (f"· {format_elapsed(frame.state.elapsed_seconds)} ", DIM),
        )
        self._rich.print(
            Panel(Group(*lines), title=title, title_align="left", border_style=DARK, width=width)
        )

        alerts = [
            event for event in frame.events if event.kind in ("warn", "error", "result_error")
        ][-6:]
        for event in alerts:
            rendered = format_event(event)
            if rendered is not None:
                rendered.truncate(width, overflow="ellipsis")
                self._rich.print(rendered)


def _box(rows: list[Text], title: str | None = None) -> Panel:
    return Panel(
        Text("\n").join(rows) if rows else Text(""),
        title=Text(f" {title} ", style=TEXT) if title else None,
        title_align="left",
        border_style=DARK,
        padding=(0, 1),
    )


def _stage_row(stage: StageProgress, state: RunConsoleState, spinner: str, inner: int) -> Text:
    detail, detail_style = "", DIM
    if stage.status == STATUS_COMPLETED:
        glyph, glyph_style, name_style = "✓", GREEN, TEXT
        if stage.artifact_status and stage.artifact_status not in ("completed", "not_needed"):
            detail, detail_style = _safe(stage.artifact_status), AMBER
        elif stage.evidence:
            detail = f"{stage.evidence} ev"
    elif stage.status == STATUS_RUNNING:
        glyph, glyph_style, name_style = spinner, GREEN, f"bold {WHITE}"
        if stage.stage_id == state.stage_id and state.attempt > 1:
            detail, detail_style = f"attempt {state.attempt}", AMBER
        else:
            detail, detail_style = "running", GREEN
    elif stage.status == STATUS_CHECKPOINTED:
        glyph, glyph_style, name_style = "◔", AMBER, TEXT
        detail, detail_style = "resumable", AMBER
    elif stage.status == STATUS_FAILED:
        glyph, glyph_style, name_style = "✗", RED, RED
        detail, detail_style = "failed", RED
    else:
        glyph, glyph_style, name_style = "○", DIM, DIM
    return _spread(
        Text.assemble((f"{glyph} ", glyph_style), (stage.stage_id, name_style)),
        Text(detail, style=detail_style),
        inner,
    )


def stage_rows_for(
    snapshot: RunSnapshot | None,
    state: RunConsoleState,
    spinner: str,
    inner: int,
) -> list[Text]:
    if snapshot is None or not snapshot.stages:
        return [Text("waiting for the run to start…", style=DIM)]
    return [_stage_row(stage, state, spinner, inner) for stage in snapshot.stages]


def ioc_rows(indicators: Any, limit: int, inner: int) -> list[Text]:
    if not indicators:
        return [Text("none yet", style=DIM)]
    limit = max(1, limit)
    shown = list(indicators)
    overflow = 0
    if len(shown) > limit:
        overflow = len(shown) - (limit - 1)
        shown = shown[: limit - 1]
    rows = []
    for item in shown:
        label, color = _IOC_LABELS.get(item.group, (item.group[:4].upper().ljust(4), TEXT))
        rows.append(_clip(Text.assemble((label, color), " ", (_safe(item.value), TEXT)), inner))
    if overflow:
        rows.append(Text(f"+{overflow} more", style=DIM))
    return rows


def evidence_rows(findings: list[FindingBrief], limit: int, inner: int) -> list[Text]:
    if not findings:
        return [Text("none yet", style=DIM)]
    limit = max(1, limit)
    shown = findings
    overflow = 0
    if len(shown) > limit:
        overflow = len(shown) - (limit - 1)
        shown = shown[: limit - 1]
    rows = []
    for item in shown:
        glyph, color = _FINDING_GLYPHS.get(item.status, ("○", DIM))
        right = Text(f"{item.confidence:.2f}" if item.confidence is not None else "", style=DIM)
        rows.append(
            _spread(Text.assemble((f"{glyph} ", color), (_safe(item.title), TEXT)), right, inner)
        )
    if overflow:
        rows.append(Text(f"+{overflow} more", style=DIM))
    return rows
