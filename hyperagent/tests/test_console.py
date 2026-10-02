"""Tests for hyperagent.console."""
from __future__ import annotations

import json
from io import StringIO
from logging import LogRecord

from hyperagent.console import (
    ConsoleEventLog,
    ConsoleLogHandler,
    RunConsole,
    collapse_whitespace,
    create_run_console,
    format_elapsed,
    preview_json_or_text,
    sanitize_terminal_text,
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


def test_console_records_semantic_events_for_live_views():
    console = RunConsole(stream=_NoTTYStringIO(), enabled=True, force_tty=False)

    console.stage_transition(index=1, total=2, stage_id="01-prepare-env")
    console.assistant_label()
    console.write_inline("partial ")
    console.write_inline("answer\n")
    console.tool_call("lookup", {"q": 1})
    console.tool_result("found", is_error=False)
    console.tool_result("broke", is_error=True)

    events = [(event.kind, event.text) for event in console.events.tail()]
    assert events == [
        ("stage", "Stage 1/2 → 01-prepare-env"),
        ("assistant", "partial answer\n"),
        ("tool", 'lookup({"q":1})'),
        ("result", "found"),
        ("result_error", "broke"),
    ]


def test_console_neutralizes_terminal_escapes_in_output_and_events():
    stream = _NoTTYStringIO()
    console = RunConsole(stream=stream, enabled=True, force_tty=False)

    console.tool_result("value \x1b[2J\x1b]0;title\x07 done")
    console.write_inline("bidi \u202e text")

    output = stream.getvalue()
    assert "\x1b" not in output and "\u202e" not in output
    assert "\\x1b[2J" in output and "\\u202e" in output
    assert "\x1b" not in console.events.tail()[0].text


def test_sanitize_terminal_text_keeps_newlines_and_tabs():
    assert sanitize_terminal_text("a\tb\r\nc\x00") == "a\tb\nc\\x00"


def test_event_log_is_bounded_and_caps_streamed_blocks():
    log = ConsoleEventLog(maxlen=3)
    for index in range(5):
        log.add("info", str(index))
    assert [event.text for event in log.tail()] == ["2", "3", "4"]

    log.begin("assistant")
    log.extend("x" * (ConsoleEventLog.MAX_EVENT_CHARS + 10))
    newest = log.tail(1)[0]
    assert newest.text.startswith("…")
    assert len(newest.text) == ConsoleEventLog.MAX_EVENT_CHARS + 1


def test_live_feed_hooks_answer_only_for_the_bound_run(tmp_path):
    stream = _NoTTYStringIO()
    console = RunConsole(stream=stream, enabled=True, force_tty=False)
    sha = "A" * 64
    console.set_viewer("running", url="http://127.0.0.1:5000/")

    assert console.live_status(sha) is None
    assert console.active_runs() == []

    console.bind_run(
        sample_sha256=sha, report_dir=tmp_path, stage_ids=["01-prepare-env"], model="m"
    )
    console.start()
    console.stage_transition(index=1, total=1, stage_id="01-prepare-env")

    assert "▶ Watch live in browser: http://127.0.0.1:5000/live/" + "a" * 64 in stream.getvalue()
    assert console.report_dir_for(sha) == tmp_path
    assert console.report_dir_for("b" * 64) is None
    status = console.live_status(sha.lower())
    assert status["active_stage_id"] == "01-prepare-env"
    assert status["stage_ids"] == ["01-prepare-env"]
    assert status["events"][-1]["kind"] == "stage"
    assert status["events"][-1]["clock"].count(":") == 2

    console.finish()
    # "" (not None): known that nothing is running, so a checkpointed stage
    # reads as resumable rather than live.
    assert console.live_status(sha)["active_stage_id"] == ""
    assert console.active_runs()[0]["finished"] is True


def test_failed_viewer_is_reported_as_a_warning():
    stream = _NoTTYStringIO()
    console = RunConsole(stream=stream, enabled=True, force_tty=False)

    console.set_viewer("failed", detail="no free port")

    assert "Live dashboard unavailable: no free port" in stream.getvalue()


def test_create_run_console_falls_back_to_lines_when_not_a_terminal():
    console = create_run_console(stream=_NoTTYStringIO())

    assert type(console) is RunConsole
    assert type(create_run_console(stream=_TTYStringIO(), prefer_tui=False)) is RunConsole


def test_bound_console_saves_its_output_to_the_report_dir(tmp_path):
    console = RunConsole(stream=_NoTTYStringIO(), enabled=True, force_tty=False)
    console.write_line("said before the run was bound", kind="warn")
    console.bind_run(sample_sha256="A" * 64, report_dir=tmp_path, stage_ids=["01-prepare-env"])
    console.start()
    console.stage_transition(index=1, total=1, stage_id="01-prepare-env")
    console.assistant_label()
    console.write_inline("streamed ")
    path = tmp_path / "console.jsonl"

    def kinds() -> list[str]:
        return [json.loads(line)["kind"] for line in path.read_text(encoding="utf-8").splitlines()]

    # The streamed block is still growing, so it is not on disk yet.
    assert kinds() == ["session", "warn", "stage"]

    console.write_inline("answer")
    console.tool_call("lookup", {"q": "\x1b[2J"})
    assert kinds() == ["session", "warn", "stage", "assistant", "tool"]

    console.assistant_label()
    console.write_inline("still open at exit")
    console.finish()
    console.finish()

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [record["text"] for record in records][3:] == [
        "streamed answer",
        'lookup({"q":"\\u001b[2J"})',
        "still open at exit",
    ]
    assert "\x1b" not in path.read_text(encoding="utf-8")
    assert len({record["session"] for record in records}) == 1


def test_event_log_closed_since_leaves_out_the_open_block():
    log = ConsoleEventLog()
    log.add("info", "a")
    log.begin("assistant")
    log.extend("partial")

    assert [event.text for event in log.closed_since(0)] == ["a"]
    assert [event.text for event in log.closed_since(0, include_open=True)] == ["a", "partial"]
    assert log.closed_since(2, include_open=True) == []
