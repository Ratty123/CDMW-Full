"""Exercise extension selection through the constructed Archive workspace."""

from collections import Counter
from dataclasses import replace
import sys

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QLineEdit, QPushButton, QTreeWidget

from cdmw.domain.archives.catalogue import ArchiveFacet, ArchiveFacetsResult
from cdmw.ui.archive_browser.mesh_builder_startup_smoke import (
    configure_synthetic_archive_context,
    synthetic_archive_entry,
)
from tests.test_archive_single_backend_workspace import workspace


def _ready(window, tmp_path, *, counts=True):
    archive = window.archive
    configure_synthetic_archive_context(window, synthetic_archive_entry(tmp_path))
    archive.archive_extension_counts = Counter({".pac": 12, ".dds": 4}) if counts else Counter()
    archive._rebuild_archive_extension_filter_choices("*")
    archive.archive_filters_dirty = False
    archive._update_archive_filter_button_state()
    assert not hasattr(archive, "archive_filter_worker")
    assert archive.archive_extension_picker_button.text() == "Select Extension"
    assert archive.archive_extension_picker_button.isEnabled()
    return archive


def _leaf(tree, value):
    for index in range(tree.topLevelItemCount()):
        parent = tree.topLevelItem(index)
        if parent.data(0, Qt.UserRole) == value:
            return parent
        for child_index in range(parent.childCount()):
            child = parent.child(child_index)
            if child.data(0, Qt.UserRole) == value:
                return child
    raise AssertionError(f"Missing extension {value}")


def _open_picker(archive):
    archive.archive_extension_picker_button.click()
    dialog = archive.archive_extension_picker_dialog
    assert dialog is not None and dialog.isVisible()
    QApplication.processEvents()
    return dialog


def _select_button(dialog):
    return next(button for button in dialog.findChildren(QPushButton) if button.text() == "Select Extension")


def _loading_hint(dialog):
    return next(label for label in dialog.findChildren(QLabel) if label.text() == "Loading extension counts...")


def _start_loading(workspace, monkeypatch):
    archive = workspace.archive
    bridge = archive.archive_remote_bridge
    assert bridge.current_session is None
    # Keep unrelated catalogue warmups out of this controlled startup sequence.
    monkeypatch.setattr(archive.archive_item_finder_warmup_controller, "start", lambda *args, **kwargs: None)
    monkeypatch.setattr(archive.archive_character_finder_warmup_controller, "start", lambda *args, **kwargs: None)
    monkeypatch.setattr(workspace, "_publish_archive_catalogue_session_to_consumers", lambda *args: None)
    monkeypatch.setattr(bridge, "request_structure_children", lambda *args: None)
    bridge._begin_pending("Loading archive catalogue...", operation="open")
    workspace.set_busy(False)
    return archive


def test_cached_picker_opens_without_blocking_the_application_or_rescanning(workspace, tmp_path, monkeypatch):
    archive = _ready(workspace, tmp_path)

    class NoScan(list):
        def __iter__(self):
            pytest.fail("Opening the cached picker must not scan archive entries.")

    class BlockedEvents(QObject):
        blocked = 0
        painted = False

        def eventFilter(self, watched, event):
            if event.type() == QEvent.WindowBlocked:
                self.blocked += 1
            if event.type() == QEvent.Paint and watched is archive.archive_extension_picker_dialog:
                self.painted = True
            return False

    archive.archive_entries = NoScan()
    monkeypatch.setattr(QDialog, "exec", lambda _dialog: pytest.fail("The extension picker must not enter a modal loop."))
    events = BlockedEvents()
    app = QApplication.instance()
    app.installEventFilter(events)
    try:
        dialog = _open_picker(archive)
        assert not dialog.isModal()
        assert _leaf(dialog.findChild(QTreeWidget), ".pac").text(1) == "12"
        assert QApplication.activeModalWidget() is None
        assert events.painted and events.blocked == 0
        dialog.reject()
    finally:
        app.removeEventFilter(events)


@pytest.mark.parametrize("counts_before_rows", [False, True])
def test_startup_click_opens_picker_before_first_rows(workspace, tmp_path, monkeypatch, counts_before_rows):
    archive = _start_loading(workspace, monkeypatch)
    controller = archive.archive_remote_bridge.controller
    facets = ArchiveFacetsResult("synthetic-session", (ArchiveFacet(".pac", ".pac", 12),), (), (), ())
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *error: errors.append(error))
    dialog = _open_picker(archive)
    tree = dialog.findChild(QTreeWidget)
    search = dialog.findChild(QLineEdit)
    hint = _loading_hint(dialog)
    assert hint.isVisible() and tree.topLevelItemCount() == 1
    search.setText("pac")
    if counts_before_rows:
        controller.facetsReady.emit(facets)
    configure_synthetic_archive_context(workspace, synthetic_archive_entry(tmp_path))
    controller.queryPublished.emit(archive.archive_remote_bridge.model.query_handle)
    if not counts_before_rows:
        controller.facetsReady.emit(facets)
    assert search.text() == "pac" and not hint.isVisible()
    item = _leaf(tree, ".pac")
    assert item.text(1) == "12" and not item.isHidden()
    controller.facetsReady.emit(ArchiveFacetsResult("obsolete-session", (ArchiveFacet(".dds", ".dds", 4),), (), (), ()))
    assert _leaf(tree, ".pac") is item
    tree.setCurrentItem(item)
    _select_button(dialog).click()
    assert errors == []
    assert archive.archive_extension_picker_dialog is None
    assert archive.textures._combo_value(archive.archive_extension_filter_combo) == ".pac"
    assert archive.archive_filters_dirty


@pytest.mark.parametrize("finish", ["cancel", "window_close", "escape", "destroy", "load_failure", "counts_failure"])
def test_startup_picker_close_disconnects_late_updates(workspace, tmp_path, monkeypatch, finish):
    archive = _start_loading(workspace, monkeypatch)
    bridge = archive.archive_remote_bridge
    controller = bridge.controller
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *error: errors.append(error))
    dialog = _open_picker(archive)
    if finish == "counts_failure":
        configure_synthetic_archive_context(workspace, synthetic_archive_entry(tmp_path))
        controller.queryPublished.emit(bridge.model.query_handle)
    if finish == "cancel":
        dialog.reject()
    elif finish == "window_close":
        dialog.close()
    elif finish == "escape":
        QTest.keyClick(dialog, Qt.Key_Escape)
    elif finish == "destroy":
        dialog.deleteLater()
    else:
        controller.requestFailed.emit("facets" if finish == "counts_failure" else "open", RuntimeError("Fixture load failure"))
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert archive.archive_extension_picker_dialog is None
    assert archive.archive_remote_query_pending == (finish not in {"load_failure", "counts_failure"})
    assert archive.textures._combo_value(archive.archive_extension_filter_combo) == "*"
    assert not archive.archive_filters_dirty
    configure_synthetic_archive_context(workspace, synthetic_archive_entry(tmp_path))
    controller.queryPublished.emit(bridge.model.query_handle)
    controller.facetsReady.emit(ArchiveFacetsResult("synthetic-session", (ArchiveFacet(".pac", ".pac", 12),), (), (), ()))
    controller.requestFailed.emit("facets", RuntimeError("Late fixture failure"))
    assert errors == []


def test_startup_picker_keeps_existing_worker_and_query_gates(workspace, tmp_path, monkeypatch):
    archive = _start_loading(workspace, monkeypatch)
    assert archive.archive_extension_picker_button.isEnabled()
    with monkeypatch.context() as patch:
        patch.setattr(workspace, "worker_thread", object())
        archive._update_archive_filter_button_state()
        assert not archive.archive_extension_picker_button.isEnabled()
    configure_synthetic_archive_context(workspace, synthetic_archive_entry(tmp_path))
    archive._update_archive_filter_button_state()
    assert not archive.archive_extension_picker_button.isEnabled()
    archive.archive_remote_query_pending = False
    archive._update_archive_filter_button_state()
    assert archive.archive_extension_picker_button.isEnabled()


@pytest.mark.parametrize("interaction", ["select", "double_click"])
def test_selecting_pac_closes_the_real_picker_before_applying_the_filter(workspace, tmp_path, monkeypatch, interaction):
    archive = _ready(workspace, tmp_path)
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *error: errors.append(error))
    dialog = _open_picker(archive)
    tree = dialog.findChild(QTreeWidget)
    item = _leaf(tree, ".pac")
    visible_during_change = []
    archive.archive_extension_filter_combo.currentTextChanged.connect(lambda _text: visible_during_change.append(dialog.isVisible()))
    QTest.mouseClick(tree.viewport(), Qt.LeftButton, pos=tree.visualItemRect(item).center())
    if interaction == "select":
        _select_button(dialog).click()
    else:
        QTest.mouseDClick(tree.viewport(), Qt.LeftButton, pos=tree.visualItemRect(item).center())
    assert errors == []
    assert archive.archive_extension_picker_dialog is None
    assert visible_during_change and not any(visible_during_change)
    assert archive.textures._combo_value(archive.archive_extension_filter_combo) == ".pac"
    assert archive.archive_filters_dirty


def test_picker_opens_before_counts_and_updates_in_place_then_disconnects(workspace, tmp_path, monkeypatch):
    archive = _ready(workspace, tmp_path, counts=False)
    controller = archive.archive_remote_bridge.controller
    facets = ArchiveFacetsResult("synthetic-session", (ArchiveFacet(".pac", ".pac", 12),), (), (), ())
    dialog = _open_picker(archive)
    hint = _loading_hint(dialog)
    tree = dialog.findChild(QTreeWidget)
    assert hint.isVisible() and tree.topLevelItemCount() == 1
    controller.facetsReady.emit(ArchiveFacetsResult("obsolete-session", facets.extensions, (), (), ()))
    assert tree.topLevelItemCount() == 1
    dialog.findChild(QLineEdit).setText("pac")
    controller.facetsReady.emit(facets)
    assert not hint.isVisible()
    item = _leaf(tree, ".pac")
    assert item.text(1) == "12" and not item.isHidden()
    tree.setCurrentItem(item)
    _select_button(dialog).click()
    assert archive.textures._combo_value(archive.archive_extension_filter_combo) == ".pac"
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *error: errors.append(error))
    controller.facetsReady.emit(facets)
    assert errors == []


def test_cancelling_the_extension_picker_preserves_the_current_filter(workspace, tmp_path):
    archive = _ready(workspace, tmp_path)
    dialog = _open_picker(archive)
    dialog.findChild(QTreeWidget).setCurrentItem(_leaf(dialog.findChild(QTreeWidget), ".pac"))
    dialog.reject()
    assert archive.textures._combo_value(archive.archive_extension_filter_combo) == "*"
    assert not archive.archive_filters_dirty


def test_late_counts_restore_the_current_extension_in_the_picker(workspace, tmp_path):
    archive = _ready(workspace, tmp_path, counts=False)
    archive._rebuild_archive_extension_filter_choices(".pac")
    dialog = _open_picker(archive)
    tree = dialog.findChild(QTreeWidget)
    assert tree.currentItem() is None
    archive.archive_remote_bridge.controller.facetsReady.emit(ArchiveFacetsResult(
        "synthetic-session", (ArchiveFacet(".pac", ".pac", 12),), (), (), ()))
    assert tree.currentItem().data(0, Qt.UserRole) == ".pac"
    dialog.reject()
    assert archive.textures._combo_value(archive.archive_extension_filter_combo) == ".pac"


def test_repeated_clicks_keep_one_picker_and_reopening_uses_current_counts(workspace, tmp_path):
    archive = _ready(workspace, tmp_path)
    dialog = _open_picker(archive)
    search = dialog.findChild(QLineEdit)
    search.setText("pac")
    assert _open_picker(archive) is dialog
    assert search.text() == "pac"
    dialog.reject()
    archive.archive_extension_counts[".pac"] = 24
    reopened = _open_picker(archive)
    assert reopened is not dialog
    assert _leaf(reopened.findChild(QTreeWidget), ".pac").text(1) == "24"
    next(button for button in reopened.findChildren(QPushButton) if button.text() == "All Files").click()
    assert archive.archive_extension_picker_dialog is None
    assert archive.textures._combo_value(archive.archive_extension_filter_combo) == "*"


@pytest.mark.parametrize("operation", ["open", "query", "retry"])
def test_new_archive_operation_closes_picker_without_changing_filter(workspace, tmp_path, operation):
    archive = _ready(workspace, tmp_path)
    dialog = _open_picker(archive)
    dialog.findChild(QTreeWidget).setCurrentItem(_leaf(dialog.findChild(QTreeWidget), ".pac"))
    archive.archive_remote_bridge._begin_pending("Fixture archive operation", operation=operation)
    assert not dialog.isVisible() and archive.archive_extension_picker_dialog is None
    assert archive.textures._combo_value(archive.archive_extension_filter_combo) == "*"
    assert not archive.archive_filters_dirty


def test_replaced_session_closes_picker_without_applying_stale_selection(workspace, tmp_path):
    archive = _ready(workspace, tmp_path)
    bridge = archive.archive_remote_bridge
    dialog = _open_picker(archive)
    bridge.controller.queryPublished.emit(replace(bridge.model.query_handle, session_id="new-session"))
    assert not dialog.isVisible() and archive.archive_extension_picker_dialog is None
    assert archive.textures._combo_value(archive.archive_extension_filter_combo) == "*"
