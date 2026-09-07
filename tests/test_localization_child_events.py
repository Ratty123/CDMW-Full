"""Do not inspect native children while Qt is still constructing them."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QChildEvent, QThread
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QLabel, QWidget
from shiboken6 import delete

from cdmw.ui.localization import UiLocalizer


def test_child_added_does_not_resolve_an_incomplete_thread(tmp_path: Path, monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    root = QWidget()
    localizer = UiLocalizer(language_dir=tmp_path, language_code="en")
    inspected = []
    original_child = QChildEvent.child

    def record_child(event):
        inspected.append(event.type())
        return original_child(event)

    monkeypatch.setattr(QChildEvent, "child", record_child)
    localizer.activate_runtime_tracking(root, application=app)
    try:
        # ChildAdded occurs inside QThread's constructor, before its Python
        # wrapper has acquired QThread metadata. This is the Model Library path.
        thread = QThread(root)
        assert inspected == []
        assert thread.parent() is root
        assert thread.metaObject().className() == "QThread"
    finally:
        localizer.shutdown()
        delete(root)


def test_new_hidden_children_and_actions_are_localized_after_construction(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    root = QWidget()
    localizer = UiLocalizer(language_dir=tmp_path, language_code="de")
    localizer.activate_runtime_tracking(root, application=app)
    localizer.apply(root)
    try:
        label = QLabel("Save", root)
        action = QAction("Save", root)
        assert label.text() == "Save"
        for _ in range(3):
            app.processEvents()
        assert label.text() == "Speichern"
        assert action.text() == "Speichern"
        assert not localizer._pending_objects
    finally:
        localizer.shutdown()
        delete(root)


def test_parent_destroyed_before_deferred_localization_is_ignored(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    root = QWidget()
    localizer = UiLocalizer(language_dir=tmp_path, language_code="de")
    localizer.activate_runtime_tracking(root, application=app)
    try:
        QLabel("Save", root)
        delete(root)
        app.processEvents()
        assert not localizer._pending_objects
    finally:
        localizer.shutdown()
