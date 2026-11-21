"""Combo popups fit their rows: no empty space under short lists, long lists scroll.

The app-wide limiter used to pad every row to the font height plus 8 px and add
8 px more, so a four-row list such as Speed & Prefabs' prefab categories opened
with blank space under its last row. It now keeps Qt's own height and only
shrinks long lists to ten rows or 40% of the screen.
"""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QComboBox, QVBoxLayout, QWidget  # noqa: E402

from cdmw.ui.combo_popup_limiter import ComboPopupLimiter, ensure_app_combo_popup_limiter  # noqa: E402
from cdmw.ui.new_item.choice_model import set_choice_rows  # noqa: E402
from cdmw.ui.themes import UI_THEME_SCHEMES, build_app_stylesheet  # noqa: E402


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    ensure_app_combo_popup_limiter(app)
    previous = app.styleSheet()
    app.setStyleSheet(build_app_stylesheet(next(iter(UI_THEME_SCHEMES))))
    yield app
    app.setStyleSheet(previous)


def _spin(app, seconds=0.08):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()


def _open(app, combo):
    combo.showPopup()
    _spin(app)
    view = combo.view()
    popup = view.parentWidget()
    return popup, view


def _rows_height(combo, rows):
    view = combo.view()
    return sum(view.visualRect(combo.model().index(row, 0)).height() for row in range(rows))


def _host(app, *combos):
    host = QWidget()
    layout = QVBoxLayout(host)
    for combo in combos:
        layout.addWidget(combo)
    host.resize(900, 300)
    host.show()
    _spin(app)
    return host


@pytest.mark.parametrize("count", [1, 2, 4, 7, 10])
def test_short_lists_leave_no_space_under_the_last_row(app, count):
    combo = QComboBox()
    combo.addItems([f"Category {row}" for row in range(count)])
    host = _host(app, combo)
    try:
        popup, view = _open(app, combo)
        assert view.viewport().height() == _rows_height(combo, count)
        assert popup.height() - view.viewport().height() <= 8
    finally:
        combo.hidePopup()
        host.close()


def test_long_lists_stop_at_ten_rows_and_scroll(app):
    combo = QComboBox()
    combo.setMaxVisibleItems(30)
    combo.addItems([f"Extension {row}" for row in range(60)])
    host = _host(app, combo)
    try:
        popup, view = _open(app, combo)
        assert view.viewport().height() == _rows_height(combo, ComboPopupLimiter.MAX_VISIBLE_ROWS)
        assert view.verticalScrollBar().maximum() > 0
    finally:
        combo.hidePopup()
        host.close()


def test_reopening_after_the_list_grows_or_shrinks_fits_again(app):
    combo = QComboBox()
    combo.addItems(["One", "Two"])
    host = _host(app, combo)
    try:
        _open(app, combo)
        combo.hidePopup()
        _spin(app)
        combo.addItems([f"More {row}" for row in range(6)])
        popup, view = _open(app, combo)
        assert view.viewport().height() == _rows_height(combo, 8)
        combo.hidePopup()
        _spin(app)
        combo.clear()
        combo.addItems(["Only"])
        popup, view = _open(app, combo)
        assert view.viewport().height() == _rows_height(combo, 1)
    finally:
        combo.hidePopup()
        host.close()


def test_prepared_choice_lists_fit_their_rows(app):
    combo = QComboBox()
    set_choice_rows(combo, [(f"Choice {row}", row) for row in range(3)])
    host = _host(app, combo)
    try:
        popup, view = _open(app, combo)
        assert view.viewport().height() == _rows_height(combo, 3)
    finally:
        combo.hidePopup()
        host.close()


def test_a_list_that_opens_above_its_combo_stays_against_it(app):
    from PySide6.QtCore import QPoint

    combo = QComboBox()
    combo.setMaxVisibleItems(30)
    combo.addItems([f"Row {row}" for row in range(40)])
    host = _host(app, combo)
    try:
        available = combo.screen().availableGeometry()
        host.move(host.x(), available.bottom() - host.height() + 1)
        _spin(app)
        popup, view = _open(app, combo)
        combo_top = combo.mapToGlobal(QPoint(0, 0)).y()
        combo_bottom = combo_top + combo.height()
        if popup.geometry().top() < combo_top:
            assert combo_top - 2 <= popup.geometry().bottom() + 1 <= combo_bottom
        assert available.contains(popup.geometry())
    finally:
        combo.hidePopup()
        host.close()


def test_a_tree_view_popup_is_measured_too(app):
    from PySide6.QtWidgets import QTreeView

    combo = QComboBox()
    view = QTreeView()
    view.setHeaderHidden(True)
    view.setRootIsDecorated(False)
    combo.setView(view)
    combo.setMaxVisibleItems(30)
    combo.addItems([f"Tree row {row}" for row in range(30)])
    host = _host(app, combo)
    try:
        popup, shown = _open(app, combo)
        assert shown.viewport().height() == _rows_height(combo, ComboPopupLimiter.MAX_VISIBLE_ROWS)
    finally:
        combo.hidePopup()
        host.close()
