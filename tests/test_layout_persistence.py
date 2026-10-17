from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QWidget
from shiboken6 import delete, isValid

from cdmw.ui import layout_persistence as persistence
from cdmw.ui import widgets


class RecordingSettings(QSettings):
    def __init__(self, path):
        super().__init__(str(path), QSettings.IniFormat)
        self.writes = []
        self.setFallbacksEnabled(False)

    def setValue(self, key, value):
        self.writes.append((key, value))
        super().setValue(key, value)


@pytest.fixture
def rig(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(persistence, "_WINDOW_GEOMETRY_SAVE_DELAY_MS", 100, raising=False)
    monkeypatch.setattr(widgets, "_settings_sync_timer", None)
    monkeypatch.setattr(widgets, "_settings_sync_pending", [])
    path = tmp_path / "geometry.cfg"
    settings = RecordingSettings(path)
    settings.setValue("unrelated/value", "preserved")
    settings.sync()
    settings.writes.clear()
    windows = []

    def window(key="window/geometry"):
        widget = QWidget()
        widget.resize(360, 240)
        widget.move(40, 60)
        widget.show()
        app.processEvents()
        policy.watch_window(widget, key, restore=False)
        windows.append(widget)
        return widget

    policy = persistence.UiLayoutPersistence(settings)
    app.installEventFilter(policy)
    yield SimpleNamespace(app=app, path=path, settings=settings, policy=policy,
                          window=window, windows=windows)
    app.removeEventFilter(policy)
    policy.deleteLater()
    for widget in windows:
        if isValid(widget):
            widget.close()
            widget.deleteLater()
    timer = widgets._settings_sync_timer
    if timer is not None and isValid(timer):
        timer.stop()
        timer.deleteLater()
    widgets._settings_sync_pending.clear()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def _geometry_writes(rig):
    return [(key, value) for key, value in rig.settings.writes if key.endswith("/geometry")]


def _settle(rig):
    QTest.qWait(160)
    rig.app.processEvents()


def test_twenty_moves_do_not_mutate_settings_until_settled(rig):
    window = rig.window()
    before = rig.path.read_bytes()
    changes = 0
    for index in range(20):
        window.move(80 + index * 3, 80)
        rig.app.processEvents()
        changes += rig.path.read_bytes() != before
    assert _geometry_writes(rig) == []
    assert changes == 0
    _settle(rig)
    assert len(_geometry_writes(rig)) == 1
    assert rig.path.read_bytes() != before
    assert rig.settings.value("window/geometry") == window.saveGeometry()
    assert rig.settings.value("unrelated/value") == "preserved"


@pytest.mark.parametrize("operation", ["close", "hide", "deleteLater", "native_delete"])
def test_leaving_window_before_delay_saves_final_geometry_once(rig, operation):
    window = rig.window()
    window.move(170, 130)
    expected = window.saveGeometry()
    assert _geometry_writes(rig) == []
    if operation == "native_delete":
        delete(window)
    else:
        getattr(window, operation)()
    rig.app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert _geometry_writes(rig) == [("window/geometry", expected)]
    rig.settings.sync()
    assert QSettings(str(rig.path), QSettings.IniFormat).value("window/geometry") == expected


def test_active_drag_pause_defers_geometry_but_not_other_settings(rig):
    from cdmw.ui.window_interaction import ensure_window_interaction_tracker

    window = rig.window()
    tracker = ensure_window_interaction_tracker(rig.app)
    tracker.begin(window)
    window.move(180, 90)
    before = rig.path.read_bytes()
    QTest.qWait(350)
    assert tracker.is_active(window)
    assert _geometry_writes(rig) == []
    assert rig.path.read_bytes() == before
    rig.settings.setValue("unrelated/value", "changed during drag")
    rig.settings.sync()
    assert _geometry_writes(rig) == []
    assert "changed during drag" in rig.path.read_text()
    window.move(240, 90)
    tracker.end(window)
    _settle(rig)
    assert len(_geometry_writes(rig)) == 1
    assert rig.settings.value("window/geometry") == window.saveGeometry()


def test_active_window_does_not_delay_another_window_save(rig):
    from cdmw.ui.window_interaction import ensure_window_interaction_tracker

    moving = rig.window()
    other = rig.window("window/detached/other/geometry")
    tracker = ensure_window_interaction_tracker(rig.app)
    tracker.begin(moving)
    moving.move(120, 90)
    other.move(200, 110)
    _settle(rig)
    assert [key for key, _ in _geometry_writes(rig)] == ["window/detached/other/geometry"]
    tracker.end(moving)
    _settle(rig)
    assert [key for key, _ in _geometry_writes(rig)] == [
        "window/detached/other/geometry", "window/geometry",
    ]


@pytest.mark.parametrize("operation", ["flush", "aboutToQuit"])
def test_orderly_flush_preserves_pending_geometry_even_during_drag(rig, operation):
    from cdmw.ui.window_interaction import ensure_window_interaction_tracker

    window = rig.window()
    tracker = ensure_window_interaction_tracker(rig.app)
    tracker.begin(window)
    window.move(200, 150)
    expected = window.saveGeometry()
    if operation == "flush":
        rig.policy.flush()
    else:
        rig.app.aboutToQuit.emit()
    assert _geometry_writes(rig) == [("window/geometry", expected)]
    assert QSettings(str(rig.path), QSettings.IniFormat).value("window/geometry") == expected
    tracker.end(window)
    _settle(rig)
    assert len(_geometry_writes(rig)) == 1


def test_minimizing_keeps_latest_pending_normal_geometry(rig):
    window = rig.window()
    window.move(230, 140)
    expected = window.saveGeometry()
    window.showMinimized()
    _settle(rig)
    assert _geometry_writes(rig) == [("window/geometry", expected)]
    restored = QWidget()
    try:
        assert restored.restoreGeometry(rig.settings.value("window/geometry"))
        assert not restored.isMinimized()
        assert restored.pos() == window.normalGeometry().topLeft()
    finally:
        restored.deleteLater()


def test_maximized_state_survives_deferred_save_and_restore(rig):
    window = rig.window()
    window.showMaximized()
    _settle(rig)
    assert len(_geometry_writes(rig)) == 1
    restored = QWidget()
    try:
        assert restored.restoreGeometry(rig.settings.value("window/geometry"))
        assert restored.isMaximized()
        assert not restored.isMinimized()
    finally:
        restored.deleteLater()


def test_reinstall_flushes_old_policy_without_leaving_a_save_timer(rig):
    owner = rig.window()
    previous = persistence.install_layout_persistence(owner, rig.settings)
    owner.move(250, 160)
    expected = owner.saveGeometry()
    replacement = persistence.install_layout_persistence(owner, rig.settings)
    try:
        assert rig.settings.value("window/geometry") == expected
        assert not previous._geometry_timer.isActive()
    finally:
        rig.app.removeEventFilter(replacement)
        replacement.deleteLater()
        del rig.app._cdmw_layout_persistence


def test_existing_detached_key_and_dialog_restore_are_preserved(rig):
    detached = rig.window()
    detached.tool_key = "sample-tool"
    detached.owner = object()
    assert rig.policy._window_key(detached) == "window/detached/sample-tool/geometry"
    detached.move(190, 100)
    rig.policy.flush()
    saved = rig.settings.value("window/geometry")
    dialog = QDialog()
    dialog.setObjectName("remembered-dialog")
    key = rig.policy._window_key(dialog)
    rig.settings.setValue(key, saved)
    rig.settings.writes.clear()
    rig.policy.watch_window(dialog, key)
    dialog.show()
    rig.app.processEvents()
    _settle(rig)
    try:
        assert dialog.pos() == detached.pos()
        assert dialog.size() == detached.size()
        assert _geometry_writes(rig) == []
    finally:
        dialog.close()
        dialog.deleteLater()
