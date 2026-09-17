from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QRect, QSize, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMenu, QPushButton, QVBoxLayout, QWidget

from cdmw.ui.display_scaling import (
    CurrentToolStack, ensure_app_display_scaling, fit_window_to_screen,
    protect_control_text, scrollable_content,
)
from tests.qt_font_metrics_support import ensure_default_ui_font_available
from cdmw.ui.shell.compact.icons import compact_line_icon
from cdmw.ui.wrapping_layout import WrappingLayout


@pytest.fixture
def app():
    app = QApplication.instance() or QApplication([])
    if not ensure_default_ui_font_available():
        pytest.skip("The application font is required for text geometry checks")
    app.setStyle("Fusion")
    yield app
    policy = getattr(app, "_cdmw_display_scaling", None)
    if policy is not None:
        app.removeEventFilter(policy)
        policy.deleteLater()
        del app._cdmw_display_scaling
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def _settle(app):
    for _ in range(8):
        app.processEvents()


def test_late_controls_and_font_changes_keep_full_text(app):
    ensure_app_display_scaling(app)
    dialog = QDialog()
    layout = QVBoxLayout(dialog)
    dialog.show()
    button = QPushButton("References and selected files")
    button.setFixedSize(90, 26)
    layout.addWidget(button)
    button.show()
    button.setFont(QFont("Segoe UI", 15))
    _settle(app)
    assert button.font().pointSize() == 15
    assert button.height() >= button.fontMetrics().height() + 12
    assert button.width() >= button.sizeHint().width()
    button.setText("A longer translated action with selected references")
    _settle(app)
    assert button.width() >= button.sizeHint().width()
    large_width = button.minimumWidth()
    button.setFont(QFont("Segoe UI", 8))
    _settle(app)
    assert button.minimumWidth() < large_width
    assert button.font().pointSize() == 8
    dialog.close()
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_oversized_dialog_scrolls_to_actions_and_preserves_nested_preview_parent(app):
    dialog = QDialog()
    dialog.setMinimumSize(1180, 780)
    layout = QVBoxLayout(dialog)
    preview_container = QWidget()
    preview_layout = QVBoxLayout(preview_container)
    preview = QLabel("Resident preview stand-in")
    preview_layout.addWidget(preview)
    layout.addWidget(preview_container)
    action = QPushButton("Apply")
    layout.addWidget(action)
    dialog.show()
    fit_window_to_screen(dialog, QRect(100, 80, 960, 500))
    _settle(app)
    scroll = dialog._display_overflow_scroll
    assert QRect(100, 80, 960, 500).contains(dialog.frameGeometry())
    assert scroll.horizontalScrollBar().maximum() > 0
    assert scroll.verticalScrollBar().maximum() > 0
    scroll.ensureWidgetVisible(action)
    _settle(app)
    assert scroll.viewport().rect().intersects(action.rect().translated(action.mapTo(scroll.viewport(), action.rect().topLeft())))
    assert preview.parentWidget() is preview_container
    body = scroll.widget()
    fit_window_to_screen(dialog, QRect(0, 0, 1920, 1040))
    fit_window_to_screen(dialog, QRect(0, 0, 960, 500))
    assert scroll.widget() is body
    assert body.layout() is layout
    assert preview.parentWidget() is preview_container
    dialog.close()
    dialog.deleteLater()


def test_inactive_tools_do_not_force_scrollbars_on_small_tools(app):
    stack = CurrentToolStack()
    large, small = QWidget(), QWidget()
    large.setMinimumSize(1600, 1000)
    small.setMinimumSize(200, 100)
    stack.addWidget(large)
    stack.addWidget(small)
    scroll = scrollable_content(stack)
    scroll.resize(600, 400)
    scroll.show()
    _settle(app)
    assert scroll.horizontalScrollBar().maximum() > 0
    stack.setCurrentWidget(small)
    _settle(app)
    assert stack.minimumSizeHint() == QSize(200, 100)
    assert scroll.horizontalScrollBar().maximum() == 0
    assert scroll.verticalScrollBar().maximum() == 0
    scroll.close()
    scroll.deleteLater()


def test_artwork_and_popups_keep_their_geometry(app):
    artwork = QLabel()
    artwork.setFixedSize(24, 24)
    protect_control_text(artwork)
    assert artwork.size() == QSize(24, 24)
    menu = QMenu()
    menu.resize(1100, 700)
    before = menu.size()
    fit_window_to_screen(menu, QRect(0, 0, 640, 400))
    assert menu.size() == before
    artwork.deleteLater()
    menu.deleteLater()


@pytest.mark.parametrize("ratio", [1.0, 1.25, 1.5, 2.0, 3.0])
def test_line_icons_render_at_requested_device_resolution(app, ratio):
    icon = compact_line_icon("folder", app.palette())
    pixmap = icon.pixmap(QSize(18, 18), ratio)
    assert pixmap.width() >= int(18 * ratio)
    assert pixmap.devicePixelRatio() == pytest.approx(ratio, abs=0.03)
    assert not pixmap.isNull()


def test_actions_wrap_without_squeezing_translated_text(app):
    panel = QWidget()
    panel.setFont(QFont("Segoe UI", 15))
    layout = WrappingLayout(panel)
    buttons = [QPushButton(text) for text in ("References", "Selected files", "Refresh")]
    for button in buttons:
        button.setFont(panel.font())
        protect_control_text(button)
        layout.addWidget(button)
    panel.resize(290, 200)
    panel.show()
    _settle(app)
    assert buttons[-1].y() > buttons[0].y()
    assert all(button.width() >= button.minimumWidth() for button in buttons)
    panel.resize(900, 200)
    _settle(app)
    assert len({button.y() for button in buttons}) == 1
    panel.close()
    panel.deleteLater()


def test_settings_performance_cards_use_one_column_when_narrow(app, tmp_path):
    from cdmw.services.settings_service import create_settings
    from cdmw.ui.settings_tab import SettingsTab
    settings = create_settings(settings_file_path=tmp_path / "settings.ini")
    settings.setValue("appearance/ui_font_size", 15)
    tab = SettingsTab(settings=settings, theme_key="crimson_desert")
    tab.setFont(QFont("Segoe UI", 15))
    tab.show_settings_section("performance")
    tab.resize(1000, 680)
    tab.show()
    _settle(app)
    grid = tab.findChild(QWidget, "SettingsPerformanceGrid")
    first, second = grid.layout().itemAt(0).widget(), grid.layout().itemAt(1).widget()
    assert first.x() == second.x()
    assert second.y() >= first.y() + first.height()
    last = grid.layout().itemAt(3).widget()
    assert last.geometry().bottom() < grid.height()
    tab.resize(1700, 900)
    _settle(app)
    assert first.y() == second.y()
    assert second.x() > first.x()
    tab.request_shutdown()
    tab.close()
    tab.deleteLater()
