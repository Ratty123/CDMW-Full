"""A preview's window is sized without the window thread waiting for its helper.

The helper's window is a Win32 child of CDMW's viewport, which attaches the two
threads' input queues: a SetWindowPos from CDMW's window thread waits until the
helper takes the message, SWP_ASYNCWINDOWPOS or not. Selecting a large PAC in
Browse held the window thread 278 ms in ``_sync_embedded_child_geometry`` in
the 2026-11-17 cold review. The move is now sent from another thread.
"""

from __future__ import annotations

import sys
import threading
from types import SimpleNamespace

import pytest

from cdmw.ui.preview import dotnet_host_protocol as protocol

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Win32 only")


class _Host(protocol.DotNetPreviewHostProtocolMixin):
    def __init__(self) -> None:
        self._embedded_child_hwnd = 77
        self.controller = SimpleNamespace(process_id=4242)
        self.embedding_error = ""

    def _host_hwnd(self) -> int:
        return 99


class _BusyHelperUser32:
    """A helper whose window thread does not answer until ``answer`` is set."""

    def __init__(self) -> None:
        self.size = (800, 600)
        self.answer = threading.Event()
        self.moves: list[tuple[int, int, int, int]] = []
        self.first_move_started = threading.Event()

    def IsWindow(self, _hwnd) -> int:  # noqa: N802
        return 1

    def GetWindowThreadProcessId(self, _hwnd, pid) -> int:  # noqa: N802
        pid._obj.value = 4242
        return 1

    def GetParent(self, _hwnd) -> int:  # noqa: N802
        return 99

    def GetClientRect(self, _hwnd, rect) -> int:  # noqa: N802
        rect._obj.left, rect._obj.top = 0, 0
        rect._obj.right, rect._obj.bottom = self.size
        return 1

    def SetWindowPos(self, hwnd, _after, _x, _y, width, height, flags) -> int:  # noqa: N802
        self.first_move_started.set()
        self.answer.wait(10)
        self.moves.append((int(hwnd.value), int(width), int(height), int(flags)))
        return 1


def _sync_on_another_thread(host: _Host, **kwargs) -> bool:
    done = threading.Event()
    thread = threading.Thread(target=lambda: (host._sync_embedded_child_geometry(**kwargs), done.set()),
                              daemon=True)
    thread.start()
    return done.wait(2)


def test_a_busy_helper_does_not_hold_the_window_thread(monkeypatch) -> None:
    fake = _BusyHelperUser32()
    monkeypatch.setattr(protocol, "_typed_user32", lambda: fake)
    host = _Host()
    try:
        assert _sync_on_another_thread(host), "the geometry sync waited for the helper's window thread"
    finally:
        fake.answer.set()
    from cdmw.ui.preview.child_window_mover import child_window_mover

    assert child_window_mover(protocol._typed_user32).wait_idle(5)
    assert fake.moves and fake.moves[-1][:3] == (77, 800, 600)


def test_the_latest_size_wins_and_keeps_a_frame_refresh(monkeypatch) -> None:
    from cdmw.ui.preview.child_window_mover import SWP_FRAMECHANGED, child_window_mover

    fake = _BusyHelperUser32()
    monkeypatch.setattr(protocol, "_typed_user32", lambda: fake)
    host = _Host()
    try:
        host._sync_embedded_child_geometry()
        assert fake.first_move_started.wait(5)  # the mover now waits on the helper
        fake.size = (900, 700)
        host._sync_embedded_child_geometry(force_frame_refresh=True)
        fake.size = (1000, 720)
        host._sync_embedded_child_geometry()
    finally:
        fake.answer.set()
    assert child_window_mover(protocol._typed_user32).wait_idle(5)
    assert [move[:3] for move in fake.moves] == [(77, 800, 600), (77, 1000, 720)]
    assert fake.moves[-1][3] & SWP_FRAMECHANGED, "the replaced request's frame refresh was lost"


def test_a_window_closed_before_the_move_is_left_alone(monkeypatch) -> None:
    from cdmw.ui.preview.child_window_mover import ChildWindowMover

    fake = _BusyHelperUser32()
    fake.answer.set()
    fake.IsWindow = lambda _hwnd: 0  # type: ignore[method-assign]
    mover = ChildWindowMover(lambda: fake)
    mover.move(77, 4242, 800, 600, 0)
    assert mover.wait_idle(5)
    assert fake.moves == []
    fake.IsWindow = lambda _hwnd: 1  # type: ignore[method-assign]
    mover.move(77, 1111, 800, 600, 0)  # its handle now belongs to another process
    assert mover.wait_idle(5)
    assert fake.moves == []
