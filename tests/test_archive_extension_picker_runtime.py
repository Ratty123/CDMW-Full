"""Exercise extension selection through the constructed Archive workspace."""

from collections import Counter
import sys

import pytest
from PySide6.QtCore import Qt
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


@pytest.mark.parametrize("interaction", ["select", "double_click"])
def test_selecting_pac_closes_the_real_picker_before_applying_the_filter(workspace, tmp_path, monkeypatch, interaction):
    archive = _ready(workspace, tmp_path)
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *error: errors.append(error))

    def interact(dialog):
        dialog.show()
        QApplication.processEvents()
        tree = dialog.findChild(QTreeWidget)
        item = _leaf(tree, ".pac")
        QTest.mouseClick(tree.viewport(), Qt.LeftButton, pos=tree.visualItemRect(item).center())
        if interaction == "select":
            next(button for button in dialog.findChildren(QPushButton) if button.text() == "Select Extension").click()
        else:
            QTest.mouseDClick(tree.viewport(), Qt.LeftButton, pos=tree.visualItemRect(item).center())
        assert dialog.result() == QDialog.Accepted and not dialog.isVisible()
        assert archive.textures._combo_value(archive.archive_extension_filter_combo) == "*"
        return dialog.result()

    monkeypatch.setattr(QDialog, "exec", interact)
    archive.archive_extension_picker_button.click()
    assert errors == []
    assert archive.textures._combo_value(archive.archive_extension_filter_combo) == ".pac"
    assert archive.archive_filters_dirty


def test_picker_opens_before_counts_and_updates_in_place_then_disconnects(workspace, tmp_path, monkeypatch):
    archive = _ready(workspace, tmp_path, counts=False)
    controller = archive.archive_remote_bridge.controller
    facets = ArchiveFacetsResult("synthetic-session", (ArchiveFacet(".pac", ".pac", 12),), (), (), ())

    def interact(dialog):
        dialog.show()
        QApplication.processEvents()
        hint = next(label for label in dialog.findChildren(QLabel) if label.text() == "Loading extension counts...")
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
        next(button for button in dialog.findChildren(QPushButton) if button.text() == "Select Extension").click()
        return dialog.result()

    monkeypatch.setattr(QDialog, "exec", interact)
    archive._open_archive_extension_picker()
    assert archive.textures._combo_value(archive.archive_extension_filter_combo) == ".pac"
    QApplication.processEvents()  # Allow the closed dialog to be deleted.
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *error: errors.append(error))
    controller.facetsReady.emit(facets)
    assert errors == []


def test_cancelling_the_extension_picker_preserves_the_current_filter(workspace, tmp_path, monkeypatch):
    archive = _ready(workspace, tmp_path)

    def cancel(dialog):
        dialog.findChild(QTreeWidget).setCurrentItem(_leaf(dialog.findChild(QTreeWidget), ".pac"))
        dialog.reject()
        return dialog.result()

    monkeypatch.setattr(QDialog, "exec", cancel)
    archive._open_archive_extension_picker()
    assert archive.textures._combo_value(archive.archive_extension_filter_combo) == "*"
    assert not archive.archive_filters_dirty


def test_late_counts_restore_the_current_extension_in_the_picker(workspace, tmp_path, monkeypatch):
    archive = _ready(workspace, tmp_path, counts=False)
    archive._rebuild_archive_extension_filter_choices(".pac")

    def interact(dialog):
        tree = dialog.findChild(QTreeWidget)
        assert tree.currentItem() is None
        archive.archive_remote_bridge.controller.facetsReady.emit(ArchiveFacetsResult(
            "synthetic-session", (ArchiveFacet(".pac", ".pac", 12),), (), (), ()))
        assert tree.currentItem().data(0, Qt.UserRole) == ".pac"
        dialog.reject()
        return dialog.result()

    monkeypatch.setattr(QDialog, "exec", interact)
    archive._open_archive_extension_picker()
    assert archive.textures._combo_value(archive.archive_extension_filter_combo) == ".pac"
