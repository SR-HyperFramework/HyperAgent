"""Keyboard and mouse-wheel input for the full-screen console.

The full-screen view lives on the terminal's alternate screen, which has no
scrollback of its own, so the trace pane scrolls itself. This module turns
raw terminal input into a handful of scroll actions on a background thread:

* Windows: native console input records (virtual-key codes and
  ``MOUSE_WHEELED`` events) read with ``ReadConsoleInputW``.
* POSIX: cbreak mode plus xterm SGR mouse reporting, parsed from the byte
  stream by :func:`parse_vt_input`.

Ctrl-C keeps working in both: the console still turns it into SIGINT, so the
reader never sees it. Nothing else in HyperAgent reads stdin during a run.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from typing import Callable, TextIO

logger = logging.getLogger(__name__)

UP = "up"
DOWN = "down"
PAGE_UP = "page_up"
PAGE_DOWN = "page_down"
HOME = "home"
END = "end"
WHEEL_UP = "wheel_up"
WHEEL_DOWN = "wheel_down"
#: Ctrl+O: expand or collapse tool bursts in the trace.
EXPAND = "expand"
_CTRL_O = chr(0x0F)

ActionHandler = Callable[[str], None]

# Windows virtual-key codes.
_VK_ACTIONS = {
    0x21: PAGE_UP,  # VK_PRIOR
    0x22: PAGE_DOWN,  # VK_NEXT
    0x23: END,
    0x24: HOME,
    0x26: UP,
    0x28: DOWN,
}

# CSI sequences xterm-compatible terminals send for the keys we use.
_CSI_ACTIONS = {
    "A": UP,
    "B": DOWN,
    "H": HOME,
    "F": END,
    "1~": HOME,
    "7~": HOME,
    "4~": END,
    "8~": END,
    "5~": PAGE_UP,
    "6~": PAGE_DOWN,
}
_SS3_ACTIONS = {"A": UP, "B": DOWN, "H": HOME, "F": END}

_MOUSE_ON = "\x1b[?1000h\x1b[?1006h"
_MOUSE_OFF = "\x1b[?1006l\x1b[?1000l"


def windows_key_action(virtual_key: int) -> str | None:
    return _VK_ACTIONS.get(virtual_key)


def parse_vt_input(data: str) -> tuple[list[str], str]:
    """Scroll actions in *data*, plus any trailing incomplete escape sequence.

    Unknown keys and sequences are dropped. The leftover is fed back in front
    of the next read, since a sequence can be split across reads.
    """
    actions: list[str] = []
    index = 0
    length = len(data)
    while index < length:
        if data[index] == _CTRL_O:
            actions.append(EXPAND)
        if data[index] != "\x1b":
            index += 1
            continue
        if index + 1 >= length:
            return actions, data[index:]
        lead = data[index + 1]
        if lead == "O":
            if index + 2 >= length:
                return actions, data[index:]
            action = _SS3_ACTIONS.get(data[index + 2])
            if action:
                actions.append(action)
            index += 3
            continue
        if lead != "[":
            index += 1
            continue
        # CSI: parameter bytes 0x30-0x3F, then one final byte 0x40-0x7E.
        end = index + 2
        while end < length and "\x30" <= data[end] <= "\x3f":
            end += 1
        if end >= length:
            return actions, data[index:]
        body = data[index + 2 : end + 1]
        if body.startswith("<") and body[-1] in "Mm":
            # SGR mouse report: ESC [ < button ; x ; y M
            button = body[1:-1].split(";", 1)[0]
            if body[-1] == "M" and button.isdigit():
                code = int(button) & ~0b11100  # drop shift/meta/ctrl bits
                if code == 64:
                    actions.append(WHEEL_UP)
                elif code == 65:
                    actions.append(WHEEL_DOWN)
        else:
            action = _CSI_ACTIONS.get(body)
            if action:
                actions.append(action)
        index = end + 1
    return actions, ""


class InputReader:
    """Background reader that reports scroll actions to *on_action*.

    ``start`` returns False (and does nothing) when stdin is not an
    interactive terminal, so callers can simply skip the scroll hint.
    """

    POLL_SECONDS = 0.1

    def __init__(self, on_action: ActionHandler, *, output: TextIO | None = None) -> None:
        self._on_action = on_action
        self._output = output
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._restore: Callable[[], None] | None = None

    @property
    def active(self) -> bool:
        return self._thread is not None

    def start(self) -> bool:
        if self._thread is not None:
            return True
        try:
            setup = self._setup_windows if sys.platform == "win32" else self._setup_posix
            loop = setup()
        except Exception:
            logger.debug("Console input unavailable; trace scrolling disabled", exc_info=True)
            loop = None
        if loop is None:
            return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, args=(loop,), name="hyperagent-console-input", daemon=True
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        thread, self._thread = self._thread, None
        self._stop.set()
        if thread is not None:
            thread.join(timeout=1.0)
        restore, self._restore = self._restore, None
        if restore is not None:
            try:
                restore()
            except Exception:
                logger.debug("Could not restore the console input mode", exc_info=True)

    def _run(self, loop: Callable[[], None]) -> None:
        try:
            loop()
        except Exception:
            logger.debug("Console input reader stopped", exc_info=True)

    def _emit(self, action: str) -> None:
        try:
            self._on_action(action)
        except Exception:
            logger.debug("Scroll action handler failed", exc_info=True)

    # --- Windows --------------------------------------------------------------

    def _setup_windows(self) -> Callable[[], None] | None:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # Without explicit prototypes ctypes passes handles as 32-bit ints.
        kernel32.GetStdHandle.restype = wintypes.HANDLE
        kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
        kernel32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.ReadConsoleInputW.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]

        handle = kernel32.GetStdHandle(wintypes.DWORD(-10).value)  # STD_INPUT_HANDLE
        old_mode = wintypes.DWORD()
        if not handle or not kernel32.GetConsoleMode(handle, ctypes.byref(old_mode)):
            return None  # stdin is a pipe or file, not a console

        processed, line, echo, mouse = 0x1, 0x2, 0x4, 0x10
        quick_edit, extended, vt_input = 0x40, 0x80, 0x200
        # Native records rather than VT input, so keys arrive as virtual-key
        # codes; quick-edit off so the wheel reaches us instead of selecting.
        mode = (old_mode.value & ~(line | echo | quick_edit | vt_input)) | processed | mouse
        if not kernel32.SetConsoleMode(handle, mode | extended):
            return None
        self._restore = lambda: kernel32.SetConsoleMode(handle, old_mode.value | extended)

        class COORD(ctypes.Structure):
            _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]

        class KEY_EVENT_RECORD(ctypes.Structure):
            _fields_ = [
                ("bKeyDown", wintypes.BOOL),
                ("wRepeatCount", wintypes.WORD),
                ("wVirtualKeyCode", wintypes.WORD),
                ("wVirtualScanCode", wintypes.WORD),
                ("uChar", wintypes.WCHAR),
                ("dwControlKeyState", wintypes.DWORD),
            ]

        class MOUSE_EVENT_RECORD(ctypes.Structure):
            _fields_ = [
                ("dwMousePosition", COORD),
                ("dwButtonState", wintypes.DWORD),
                ("dwControlKeyState", wintypes.DWORD),
                ("dwEventFlags", wintypes.DWORD),
            ]

        class EVENT(ctypes.Union):
            _fields_ = [
                ("KeyEvent", KEY_EVENT_RECORD),
                ("MouseEvent", MOUSE_EVENT_RECORD),
                ("_pad", ctypes.c_byte * 16),
            ]

        class INPUT_RECORD(ctypes.Structure):
            _fields_ = [("EventType", wintypes.WORD), ("Event", EVENT)]

        key_event, mouse_event, mouse_wheeled = 0x1, 0x2, 0x4
        records = (INPUT_RECORD * 32)()
        count = wintypes.DWORD()
        wait_ms = int(self.POLL_SECONDS * 1000)

        def loop() -> None:
            while not self._stop.is_set():
                if kernel32.WaitForSingleObject(handle, wait_ms) != 0:  # WAIT_OBJECT_0
                    continue
                if not kernel32.ReadConsoleInputW(
                    handle, ctypes.byref(records), len(records), ctypes.byref(count)
                ):
                    return
                for record in records[: count.value]:
                    if record.EventType == key_event:
                        key = record.Event.KeyEvent
                        action = windows_key_action(key.wVirtualKeyCode) if key.bKeyDown else None
                        if key.bKeyDown and key.uChar == _CTRL_O:
                            action = EXPAND
                        for _ in range(max(1, key.wRepeatCount) if action else 0):
                            self._emit(action)  # type: ignore[arg-type]
                    elif record.EventType == mouse_event:
                        mouse_record = record.Event.MouseEvent
                        if mouse_record.dwEventFlags == mouse_wheeled:
                            delta = ctypes.c_short(mouse_record.dwButtonState >> 16).value
                            self._emit(WHEEL_UP if delta > 0 else WHEEL_DOWN)

        return loop

    # --- POSIX ----------------------------------------------------------------

    def _setup_posix(self) -> Callable[[], None] | None:
        import select
        import termios
        import tty

        stdin = sys.stdin
        if stdin is None or not stdin.isatty():
            return None
        fd = stdin.fileno()
        saved = termios.tcgetattr(fd)
        tty.setcbreak(fd)  # keeps ISIG, so Ctrl-C still raises KeyboardInterrupt
        # Without IEXTEN, BSD/macOS terminals no longer swallow Ctrl+O as VDISCARD.
        attrs = termios.tcgetattr(fd)
        attrs[3] &= ~termios.IEXTEN
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        output = self._output
        if output is not None:
            output.write(_MOUSE_ON)
            output.flush()

        def restore() -> None:
            if output is not None:
                output.write(_MOUSE_OFF)
                output.flush()
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)

        self._restore = restore

        def loop() -> None:
            pending = ""
            while not self._stop.is_set():
                ready, _, _ = select.select([fd], [], [], self.POLL_SECONDS)
                if not ready:
                    if pending == "\x1b":
                        pending = ""  # a lone Escape keypress
                    continue
                chunk = os.read(fd, 1024)
                if not chunk:
                    return
                actions, pending = parse_vt_input(pending + chunk.decode("utf-8", "ignore"))
                for action in actions:
                    self._emit(action)

        return loop
