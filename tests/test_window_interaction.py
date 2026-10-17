from __future__ import annotations

import ctypes
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QByteArray, QCoreApplication, QEvent, Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import VoidPtr, delete, isValid

from cdmw.ui import window_interaction as interaction


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tracker(app):
    return interaction.ensure_window_interaction_tracker(app)


@pytest.fixture
def windows(app):
    first, second = QWidget(), QWidget()
    yield first, second
    for window in (first, second):
        if isValid(window):
            delete(window)
    _settle(app)


def _settle(app):
    for _ in range(4):
        app.processEvents()


def test_singleton_does_not_force_hidden_window_handle(app, tracker, windows):
    window, _ = windows
    assert interaction.ensure_window_interaction_tracker() is tracker
    assert not window.testAttribute(Qt.WidgetAttribute.WA_WState_Created)
    tracker.begin(window)
    assert tracker.is_active(window)
    tracker.end(window)
    _settle(app)
    assert not tracker.is_active(window)
    assert not window.testAttribute(Qt.WidgetAttribute.WA_WState_Created)


def test_holds_are_window_scoped_and_finish_is_queued(app, tracker, windows):
    first, second = windows
    child = QWidget(first)
    started = QSignalSpy(tracker.started)
    finished = QSignalSpy(tracker.finished)
    tracker.begin(child)
    tracker.begin(first)
    assert started.count() == 1
    assert started.at(0)[0] is first
    assert tracker.is_active(child)
    assert not tracker.is_active(second)
    tracker.begin(second)
    tracker.end(first)
    tracker.end(first)
    assert tracker.is_active(first)
    assert tracker.is_active(second)
    assert finished.count() == 0
    _settle(app)
    assert not tracker.is_active(first)
    assert tracker.is_active(second)
    assert finished.count() == 1
    assert finished.at(0)[0] is first


def test_new_begin_supersedes_queued_finish(app, tracker, windows):
    window, _ = windows
    finished = QSignalSpy(tracker.finished)
    tracker.begin(window)
    tracker.end(window)
    tracker.begin(window)
    _settle(app)
    assert tracker.is_active(window)
    assert finished.count() == 0
    tracker.end(window)
    _settle(app)
    assert not tracker.is_active(window)
    assert finished.count() == 1


@pytest.mark.parametrize("event_type", [b"windows_generic_MSG", b"windows_dispatcher_MSG"])
@pytest.mark.parametrize("wrap_pointer", [int, VoidPtr])
def test_native_msg_pointer_decode_never_consumes_message(monkeypatch, tracker, event_type, wrap_pointer):
    calls = []
    monkeypatch.setattr(tracker, "_native_message", lambda hwnd, kind: calls.append((hwnd, kind)))
    native = interaction._MSG(hwnd=0x1234, message=interaction._WM_ENTERSIZEMOVE)
    pointer = wrap_pointer(ctypes.addressof(native))
    result = tracker._native_filter.nativeEventFilter(QByteArray(event_type), pointer)
    assert result == (False, 0)
    assert calls == [(0x1234, interaction._WM_ENTERSIZEMOVE)]
    native.message = 0x02E0  # WM_DPICHANGED must keep its normal Qt/native path.
    assert tracker._native_filter.nativeEventFilter(QByteArray(event_type), pointer) == (False, 0)
    assert len(calls) == 1
    assert tracker._native_filter.nativeEventFilter(QByteArray(b"xcb_generic_event_t"), pointer) == (False, 0)
    assert tracker._native_filter.nativeEventFilter(QByteArray(event_type), 0) == (False, 0)
    assert len(calls) == 1


@pytest.mark.parametrize("end_message", [interaction._WM_EXITSIZEMOVE, interaction._WM_CANCELMODE])
def test_native_handle_resolves_owning_window_and_cancel_releases_hold(app, tracker, windows, end_message):
    window, other = windows
    # The test deliberately creates a handle; the tracker must only look it up.
    hwnd = int(window.winId())
    tracker._native_message(hwnd, interaction._WM_ENTERSIZEMOVE)
    assert tracker.is_active(window)
    assert not tracker.is_active(other)
    tracker._native_message(hwnd, end_message)
    assert tracker.is_active(window)
    _settle(app)
    assert not tracker.is_active(window)


@pytest.mark.parametrize("event_type", [QEvent.Type.Hide, QEvent.Type.WinIdChange])
def test_hide_or_handle_replacement_ends_hold_without_consuming_event(app, tracker, windows, event_type):
    window, _ = windows
    tracker.begin(window)
    event = QEvent(event_type)
    assert tracker.eventFilter(window, event) is False
    assert tracker.is_active(window)
    _settle(app)
    assert not tracker.is_active(window)


def test_unrelated_native_message_cannot_end_hold(app, tracker, windows):
    window, _ = windows
    hwnd = int(window.winId())
    tracker.begin(window)
    tracker._native_message(hwnd, 0x02E0)
    _settle(app)
    assert tracker.is_active(window)


def test_close_event_alone_does_not_end_a_hold(app, tracker, windows):
    window, _ = windows
    tracker.begin(window)
    close = QEvent(QEvent.Type.Close)
    assert tracker.eventFilter(window, close) is False
    _settle(app)
    assert tracker.is_active(window)


def test_destroyed_window_cannot_emit_stale_finish(app, tracker, windows):
    window, _ = windows
    finished = QSignalSpy(tracker.finished)
    tracker.begin(window)
    tracker.end(window)
    key = id(window)
    delete(window)
    assert not isValid(window)
    assert not tracker.is_active(window)
    assert key not in tracker._windows
    _settle(app)
    assert finished.count() == 0


def test_deferred_destroy_during_hold_clears_state(app, tracker, windows):
    window, _ = windows
    tracker.begin(window)
    key = id(window)
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not tracker.is_active(window)
    assert key not in tracker._windows


def test_quit_signal_does_not_poison_reused_application(app, tracker, windows):
    window, _ = windows
    app.aboutToQuit.emit()
    assert interaction.ensure_window_interaction_tracker(app) is tracker
    tracker.begin(window)
    assert tracker.is_active(window)
    tracker.end(window)
    _settle(app)
    assert not tracker.is_active(window)
