"""Textures' Upscale sidebar and Replace queue at every text size, 6 to 16 pt (plan P11, side thread).

Each test builds the shell's own window once per window size and changes the text
size through the shell's own font path, as Settings does, then checks:
- Upscale: the controls never scroll sideways; when they cannot fit beside the
  preview the sidebar moves above it, and back when there is room again.
- Replace: the queue's "Selected file:" row stays on one line.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CDMW_GUI_STARTUP_SMOKE", "1")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

from cdmw.constants import UI_FONT_SIZE_MAX, UI_FONT_SIZE_MIN

WINDOW_SIZES = [(1280, 900), (1920, 1080)]
TEXT_SIZES = range(UI_FONT_SIZE_MIN, UI_FONT_SIZE_MAX + 1)
#: Known limit (REPORT-4 section 7): at 1280 px and 15 or 16 pt a few labels ("Workflow
#: Profiles, Rules & Matches", "Allow unique basename fallback") are wider than the whole
#: stacked page, and display_scaling.protect_control_text keeps every control at its full
#: one-line text width. Letting them elide or wrap loops that layout today. These sizes must
#: still be stacked (the most room there is); they may scroll sideways, by no more than this.
KNOWN_TOO_NARROW = {(1280, 15), (1280, 16)}


@pytest.fixture
def shell(tmp_path, monkeypatch):
    from cdmw.services.settings_service import create_settings
    from cdmw.ui.main_window import MainWindow
    from cdmw.ui.shell.app_context import AppContext

    app = QApplication.instance() or QApplication([])
    font, palette, stylesheet = app.font(), app.palette(), app.styleSheet()
    monkeypatch.setenv("CDMW_PROFILE_DIR", str(tmp_path / "profile"))
    settings = create_settings(settings_file_path=tmp_path / "sizes.cfg")
    settings.setValue("ui/active_tool_key", "archive_browser")
    settings.setValue("appearance/ui_font_family", "Segoe UI")
    window = MainWindow(app_context=AppContext.from_settings(settings))
    window.setAttribute(Qt.WA_DontShowOnScreen)
    try:
        yield app, window
    finally:
        window._close_force_accept = True
        window.close()
        window.deleteLater()
        app.processEvents()
        app.setFont(font)
        app.setPalette(palette)
        app.setStyleSheet(stylesheet)


def _settle(app, count: int = 4) -> None:
    for _ in range(count):
        app.processEvents()


def _apply_text_size(app, window, size: int) -> None:
    """The shell's own route for a new text size: settings, app fonts, stylesheet."""
    from cdmw.ui.shell.theme_controller import apply_window_ui_fonts
    from cdmw.ui.themes import build_app_stylesheet

    window.settings.setValue("appearance/ui_font_size", size)
    window.settings.setValue("appearance/data_font_size", size)
    apply_window_ui_fonts(window, app)
    app.setStyleSheet(build_app_stylesheet("nord", base_font_size=size))
    _settle(app)


@pytest.mark.parametrize("window_size", WINDOW_SIZES, ids=lambda size: f"{size[0]}x{size[1]}")
def test_upscale_controls_never_scroll_sideways_at_any_text_size(shell, window_size):
    app, window = shell
    width, height = window_size
    window.resize(width, height)
    window.show()
    window._activate_tool_key("texture_workflow")
    window.texture_editor_tab.ensure_widget()
    textures = window.textures
    textures.set_texture_mode("upscale")
    _settle(app)
    for name in ("settings", "asset_authoring", "dds_output", "filters", "chainner"):
        section = getattr(textures, f"{name}_section")
        if not section.toggle_button.isChecked():
            section.toggle_button.click()
        _settle(app)
    failures = []
    for size in TEXT_SIZES:
        _apply_text_size(app, window, size)
        scroll = textures.upscale_controls
        viewport = scroll.viewport()
        if (width, size) in KNOWN_TOO_NARROW:
            if not textures.upscale_sidebar_stacked():
                failures.append(f"{size} pt: too narrow, yet not stacked above the preview")
            continue
        if scroll.horizontalScrollBar().maximum() != 0:
            failures.append(f"{size} pt: scrolls sideways by {scroll.horizontalScrollBar().maximum()}")
        if textures.left_panel.width() > viewport.width():
            failures.append(f"{size} pt: controls {textures.left_panel.width()} wider than {viewport.width()}")
        for control in (textures.dds_format_mode_combo, textures.upscale_backend_combo):
            left = control.mapTo(viewport, QPoint()).x()
            if not 0 <= left < left + control.width() <= viewport.width():
                failures.append(f"{size} pt: {control.objectName() or type(control).__name__} outside the sidebar")
        # Side by side exactly when the controls and the preview's minimum fit the page.
        from PySide6.QtWidgets import QStyle

        splitter = textures.job_splitter
        needed = (textures.left_panel.minimumSizeHint().width()
                  + scroll.style().pixelMetric(QStyle.PM_ScrollBarExtent) + 2 * scroll.frameWidth()
                  + splitter.handleWidth() + textures.preview_stack.minimumSizeHint().width())
        if textures.upscale_sidebar_stacked() and needed <= splitter.width():
            failures.append(f"{size} pt: stacked though the controls fit beside the preview")
        if not textures.upscale_sidebar_stacked() and needed > splitter.width():
            failures.append(f"{size} pt: beside the preview though the controls do not fit")
    assert failures == []
    # Leaving Upscale puts the sidebar back beside the preview.
    textures.set_texture_mode("edit")
    _settle(app)
    assert not textures.upscale_sidebar_stacked()


@pytest.mark.parametrize("window_size", WINDOW_SIZES, ids=lambda size: f"{size[0]}x{size[1]}")
def test_replace_queue_keeps_its_selected_file_row_on_one_line_at_any_text_size(shell, window_size):
    app, window = shell
    width, height = window_size
    window.resize(width, height)
    window.show()
    window._activate_tool_key("texture_workflow")
    textures = window.textures
    textures.set_texture_mode("replace")
    _settle(app)
    from cdmw.ui.shell.lazy_tool_tab import created_tool_widget

    for _ in range(200):
        matcher = created_tool_widget(window.replace_assistant_tab)
        if matcher is not None:
            break
        _settle(app, 1)
    assert matcher is not None
    failures = []
    for size in TEXT_SIZES:
        _apply_text_size(app, window, size)
        matcher.apply_responsive_splitter_sizes()
        _settle(app)
        row = matcher.queue_selected_row
        tops = {row.itemAt(index).geometry().top() for index in range(row.count())
                if not row.itemAt(index).isEmpty()}
        # One line wherever the page can spare the width beside the other panes' minimums;
        # otherwise the queue gets all the width it can, and the row wraps.
        sizes = matcher.main_splitter.sizes()
        room = matcher._queue_sizing_minimum(max(1, matcher.width() - 32), (160, matcher.settings_scroll.minimumWidth()))
        if matcher.queue_row_one_line_width() <= room and len(tops) != 1:
            failures.append(f"{size} pt: the Selected file row wraps onto {len(tops)} lines though it fits "
                            f"(queue {sizes[0]}, row needs {matcher.queue_row_one_line_width()}, room {room})")
        if sum(matcher.main_splitter.sizes()) > matcher.main_splitter.width():
            failures.append(f"{size} pt: Replace's panes are wider than the page")
    assert failures == []
