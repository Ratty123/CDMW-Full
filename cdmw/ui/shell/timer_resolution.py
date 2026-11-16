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

The tick only shortens how a wait is rounded; the wait itself is the switch
interval. ``request_short_gil_switch_interval`` lowers it from 5 ms to 1 ms,
the shortest a Windows wait can be without the waiting thread spinning (CPython
waits whole milliseconds there and turns a shorter interval into a 0 ms busy
wait). Measured headless with a 1 ms tick, twelve application filters and one
busy Python worker, a burst of 78 events took about 600 ms at 5 ms and about
66 ms at 1 ms (two workers: about 1.1 s and 0.2 s); with no busy worker both
took about 1 ms.
"""

from __future__ import annotations

import ctypes
import sys

_TIMER_PERIOD_MS = 1
_LOAD_LIBRARY_SEARCH_SYSTEM32 = 0x00000800
#: Seconds a thread that wants the GIL waits before asking the holder to drop it.
GIL_SWITCH_INTERVAL_S = 0.001
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


def request_short_gil_switch_interval(*, interval_s: float = GIL_SWITCH_INTERVAL_S) -> float:
    """Let a thread that needs the GIL ask for it after ``interval_s``; return the interval in use.

    The GUI thread is such a thread for every Python event filter and slot Qt
    calls while a worker runs Python, so this bounds each of those waits. An
    interval already shorter (set by a test or an embedding host) is kept.
    """
    current = sys.getswitchinterval()
    if current > interval_s:
        sys.setswitchinterval(interval_s)
    return sys.getswitchinterval()


__all__ = ["GIL_SWITCH_INTERVAL_S", "request_fine_timer_resolution", "request_short_gil_switch_interval"]
