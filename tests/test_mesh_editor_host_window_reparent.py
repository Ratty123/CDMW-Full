"""A recreated host window must take the running helper with it.

The helper is a Win32 child of the Qt host widget's native window, and it is
told that window's HWND once, on its command line. Qt destroys and recreates
that native window when the application moves to a screen at a different scale,
so the helper was left parented to a window that is no longer the one on screen:
the builder panel stayed where it was, or disappeared, after a drag to a second
monitor. ``WinIdChange`` is the only notice Qt gives, and nothing was listening.

Relaunching instead would drop the resident scene and the edit session with it,
so the helper is moved rather than restarted.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from cdmw.ui.preview.dotnet_host import DotNetPreviewHostFrame
from cdmw.ui.preview.profile import DotNetPreviewProfile

_APP = QApplication.instance() or QApplication([])


class _InertSignal:
    def connect(self, _callback: object) -> None:
        pass


class _RecordingController:
    """Stands in for the session controller's re-embed surface."""

    def __init__(self) -> None:
        self.reembedded: list[int] = []
        self.ui_localizer: object | None = None
        # Every signal the host frame connects at construction.
        self.state_changed = _InertSignal()
        self.protocol_event = _InertSignal()
        self.view_state_changed = _InertSignal()
        self.part_pick_result = _InertSignal()
        self.capture_completed = _InertSignal()

    def set_ui_localizer(self, localizer: object) -> None:
        self.ui_localizer = localizer

    def set_visible(self, visible: bool) -> None:
        del visible

    def retry_now(self) -> None:
        pass

    def shutdown(self) -> None:
        pass

    def reembed(self, parent_hwnd: int) -> bool:
        self.reembedded.append(int(parent_hwnd))
        return True


def _host_frame() -> tuple[DotNetPreviewHostFrame, _RecordingController]:
    controller = _RecordingController()
    frame = DotNetPreviewHostFrame(
        profile=DotNetPreviewProfile.PREVIEW,
        controller=controller,
    )
    return frame, controller


def test_a_recreated_host_window_reembeds_the_helper() -> None:
    frame, controller = _host_frame()
    try:
        frame.event(QEvent(QEvent.Type.WinIdChange))

        assert controller.reembedded, (
            "the host widget's native window was recreated and the helper was "
            "never told; it stays a child of the destroyed window"
        )
        assert controller.reembedded[-1] > 0
    finally:
        frame.deleteLater()


def test_the_reembed_carries_the_current_window() -> None:
    frame, controller = _host_frame()
    try:
        frame.event(QEvent(QEvent.Type.WinIdChange))
        assert controller.reembedded[-1] == frame._host_hwnd(), (
            "the helper was pointed at a window other than the one the host is "
            "using now"
        )
    finally:
        frame.deleteLater()


def test_an_unrelated_event_does_not_reembed() -> None:
    frame, controller = _host_frame()
    try:
        frame.event(QEvent(QEvent.Type.WindowActivate))
        assert controller.reembedded == [], (
            "a re-parent was issued for an event that did not change the window"
        )
    finally:
        frame.deleteLater()


def test_the_controller_refuses_to_reembed_without_a_running_helper() -> None:
    """There is nothing to move, and the launch path reads the HWND itself."""

    from cdmw.ui.preview.dotnet_session import DotNetPreviewSessionController

    controller = DotNetPreviewSessionController(
        host_hwnd=lambda: 4242,
        profile=DotNetPreviewProfile.PREVIEW,
    )
    try:
        assert controller.reembed(4242) is False
        assert controller.reembed(0) is False
    finally:
        controller.shutdown()
