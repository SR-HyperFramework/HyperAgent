"""Tests for hyperagent.tui (the full-screen sidebar console)."""

from __future__ import annotations

import re
import sys
from io import StringIO
from pathlib import Path

from rich.console import Console

from hyperagent.console import ConsoleEvent
from hyperagent.tests.live_fixtures import SHA, build_run_dir
from hyperagent.tui import (
    SidebarConsole,
    TraceScroll,
    format_event,
    sidebar_width,
    tui_supported,
)
from hyperagent.tui_input import (
    END,
    EXPAND,
    HOME,
    PAGE_DOWN,
    PAGE_UP,
    UP,
    WHEEL_DOWN,
    WHEEL_UP,
    parse_vt_input,
    windows_key_action,
)

STAGES = (
    "01-prepare-env",
    "02-static-pass1",
    "03-unpack",
    "04-static-pass2",
    "05-dynamic",
    "07-deepdive",
)


def _console(width: int = 150, height: int = 42) -> tuple[SidebarConsole, Console]:
    rich_console = Console(
        file=StringIO(),
        width=width,
        height=height,
        force_terminal=True,
        color_system=None,
        legacy_windows=False,
        record=True,
    )
    return SidebarConsole(stream=StringIO(), rich_console=rich_console), rich_console


def _screen(console: SidebarConsole, rich_console: Console) -> str:
    rich_console.print(console.renderable())
    return rich_console.export_text()


def _bound(tmp_path: Path, **kwargs) -> tuple[SidebarConsole, Console]:
    console, rich_console = _console(**kwargs)
    report_dir = build_run_dir(tmp_path)
    console.set_viewer("running", url="http://127.0.0.1:5000/")
    console.bind_run(
        sample_sha256=SHA, report_dir=report_dir, stage_ids=STAGES, model="claude-opus-5-5"
    )
    console.stage_transition(
        index=4, total=6, stage_id="04-static-pass2", stage_name="hyperagent-static", attempt=2
    )
    return console, rich_console


def test_sidebar_width_hides_sidebar_on_narrow_terminals():
    assert sidebar_width(99) == 0
    assert sidebar_width(120) == 34
    assert sidebar_width(400) == 48


def test_sidebar_shows_viewer_stages_iocs_evidence_and_stats(tmp_path: Path):
    console, rich_console = _bound(tmp_path)
    console.tool_call("read_file", {"path": "02-static-pass1.json"})
    console.tool_result("loaded", is_error=False)

    screen = _screen(console, rich_console)

    # The browser block sits at the top of the sidebar, above the stage list.
    assert "Watch live in browser" in screen
    assert f"http://127.0.0.1:5000/live/{SHA}"[:30] in screen
    assert screen.index("Watch live in browser") < screen.index("Stages 3/6")
    assert "✓ 02-static-pass1" in screen
    assert "◔ 03-unpack" in screen
    assert "resumable" in screen
    assert "attempt 2" in screen
    assert "IoCs 3" in screen
    assert "evil.example.com" in screen
    assert "Evidence 6 · 3 findings" in screen
    assert "Decoded payload executed" in screen
    assert "Verdict SUSPICIOUS 0.60" in screen
    assert "claude-opus-5-5" in screen
    # Trace pane and status row.
    assert "◆ Read 1 file" in screen  # tool bursts are collapsed by default
    assert "read_file" not in screen
    assert "Stage 04/06 04-static-pass2" in screen
    assert "ctrl-c stop" in screen


def test_sample_derived_text_cannot_inject_terminal_escapes(tmp_path: Path):
    console, rich_console = _bound(tmp_path)
    console.write_line("log line with \x1b]0;pwned\x07 title escape", kind="warn")

    rich_console.print(console.renderable())
    raw = rich_console.file.getvalue()

    assert "\x1b[2J" not in raw
    assert "\x1b]0;pwned" not in raw
    assert "\\x1b[2J" in rich_console.export_text()


def test_narrow_terminal_drops_the_sidebar(tmp_path: Path):
    console, rich_console = _bound(tmp_path, width=90)

    screen = _screen(console, rich_console)

    assert "Stages 3/6" not in screen
    assert "Stage 04/06 04-static-pass2" in screen
    # The dashboard link stays reachable through the trace line bind_run wrote.
    assert "▶ Watch live in browser:" in screen
    assert "http://127.0.0.1:5000/live/" in screen


def test_failed_dashboard_is_reported_in_the_viewer_block(tmp_path: Path):
    console, rich_console = _console()
    console.set_viewer("failed", detail="no free port in 5000-5009")

    screen = _screen(console, rich_console)

    assert "Live dashboard unavailable" in screen
    assert "no free port" in screen


def test_format_event_styles_each_kind():
    assert format_event(ConsoleEvent(seq=1, kind="assistant", text="   \n")) is None
    tool = format_event(ConsoleEvent(seq=2, kind="tool", text='lookup({"q":1})'))
    assert tool is not None and tool.plain == '→ lookup({"q":1})'
    stage = format_event(ConsoleEvent(seq=3, kind="stage", text="Stage 1/2 → 01-prepare-env"))
    assert stage is not None and stage.plain.startswith("\n▌ Stage 1/2")


def test_live_session_captures_prints_and_restores_streams(tmp_path: Path):
    console, rich_console = _bound(tmp_path)
    original = (sys.stdout, sys.stderr)

    console.start()
    try:
        print("stray print during the run")
        assert sys.stdout is not original[0]
    finally:
        console.finish()

    assert (sys.stdout, sys.stderr) == original
    assert any(event.text == "stray print during the run" for event in console.events.tail())
    # Leaving the alternate screen erases the frame, so a recap is printed.
    recap = rich_console.export_text()
    assert "✓ 02-static-pass1" in recap
    # Once the run is over nothing is live: the checkpoint reads as resumable
    # and the stage that was executing is no longer shown as running.
    assert "◔ 03-unpack" in recap and "resumable" in recap
    assert "○ 04-static-pass2" in recap
    assert "IoCs 3" in recap
    assert "live dashboard stopped" in recap
    # finish() is idempotent: the CLI and the launcher both call it.
    console.finish()


def test_lines_print_plainly_outside_the_live_window(tmp_path: Path):
    stream = StringIO()
    console = SidebarConsole(
        stream=stream, rich_console=Console(file=StringIO(), force_terminal=True)
    )

    console.write_line("before start", kind="warn")

    assert "before start" in stream.getvalue()
    assert console.events.tail()[-1].text == "before start"


class _Terminal(StringIO):
    def __init__(self, encoding: str) -> None:
        super().__init__()
        self._encoding = encoding

    @property
    def encoding(self) -> str:  # type: ignore[override]
        return self._encoding

    def isatty(self) -> bool:
        return True


def test_tui_requires_a_utf8_terminal(monkeypatch):
    monkeypatch.delenv("TERM", raising=False)
    monkeypatch.setattr("rich.console.detect_legacy_windows", lambda: False)

    assert tui_supported(_Terminal("utf-8")) is True
    assert tui_supported(_Terminal("cp1252")) is False
    assert tui_supported(StringIO()) is False


def _trace_lines(console: SidebarConsole, count: int) -> None:
    for index in range(count):
        console.write_line(f"trace line {index:03d}", kind="info")


def test_trace_scrolls_back_and_holds_still_while_output_arrives(tmp_path: Path):
    console, rich_console = _bound(tmp_path, width=150, height=30)
    _trace_lines(console, 120)

    following = _screen(console, rich_console)
    assert "trace line 119" in following and "more line" not in following

    console.scroll.page(-2)
    scrolled = console.renderable()
    rich_console.print(scrolled)
    screen = rich_console.export_text()
    assert "trace line 119" not in screen
    assert "more lines" in screen and "End to follow" in screen
    visible_top = min(int(n) for n in re.findall(r"trace line (\d{3})", screen))

    # New output does not drag a scrolled view along with it.
    for index in range(5):
        console.write_line(f"late line {index}", kind="info")
    screen = _screen(console, rich_console)
    assert min(int(n) for n in re.findall(r"trace line (\d{3})", screen)) == visible_top

    console.scroll.home()
    screen = _screen(console, rich_console)
    assert "Stage 4/6" in screen and "trace line 000" in screen  # oldest output on top
    console.scroll.end()
    screen = _screen(console, rich_console)
    assert "late line 4" in screen and "more line" not in screen
    assert console.scroll.following


def test_scrolling_down_to_the_bottom_resumes_following():
    scroll = TraceScroll()
    keys = [(seq, 0) for seq in range(50)]

    assert scroll.window(keys, 10) == (40, 0)
    scroll.scroll(-15)
    assert scroll.window(keys, 10) == (25, 15)
    # Ten more rows arrive: the anchored view stays put.
    keys += [(seq, 0) for seq in range(50, 60)]
    assert scroll.window(keys, 10) == (25, 25)
    scroll.scroll(1000)
    assert scroll.window(keys, 10) == (50, 0)
    assert scroll.following
    scroll.scroll(-1000)
    assert scroll.window(keys, 10) == (0, 50)
    # The anchored event aged out of the bounded log: clamp to the oldest row.
    assert scroll.window(keys[5:], 10) == (0, 45)


def test_key_and_wheel_input_drive_the_scroll(tmp_path: Path):
    console, _ = _bound(tmp_path)
    _trace_lines(console, 100)
    console.renderable()

    console._on_input(PAGE_UP)
    console._on_input(WHEEL_UP)
    console._on_input(UP)
    console.renderable()
    assert not console.scroll.following
    console._on_input(END)
    console.renderable()
    assert console.scroll.following


def test_vt_input_parser_reads_keys_and_wheel_across_reads():
    keys = "x\x1b[A\x1b[5~\x1b[<64;10;5M\x1b[<65;1;1M\x1b[<0;1;1M\x1bOF\x1b["
    actions, rest = parse_vt_input(keys)
    assert actions == [UP, PAGE_UP, WHEEL_UP, WHEEL_DOWN, END]
    assert rest == "\x1b["
    actions, rest = parse_vt_input(rest + "6~\x1b[1~")
    assert actions == [PAGE_DOWN, HOME] and rest == ""
    assert windows_key_action(0x21) == PAGE_UP and windows_key_action(0x41) is None


def test_tool_bursts_collapse_to_a_summary_and_expand_on_ctrl_o(tmp_path: Path):
    console, rich_console = _bound(tmp_path)
    console.assistant_label()
    console.write_inline("Checking the unpacked layer.")
    console.tool_call("read_file", {"path": r"C:\reports\x\02-static-pass1.json"})
    console.tool_call("read_file", {"path": "03-unpack.json"})
    console.tool_call("vm_run_program", {"program": r"C:\Tools\procmon.exe"})
    console.tool_call("decompile", {"addr": "0x401000"})
    console.write_line("Calling tool: read_file", kind="muted")
    console.tool_result("ok", name="read_file")
    console.write_line("Calling tool: read_file", kind="muted")
    console.tool_result("Error: no such file", is_error=True, name="read_file")
    console.write_line("Tool read_file returned an error", kind="warn")
    console.write_line("Calling tool: vm_run_program", kind="muted")
    console.tool_result("exit 0", name="vm_run_program")

    screen = _screen(console, rich_console)

    assert "◆ Read 2 files, ran 1 command, called 1 tool · 1 failed" in screen
    assert "⎿ ✗ Read 03-unpack.json  Error: no such file" in screen
    assert "⎿ Decompiled 0x401000 …" in screen  # still waiting for its result
    assert "Calling tool" not in screen and "procmon" not in screen

    console._on_input(EXPAND)
    screen = _screen(console, rich_console)
    assert "→ vm_run_program" in screen and "Calling tool: vm_run_program" in screen
    assert "◆" not in screen

    console._on_input(EXPAND)
    console.tool_result("int main() {}", name="decompile")
    console.write_line("Context nearing the cap", kind="warn")
    screen = _screen(console, rich_console)
    assert "…" not in screen.split("◆")[1].split("\n")[1]  # nothing pending now
    assert "! Context nearing the cap" in screen  # trailing warnings stay visible
