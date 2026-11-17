"""Move another process's embedded window without the window thread waiting.

A preview helper's window is a Win32 child of a CDMW window. Windows attaches
the input queues of a parent's thread and its child's thread, so a
SetWindowPos from CDMW's window thread runs synchronously, SWP_ASYNCWINDOWPOS
or not, and waits until the helper's thread takes the message. A helper busy
loading a large model held the window thread 278 ms there in the 2026-11-17
cold review.

This thread is not attached to the helper's queue: with SWP_ASYNCWINDOWPOS its
request is posted to the helper and the call returns. Requests are kept per
window, and a newer size replaces one not yet sent, so the latest geometry wins.
Any thread may move any window; only the call's wait depends on the caller.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

#: SetWindowPos's SWP_FRAMECHANGED: kept when a newer request replaces one that had it.
SWP_FRAMECHANGED = 0x0020

_LOGGER = logging.getLogger(__name__)


class ChildWindowMover:
    def __init__(self, user32_loader: Callable[[], object]) -> None:
        self._user32_loader = user32_loader
        self._condition = threading.Condition()
        #: hwnd -> (owner process id, width, height, flags), oldest first.
        self._pending: dict[int, tuple[int, int, int, int]] = {}
        self._busy = False
        self._thread: threading.Thread | None = None

    def move(self, hwnd: int, owner_pid: int, width: int, height: int, flags: int) -> None:
        """Ask for ``hwnd`` at (0, 0, width, height); returns without waiting."""

        hwnd = int(hwnd)
        with self._condition:
            previous = self._pending.pop(hwnd, None)
            if previous is not None:
                flags |= previous[3] & SWP_FRAMECHANGED
            self._pending[hwnd] = (int(owner_pid), int(width), int(height), int(flags))
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="cdmw-child-window-mover", daemon=True)
                self._thread.start()
            self._condition.notify()

    def wait_idle(self, timeout: float) -> bool:
        """True once every request was sent (for tests and shutdown)."""

        with self._condition:
            return self._condition.wait_for(lambda: not self._pending and not self._busy, timeout)

    def _run(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(lambda: bool(self._pending))
                hwnd = next(iter(self._pending))
                owner_pid, width, height, flags = self._pending.pop(hwnd)
                self._busy = True
            try:
                self._send(hwnd, owner_pid, width, height, flags)
            except Exception:  # noqa: BLE001 - one bad window must not stop the others
                _LOGGER.debug("embedded window move failed", exc_info=True)
            finally:
                with self._condition:
                    self._busy = False
                    self._condition.notify_all()

    def _send(self, hwnd: int, owner_pid: int, width: int, height: int, flags: int) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = self._user32_loader()
        handle = wintypes.HWND(hwnd)
        # Checked again here: the window may have closed, and its handle been
        # reused, since the request was made.
        if not user32.IsWindow(handle):
            return
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(owner))
        if int(owner.value) != int(owner_pid):
            return
        user32.SetWindowPos(handle, None, 0, 0, int(width), int(height), int(flags))


_MOVER: ChildWindowMover | None = None
_MOVER_LOCK = threading.Lock()


def child_window_mover(user32_loader: Callable[[], object]) -> ChildWindowMover:
    """The process's one mover; its thread starts with the first request."""

    global _MOVER
    with _MOVER_LOCK:
        if _MOVER is None:
            _MOVER = ChildWindowMover(user32_loader)
        return _MOVER


__all__ = ["ChildWindowMover", "SWP_FRAMECHANGED", "child_window_mover"]
