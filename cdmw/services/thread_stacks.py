"""Every thread's Python stack, read without holding any thread's frame.

``sys._current_frames()`` hands out each thread's live frame object. While
another thread holds such a frame, a function that returns in the meantime
cannot free its locals: they move into the held frame object and die when the
holder lets go, later and on the holder's thread. For a ``QPainter`` made in a
``paintEvent`` that is fatal. The painter outlives its paint event, the next
widget of the window starts painting on the same backing store (Qt's raster
paint engine is one per backing store), and when the old painter is finally
destroyed its ``end()`` clears the engine's state under the painter now in use:
the next call of that painter reads or writes through a null pointer. That was
the start-up splash crash of 2026-11-17 (``Qt6Gui`` in
``QRasterPaintEngine::penChanged`` with a null state, under
``startup_dialogs._draw_iso_block``), seen while a test driver asked the
automation bridge for ``ui_stack`` every 50 ms.

``faulthandler.dump_traceback`` walks the same stacks inside the interpreter
and writes them as text: no frame object is made, so nothing is kept alive.
This module asks it for the text and parses it. The price is faulthandler's
limits: the innermost 100 frames of a thread, file names cut at 500 characters
and non-ASCII characters written as escapes.
"""

from __future__ import annotations

import faulthandler
import re
import tempfile
import threading
from dataclasses import dataclass

_HEADER = re.compile(r"^(Current thread|Thread) 0x([0-9a-fA-F]+)(?: \[(.*)\])? \(most recent call first\):\s*$")
_FRAME = re.compile(r'^  File "(.*)", line (\d+|\?+) in (.*?)\s*$')

_lock = threading.Lock()
_scratch = None


@dataclass(frozen=True)
class StackFrame:
    filename: str
    lineno: int
    name: str


@dataclass(frozen=True)
class ThreadStack:
    ident: int
    name: str
    #: The thread that asked.
    current: bool
    #: Outermost call first, as ``traceback.extract_stack`` orders them.
    frames: tuple[StackFrame, ...]
    #: faulthandler stopped before the outermost call (a very deep stack).
    truncated: bool = False


def parse_faulthandler_traceback(text: str) -> list[ThreadStack]:
    """The threads in ``faulthandler.dump_traceback(all_threads=True)`` output."""

    stacks: list[ThreadStack] = []
    header: tuple[int, str, bool] | None = None
    frames: list[StackFrame] = []
    truncated = False

    def close() -> None:
        if header is not None:
            stacks.append(ThreadStack(header[0], header[1], header[2], tuple(reversed(frames)), truncated))

    for line in text.splitlines():
        match = _HEADER.match(line)
        if match is not None:
            close()
            header = (int(match.group(2), 16), match.group(3) or "", match.group(1) == "Current thread")
            frames = []
            truncated = False
            continue
        if header is None:
            continue
        match = _FRAME.match(line)
        if match is not None:
            number = match.group(2)
            frames.append(StackFrame(match.group(1), int(number) if number.isdigit() else 0, match.group(3)))
        elif line.strip() == "...":
            truncated = True
    close()
    return stacks


def python_thread_stacks() -> list[ThreadStack]:
    """Every thread's Python stack right now. Empty if faulthandler cannot write it."""

    global _scratch
    with _lock:
        try:
            if _scratch is None:
                _scratch = tempfile.TemporaryFile()
            _scratch.seek(0)
            _scratch.truncate()
            faulthandler.dump_traceback(_scratch, all_threads=True)
            _scratch.flush()
            _scratch.seek(0)
            text = _scratch.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - a stack sample must never break its caller
            try:
                if _scratch is not None:
                    _scratch.close()
            except Exception:  # noqa: BLE001
                pass
            _scratch = None
            return []
    stacks = parse_faulthandler_traceback(text)
    names = {thread.ident: thread.name for thread in threading.enumerate()}
    return [
        ThreadStack(stack.ident, names.get(stack.ident, stack.name), stack.current, stack.frames, stack.truncated)
        for stack in stacks
    ]


__all__ = ["StackFrame", "ThreadStack", "parse_faulthandler_traceback", "python_thread_stacks"]
