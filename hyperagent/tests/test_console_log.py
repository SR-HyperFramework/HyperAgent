"""Tests for hyperagent.console_log (the on-disk console transcript)."""

from __future__ import annotations

import json
from pathlib import Path

from hyperagent.console_log import (
    ConsoleTranscript,
    console_log_path,
    has_console_log,
    read_console_log,
)


def _write_session(report_dir: Path, texts: list[str]) -> None:
    transcript = ConsoleTranscript(console_log_path(report_dir))
    transcript.open("Console session", timestamp=1_700_000_000.0)
    for seq, text in enumerate(texts, start=1):
        transcript.write(seq=seq, kind="info", text=text, timestamp=1_700_000_000.0 + seq)
    transcript.close()


def test_transcript_round_trips_and_appends_sessions(tmp_path: Path):
    _write_session(tmp_path, ["one", "two"])
    _write_session(tmp_path, ["three"])

    saved = read_console_log(tmp_path)

    assert saved.exists and saved.sessions == 2 and saved.total == 5
    assert [event["text"] for event in saved.events] == [
        "Console session",
        "one",
        "two",
        "Console session",
        "three",
    ]
    assert saved.events[1]["ts"] == "2023-11-14T22:13:21Z"
    assert saved.events[1]["clock"].count(":") == 2
    assert has_console_log(tmp_path)


def test_reader_skips_damaged_lines_and_honours_limit(tmp_path: Path):
    _write_session(tmp_path, [f"line {n}" for n in range(10)])
    with console_log_path(tmp_path).open("a", encoding="utf-8") as handle:
        handle.write('{"seq": 99, "kind": "info", "te')  # cut off by a crash
        handle.write("\n[1, 2]\n")

    saved = read_console_log(tmp_path, limit=3)

    assert [event["text"] for event in saved.events] == ["line 7", "line 8", "line 9"]
    assert saved.total == 11 and saved.truncated


def test_reader_reads_only_the_tail_of_a_large_file(tmp_path: Path):
    _write_session(tmp_path, [f"entry {n:04d} " + "x" * 80 for n in range(200)])

    saved = read_console_log(tmp_path, limit=None, tail_bytes=2_000)

    assert saved.truncated
    assert 0 < saved.total < 200
    assert saved.events[-1]["text"].startswith("entry 0199")
    for event in saved.events:
        assert event["text"].startswith("entry ")  # no half line at the cut


def test_missing_or_unwritable_transcript_is_harmless(tmp_path: Path):
    assert not read_console_log(tmp_path).exists
    assert not has_console_log(tmp_path)

    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    transcript = ConsoleTranscript(blocker / "sub" / "console.jsonl")
    transcript.open("header", timestamp=0.0)  # parent is a file: logged, not raised
    transcript.write(seq=1, kind="info", text="dropped", timestamp=0.0)
    transcript.close()


def test_records_keep_unicode_readable(tmp_path: Path):
    _write_session(tmp_path, ["→ lookup ✓ phân tích"])

    raw = console_log_path(tmp_path).read_text(encoding="utf-8")

    assert "→ lookup ✓ phân tích" in raw
    assert json.loads(raw.splitlines()[1])["kind"] == "info"
