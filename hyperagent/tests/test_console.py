"""Tests for hyperagent.console."""
from __future__ import annotations

from io import StringIO
from logging import LogRecord

from hyperagent.console import (
    ConsoleLogHandler,
    RunConsole,
    collapse_whitespace,
    format_elapsed,
    preview_json_or_text,
    truncate_preview,
)


class _TTYStringIO(StringIO):
    def isatty(self) -> bool:
        return True


class _NoTTYStringIO(StringIO):
    def isatty(self) -> bool:
        return False


class _FakeConsole:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str]] = []

    def write_line(self, text, *, kind="info", collapse=True):
        self.lines.append((kind, text))


def test_preview_helpers_collapse_and_truncate():
    assert collapse_whitespace("alpha\n beta\t gamma") == "alpha beta gamma"

    preview = truncate_preview("alpha " * 40, max_chars=60)
    assert "collapsed" in preview
    assert preview.startswith("alpha")

    assert preview_json_or_text({"q": "a b", "n": 1}, max_chars=40).startswith('{"q":"a b"')


def test_format_elapsed_compacts_time_counter():
    assert format_elapsed(0) == "00:00"
    assert format_elapsed(65) == "01:05"
    assert format_elapsed(3661) == "1:01:01"


    stream = _NoTTYStringIO()
    console = RunConsole(stream=stream, enabled=True, force_tty=False, preview_chars=100)

    console.start()
    console.stage_transition(index=1, total=9, stage_id="01-prepare-env", stage_name="hyperagent-prepare-env", attempt=1, guarded=True)
    console.tool_call("lookup", {"query": "A" * 120})
    console.tool_result("line1\nline2", is_error=False)
    console.finish()

    output = stream.getvalue()
    assert "\033[" not in output
    assert "Stage 1/9 → 01-prepare-env" in output
    assert "tool lookup({\"query\":\"AAAAAAAA" in output
    assert "collapsed" in output
    assert "line1 line2" in output


def test_run_console_tty_renders_footer_and_clears_it():
    stream = _TTYStringIO()
    console = RunConsole(stream=stream, enabled=True, force_tty=True, preview_chars=120)

    console.start()
    console.set_stage(index=2, total=9, stage_id="02-static-pass1", stage_name="hyperagent-static", attempt=3)
    console.set_context(turn=4, max_turns=100, tokens=1234, cap=200000)
    console.write_line("stage update", kind="stage")
    console.finish()

    output = stream.getvalue()
    assert "\0337\033[999;1H\033[2K" in output
    assert "Stage 02/09 02-static-pass1 attempt 3" in output
    assert "Time 00:00" in output
    assert "Context 1,234/200,000 0.6% turn 4/100" in output
    assert "stage update" in output
    assert console.footer_active is False


def test_console_log_handler_routes_records_to_console():
    console = _FakeConsole()
    handler = ConsoleLogHandler(console)  # type: ignore[arg-type]
    record = LogRecord("hyperagent", 20, __file__, 1, "hello world", args=(), exc_info=None)

    handler.emit(record)

    assert console.lines == [("muted", "hello world")]
