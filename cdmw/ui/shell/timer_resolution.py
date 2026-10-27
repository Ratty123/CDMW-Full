"""Keep the GUI thread's waits for the GIL short while workers run Python.

Qt calls into Python for every event (application event filters, slots), and
each call takes the GIL. While a worker thread is busy in Python, the GUI
thread waits up to the interpreter's 5 ms switch interval for it, but Windows
rounds that wait up to the system timer tick, 15.6 ms by default. With eleven
Python application filters, as CDMW installs, and one busy worker, an event
took about 15 ms at the default tick and about 2 ms at 1 ms; a few hundred
queued events are then the difference between a window that stalls for seconds
while Mesh Editor opens and one that keeps up.

Windows 10 2004 and later apply the request to this process only, and may not
honour it while its windows are minimised or hidden, so it does not hold the
whole system at a fine tick. The request lasts until the process exits.
"""

from __future__ import annotations

import ctypes
import sys

_TIMER_PERIOD_MS = 1
_LOAD_LIBRARY_SEARCH_SYSTEM32 = 0x00000800
_requested = False


def request_fine_timer_resolution(*, loader=None) -> bool:
    """Ask Windows for a 1 ms timer tick once per process; return whether it is held."""
    global _requested
    if _requested:
        return True
    if sys.platform != "win32":
        return False
    try:
        # System32 only: the game's bin64 ships its own winmm.dll proxy.
        winmm = (loader or ctypes.WinDLL)("winmm", winmode=_LOAD_LIBRARY_SEARCH_SYSTEM32)
        _requested = int(winmm.timeBeginPeriod(_TIMER_PERIOD_MS)) == 0
    except (AttributeError, OSError):
        return False
    return _requested


__all__ = ["request_fine_timer_resolution"]
