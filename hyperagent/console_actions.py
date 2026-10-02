"""Collapse runs of tool calls in the console trace into one summary line.

An agent turn is often a burst of tool calls -- read three files, run a
command, query IDA a dozen times -- whose raw ``name({json})`` lines and
result previews bury the assistant's reasoning. Both trace views (the
full-screen console and the dashboard's live page) group each burst into an
:class:`ActionGroup` that reads "Read 3 files, ran 1 command, called 4 tools",
and expand it on demand.

Grouping works on console events as recorded (objects with attributes, or the
dicts the dashboard reads back from ``console.jsonl``), so nothing about how
events are stored changes. Stdlib only: ``webui`` imports this module too.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

#: Event kinds that belong to a tool burst.
ACTION_KINDS = frozenset({"tool", "result", "result_error"})
#: Log lines absorbed into a burst when more actions follow them ("Calling
#: tool: X" and per-tool warnings); trailing ones stay visible on their own.
ABSORBED_KINDS = frozenset({"muted", "warn"})

READ, LIST, WRITE, RUN, SEARCH, CALL = "read", "list", "write", "run", "search", "call"
# Summary order and wording: (category, verb, singular noun, plural noun).
_PHRASES = (
    (READ, "read", "file", "files"),
    (LIST, "listed", "directory", "directories"),
    (WRITE, "wrote", "file", "files"),
    (RUN, "ran", "command", "commands"),
    (SEARCH, "searched", "time", "times"),
    (CALL, "called", "tool", "tools"),
)

STATUS_PENDING, STATUS_OK, STATUS_ERROR = "pending", "ok", "error"


@dataclass
class Action:
    """One tool call and, once it returned, its result."""

    name: str
    category: str
    label: str
    clock: str = ""
    status: str = STATUS_PENDING
    result: str = ""
    #: The call as the console recorded it, ``name(args)``.
    call: str = ""


@dataclass
class ActionGroup:
    """A burst of consecutive tool activity in the trace."""

    seq: int
    clock: str
    actions: list[Action] = field(default_factory=list)
    #: Every event folded into the group, in order -- what "expand" shows.
    events: list[Any] = field(default_factory=list)

    @property
    def failed(self) -> int:
        return sum(1 for action in self.actions if action.status == STATUS_ERROR)

    @property
    def pending(self) -> Action | None:
        """The newest call still waiting for its result."""
        for action in reversed(self.actions):
            if action.status == STATUS_PENDING:
                return action
        return None

    @property
    def summary(self) -> str:
        counts: dict[str, int] = {}
        for action in self.actions:
            counts[action.category] = counts.get(action.category, 0) + 1
        parts = []
        for category, verb, one, many in _PHRASES:
            count = counts.get(category)
            if count:
                parts.append(f"{verb} {count} {one if count == 1 else many}")
        if not parts:
            return "Tool activity"
        text = ", ".join(parts)
        return text[0].upper() + text[1:]


def _get(event: Any, key: str, default: Any = "") -> Any:
    if isinstance(event, dict):
        return event.get(key, default)
    return getattr(event, key, default)


_STRING_FIELD = re.compile(r'"(\w+)"\s*:\s*"((?:[^"\\]|\\.)*)"')
_NUMBER_FIELD = re.compile(r'"(\w+)"\s*:\s*(-?\d+)')


def parse_call(text: str) -> tuple[str, dict[str, str]]:
    """``name`` and string/number arguments from a ``name(args)`` trace line.

    The argument preview may have been truncated mid-JSON, so fields are
    pulled out with a pattern rather than a full parse.
    """
    name, _, rest = text.partition("(")
    args: dict[str, str] = {}
    for key, raw in _STRING_FIELD.findall(rest):
        try:
            args.setdefault(key, json.loads(f'"{raw}"'))
        except ValueError:
            args.setdefault(key, raw)
    for key, raw in _NUMBER_FIELD.findall(rest):
        args.setdefault(key, raw)
    return name.strip(), args


def _basename(path: str) -> str:
    cleaned = path.rstrip("/\\")
    return re.split(r"[\\/]", cleaned)[-1] or cleaned


def _first(args: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = args.get(key)
        if value:
            return str(value)
    return ""


def _path_label(verb: str, args: dict[str, str], fallback: str) -> str:
    path = _first(args, "path", "file_path", "filename", "host_path", "input_path", "output_path")
    return f"{verb} {_basename(path)}" if path else fallback


def _address(args: dict[str, str]) -> str:
    return _first(args, "addr", "address", "ea", "name", "func", "function", "query", "target")


def describe(name: str, args: dict[str, str]) -> tuple[str, str]:
    """``(category, label)`` for one call, e.g. ``("read", "Read STATE.json")``."""
    if name == "read_file":
        return READ, _path_label("Read", args, "Read a file")
    if name == "file_exists":
        return READ, _path_label("Checked", args, "Checked a path")
    if name == "list_directory":
        path = _first(args, "path", "directory")
        return LIST, f"Listed {_basename(path)}" if path else "Listed a directory"
    if name == "write_file":
        return WRITE, _path_label("Wrote", args, "Wrote a file")
    if name == "mkdir":
        path = _first(args, "path")
        return WRITE, f"Created {_basename(path)}/" if path else "Created a directory"
    if name == "vm_run_program":
        program = _first(args, "program", "program_path", "path", "command")
        return RUN, f"Ran {_basename(program)} in the guest" if program else "Ran a guest program"
    if name == "vm_run_debugger_with_sample":
        sample = _first(args, "sample_filename")
        return (
            RUN,
            f"Ran {sample} under the debugger" if sample else "Ran the sample under the debugger",
        )
    if name == "upx_unpack":
        return RUN, _path_label("Unpacked", args, "Ran UPX unpack")
    if name in ("decompile", "disasm"):
        target = _address(args)
        verb = "Decompiled" if name == "decompile" else "Disassembled"
        return CALL, f"{verb} {target}" if target else verb
    if name in ("find", "find_bytes", "find_regex", "search_text", "search_structs"):
        pattern = _first(args, "pattern", "query", "text", "regex", "bytes")
        return SEARCH, f"Searched {pattern!r}" if pattern else "Searched the binary"
    if name.startswith("xrefs"):
        target = _address(args)
        return CALL, f"Xrefs to {target}" if target else "Looked up xrefs"
    if name == "sha256_file":
        return CALL, _path_label("Hashed", args, "Hashed a file")
    if name == "validate_json_output":
        return CALL, _path_label("Validated", args, "Validated JSON output")
    if name == "idalib_open":
        return CALL, _path_label("Opened", args, "Opened IDA database") + " in IDA"
    if name == "vm_revert_snapshot":
        snapshot = _first(args, "snapshot", "snapshot_name")
        return CALL, f"Reverted VM to {snapshot}" if snapshot else "Reverted the VM"
    if name == "vm_copy_to_guest":
        return CALL, _path_label("Copied", args, "Copied a file") + " to the guest"
    target = _address(args) if not args.get("path") else _basename(args["path"])
    return CALL, f"{name} {target}" if target else name


def group_events(events: Iterable[Any]) -> list[Any]:
    """The trace as plain events and :class:`ActionGroup` items, in order."""
    items: list[Any] = []
    group: ActionGroup | None = None
    held: list[Any] = []  # log lines that may still turn out to be mid-burst

    def close() -> None:
        nonlocal group
        group = None
        items.extend(held)
        held.clear()

    for event in events:
        kind = _get(event, "kind")
        if kind in ACTION_KINDS:
            if group is None:
                group = ActionGroup(seq=_get(event, "seq", 0), clock=_get(event, "clock"))
                items.append(group)
            group.events.extend(held)
            held.clear()
            group.events.append(event)
            _fold(group, event)
        elif group is not None and kind in ABSORBED_KINDS:
            held.append(event)
        else:
            if group is not None:
                close()
            items.append(event)
    if group is not None:
        close()
    return items


def _fold(group: ActionGroup, event: Any) -> None:
    kind = _get(event, "kind")
    text = str(_get(event, "text"))
    clock = str(_get(event, "clock"))
    if kind == "tool":
        name, args = parse_call(text)
        category, label = describe(name, args)
        group.actions.append(
            Action(name=name, category=category, label=label, clock=clock, call=text)
        )
        return
    status = STATUS_ERROR if kind == "result_error" else STATUS_OK
    tool = str(_get(event, "tool") or "")
    waiting = [action for action in group.actions if action.status == STATUS_PENDING]
    match = next((action for action in waiting if tool and action.name == tool), None)
    if match is None and waiting:
        match = waiting[0]  # results arrive in call order
    if match is None:  # a result whose call was not shown (or aged out)
        category, label = describe(tool, {}) if tool else (CALL, "Tool result")
        match = Action(name=tool or "tool", category=category, label=label, clock=clock)
        group.actions.append(match)
    match.status = status
    match.result = text.strip()
