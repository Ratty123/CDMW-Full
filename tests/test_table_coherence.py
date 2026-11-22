"""Table coherence fits columns without undoing the user's widths or sizing hidden columns."""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QApplication, QTableView

from cdmw.ui import layout_persistence as persistence
from cdmw.ui.table_coherence import fit_resizable_columns


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _table(app, columns: int = 4) -> QTableView:
    model = QStandardItemModel(3, columns)
    model.setHorizontalHeaderLabels([f"Column {index}" for index in range(columns)])
    for row in range(3):
        for col in range(columns):
            model.setItem(row, col, QStandardItem(f"r{row}c{col}"))
    view = QTableView()
    view.setModel(model)
    view.resize(900, 300)
    view.show()
    app.processEvents()
    return view


def _visible_width(view: QTableView) -> int:
    header = view.horizontalHeader()
    return sum(header.sectionSize(col) for col in range(header.count()) if not header.isSectionHidden(col))


def test_a_hidden_column_takes_no_slack_and_leaves_no_void(app) -> None:
    view = _table(app)
    try:
        header = view.horizontalHeader()
        header.hideSection(3)
        fit_resizable_columns(view, force=True)
        app.processEvents()
        assert header.isSectionHidden(3)
        assert _visible_width(view) == view.viewport().width()
    finally:
        view.close()
        view.deleteLater()


def test_restored_column_widths_survive_the_fit_on_show_and_on_model_changes(app, tmp_path) -> None:
    settings = QSettings(str(tmp_path / "layout.cfg"), QSettings.IniFormat)
    policy = persistence.UiLayoutPersistence(settings)
    view = _table(app)
    try:
        header = view.horizontalHeader()
        policy.watch_header(header)
        key = policy._headers[header][0]
        saved = [210, 90, 130, 70]
        settings.setValue(key, json.dumps(saved))
        assert policy.restore_header(header)
        # What the filter does on Show, and again on dataChanged and modelReset.
        fit_resizable_columns(view)
        view.model().setItem(0, 0, QStandardItem("a much longer value than before in this cell"))
        fit_resizable_columns(view)
        app.processEvents()
        widths = [header.sectionSize(col) for col in range(header.count())]
        assert widths[:3] == saved[:3]
        # Every column is the user's, so the last one takes the slack rather than leave a void.
        assert widths[3] >= saved[3] and sum(widths) == view.viewport().width()
    finally:
        view.close()
        view.deleteLater()
        policy.deleteLater()
