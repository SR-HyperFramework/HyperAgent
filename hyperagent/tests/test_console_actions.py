"""Tests for hyperagent.console_actions (collapsing tool bursts in the trace)."""

from __future__ import annotations

from hyperagent.console_actions import (
    ActionGroup,
    describe,
    group_events,
    parse_call,
)


def _event(seq: int, kind: str, text: str, tool: str = "") -> dict:
    return {"seq": seq, "kind": kind, "text": text, "clock": "10:00:00", "tool": tool}


def test_burst_between_assistant_lines_becomes_one_group():
    events = [
        _event(1, "assistant", "Looking at the artifacts."),
        _event(2, "tool", 'read_file({"path":"C:\\\\r\\\\STATE.json"})'),
        _event(3, "tool", 'list_directory({"path":"C:/r/_state"})'),
        _event(4, "muted", "Calling tool: read_file"),
        _event(5, "result", "{...}", "read_file"),
        _event(6, "muted", "Calling tool: list_directory"),
        _event(7, "result_error", "Error: denied", "list_directory"),
        _event(8, "warn", "Tool list_directory returned an error"),
        _event(9, "assistant", "Next."),
    ]

    items = group_events(events)

    assert [type(item).__name__ for item in items] == ["dict", "ActionGroup", "dict", "dict"]
    group = items[1]
    assert isinstance(group, ActionGroup)
    assert group.summary == "Read 1 file, listed 1 directory"
    assert group.failed == 1 and group.pending is None
    assert [action.label for action in group.actions] == ["Read STATE.json", "Listed _state"]
    assert [action.status for action in group.actions] == ["ok", "error"]
    # The "Calling tool" lines are folded in; the trailing warning stays visible.
    assert [event["seq"] for event in group.events] == [2, 3, 4, 5, 6, 7]
    assert items[2]["kind"] == "warn"


def test_results_pair_by_tool_name_and_fall_back_to_call_order():
    events = [
        _event(1, "tool", 'decompile({"addr":"0x401000"})'),
        _event(2, "tool", 'vm_run_program({"program":"cmd.exe"})'),
        _event(3, "result", "exit 0", "vm_run_program"),
        _event(4, "result", "void f()"),  # no name recorded: oldest open call
    ]

    (group,) = group_events(events)

    assert group.summary == "Ran 1 command, called 1 tool"
    assert [(action.label, action.result) for action in group.actions] == [
        ("Decompiled 0x401000", "void f()"),
        ("Ran cmd.exe in the guest", "exit 0"),
    ]


def test_pending_call_and_orphan_result():
    (group,) = group_events([_event(1, "tool", 'search_text({"text":"http"})')])
    assert group.pending is not None and group.pending.label == "Searched 'http'"
    assert group.summary == "Searched 1 time"

    (orphan,) = group_events([_event(5, "result", "ok", "write_file")])
    assert orphan.summary == "Wrote 1 file" and orphan.actions[0].status == "ok"


def test_parse_call_survives_a_truncated_argument_preview():
    name, args = parse_call(
        'write_file({"path":"out/09-summary.json","content":"{\\"a\\": … (collapsed'
    )

    assert name == "write_file"
    assert args["path"] == "out/09-summary.json"
    assert describe(name, args) == ("write", "Wrote 09-summary.json")
    assert describe("some_mcp_tool", {}) == ("call", "some_mcp_tool")
