"""Headless startup and tab-switch regressions for the shared Rust UI host."""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QProcess, Signal
from PySide6.QtWidgets import QApplication, QWidget

from cdmw.ui.new_item.rust_ui_tab import RustNewItemStudioTab


class _Workflow(QWidget):
    status_message_requested = Signal(str, bool)

    def __init__(self):
        super().__init__()
        self.controller = SimpleNamespace(log_message=Mock())
        self.log = Mock()

    def iter_shutdown_workers(self):
        return ()

    def request_shutdown(self):
        pass


@pytest.fixture
def presentation(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(RustNewItemStudioTab, "_start_prepare", lambda self: None)
    tab = RustNewItemStudioTab(workflow=_Workflow())
    tab._rust_mode = True
    generation = 0

    def snapshot():
        nonlocal generation
        generation += 1
        return {"type": "state", "generation": generation}

    tab._bridge = SimpleNamespace(session="startup", snapshot=snapshot,
        document=SimpleNamespace(portals={}), close=lambda: None)
    process = Mock(spec=QProcess)
    process.state.return_value = QProcess.Running
    process.processId.return_value = 77
    process.bytesToWrite.return_value = 0
    tab._process = process
    monkeypatch.setattr(tab._host, "attach_child_window", Mock(return_value=(True, "")))
    monkeypatch.setattr(tab._host, "request_first_frame", Mock())
    errors = []
    tab.status_message_requested.connect(lambda message, error: errors.append(message) if error else None)
    try:
        yield app, tab, process, errors
    finally:
        tab.request_shutdown()
        tab._process_finished()
        tab.deleteLater()
        app.sendPostedEvents(None, QEvent.DeferredDelete)


def _message(tab, kind, **fields):
    tab._handle_message({"session": "startup", "type": kind, **fields})


@pytest.mark.parametrize("stage", ["before_ready", "before_ack", "before_frame"])
def test_switching_tabs_during_startup_reuses_the_process_and_waits_for_a_frame(presentation, stage):
    app, tab, process, errors = presentation
    tab.show()
    tab._startup_deadline.start(30000)
    if stage != "before_ready":
        _message(tab, "ready", child_hwnd=123, embedded_parent_hwnd=456)
    if stage == "before_frame":
        _message(tab, "state_received", generation=tab._sent_generation)

    tab.hide()
    app.processEvents()
    assert not tab._startup_deadline.isActive()
    if stage == "before_ready":
        _message(tab, "ready", child_hwnd=123, embedded_parent_hwnd=456)
    elif stage == "before_ack":
        _message(tab, "state_received", generation=tab._sent_generation)
    assert not tab._startup_deadline.isActive()
    assert not tab._timer.isActive()

    tab.show()
    assert tab._startup_deadline.isActive()
    assert tab._process is process
    assert tab._ready and not tab._stopping and not tab._first_frame_ready
    assert tab._host._pages.isVisible()
    _message(tab, "state_received", generation=tab._sent_generation)
    _message(tab, "layout", generation=tab._sent_generation, pixels_per_point=1, portals=[])
    assert tab._first_frame_ready and not tab._startup_deadline.isActive()
    assert not tab._host._pages.isVisible()
    assert errors == []


def test_preparation_finishing_on_a_hidden_tab_arms_the_deadline_only_on_show(presentation, monkeypatch, tmp_path):
    _app, tab, process, errors = presentation
    class ProcessFactory:
        SeparateChannels, Running, NotRunning = QProcess.SeparateChannels, QProcess.Running, QProcess.NotRunning

        def __new__(cls, _parent):
            return process

    monkeypatch.setattr("cdmw.ui.new_item.rust_ui_tab.QProcess", ProcessFactory)
    monkeypatch.setattr(tab._host, "prepare_launch", lambda: 456)
    tab._process = None
    launch = SimpleNamespace(executable="fixture.exe", manifest=tmp_path / "session.json", cleanup=Mock())
    tab._launch_ready(launch)
    assert not tab._startup_deadline.isActive()
    tab.show()
    assert not tab._ready
    assert tab._startup_deadline.isActive()
    assert tab._process is process and errors == []


def test_hidden_time_does_not_count_towards_the_state_ack_deadline(presentation):
    _app, tab, _process, errors = presentation
    tab._ready = True
    tab._sent_generation = 1
    delivery = Mock()
    delivery.isValid.return_value = True
    delivery.elapsed.return_value = 30000
    delivery.start.side_effect = lambda: setattr(delivery.elapsed, "return_value", 0)
    tab._state_delivery = delivery
    tab._publish_state()
    assert errors == [] and not tab._stopping
    tab.show()
    delivery.start.assert_called_once()
    assert tab._startup_deadline.isActive()
    _message(tab, "state_received", generation=1)
    _message(tab, "layout", generation=1, pixels_per_point=1, portals=[])
    assert tab._first_frame_ready and errors == []


def test_visible_state_ack_timeout_still_stops_an_unresponsive_process(presentation):
    _app, tab, _process, errors = presentation
    tab.show()
    tab._ready = True
    tab._sent_generation = 1
    tab._state_delivery = Mock()
    tab._state_delivery.isValid.return_value = True
    tab._state_delivery.elapsed.return_value = 10001
    tab._publish_state()
    assert tab._stopping and len(errors) == 1
    assert "stopped acknowledging updates" in errors[0]


def test_explicit_hidden_prewarm_still_sends_state_and_idles_after_acknowledgement(presentation):
    _app, tab, process, errors = presentation
    tab._prewarming = True
    tab._startup_deadline.start(30000)
    _message(tab, "ready", child_hwnd=123, embedded_parent_hwnd=456)
    assert process.write.call_count == 1
    assert tab._startup_deadline.isActive()
    _message(tab, "state_received", generation=tab._sent_generation)
    assert not tab._startup_deadline.isActive() and not tab._timer.isActive()
    assert not tab._prewarming and not tab._first_frame_ready
    tab.show()
    assert tab._startup_deadline.isActive() and tab._process is process
    _message(tab, "state_received", generation=tab._sent_generation)
    _message(tab, "layout", generation=tab._sent_generation, pixels_per_point=1, portals=[])
    assert tab._first_frame_ready and errors == []
