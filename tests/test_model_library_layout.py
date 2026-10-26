from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QPushButton

from cdmw.services.settings_service import create_settings
from cdmw.ui.themes import build_app_stylesheet, get_theme


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _make_tab(settings_path: Path, base_dir: Path):
    from cdmw.ui.model_library import ModelLibraryTab

    app = _app()
    tab = ModelLibraryTab(settings=create_settings(settings_file_path=settings_path), base_dir=base_dir)
    tab.resize(1280, 800)
    tab.show()
    app.processEvents()
    return tab


def _close(tab) -> None:
    app = _app()
    tab.close()
    tab.deleteLater()
    app.processEvents()


@pytest.fixture
def tab(tmp_path: Path):
    tab = _make_tab(tmp_path / "settings.cfg", tmp_path)
    try:
        yield tab
    finally:
        _close(tab)


def test_sources_lane_shows_only_the_active_views_source(tab) -> None:
    assert tab.mirror_group.isVisibleTo(tab)
    assert not tab.local_group.isVisibleTo(tab)
    assert tab.download_button.isVisibleTo(tab)
    assert not tab.results_filter_field_combo.isVisibleTo(tab)

    tab._set_active_results_view("local", persist=False)

    assert tab.local_group.isVisibleTo(tab)
    assert not tab.mirror_group.isVisibleTo(tab)
    assert not tab.download_button.isVisibleTo(tab)
    assert tab.results_filter_field_combo.isVisibleTo(tab)
    assert tab._local_filter_fields.isVisibleTo(tab.filters_strip)
    assert not tab._mirror_filter_fields.isVisibleTo(tab.filters_strip)


def test_sources_lane_and_filters_toggle_and_survive_a_restart(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.cfg"
    tab = _make_tab(settings_path, tmp_path)
    try:
        lane = tab._model_library_controls_panel
        assert lane.isVisibleTo(tab)
        assert not tab.filters_strip.isVisibleTo(tab)
        assert not tab.column_filter_row.isVisibleTo(tab)

        tab.sources_toggle_button.click()
        tab.filters_toggle_button.click()
        _app().processEvents()
        assert not lane.isVisibleTo(tab)
        assert tab.filters_strip.isVisibleTo(tab)
        assert tab.column_filter_row.isVisibleTo(tab)
    finally:
        _close(tab)

    reopened = _make_tab(settings_path, tmp_path)
    try:
        assert not reopened._model_library_controls_panel.isVisibleTo(reopened)
        assert reopened.filters_strip.isVisibleTo(reopened)

        reopened.sources_toggle_button.click()
        _app().processEvents()
        assert reopened._model_library_controls_panel.isVisibleTo(reopened)
        assert 256 <= reopened._model_library_splitter.sizes()[0] <= 300
    finally:
        _close(reopened)


def test_filters_button_counts_hidden_filters_and_clear_resets_them(tab, monkeypatch) -> None:
    searches: list[object] = []
    monkeypatch.setattr(tab, "search_mirror", lambda **kwargs: searches.append(kwargs))
    assert tab.filters_toggle_button.text() == "Filters"
    assert not tab.clear_filters_button.isEnabled()

    tab.license_filter_edit.setText("CC0")
    tab.results_column_filter_edits[1].setText("sword")
    tab.hide_downloaded_checkbox.setChecked(True)

    assert not tab.filters_strip.isVisibleTo(tab)
    assert tab.filters_toggle_button.text() == "Filters (3)"
    assert tab.clear_filters_button.isEnabled()

    tab.clear_filters_button.click()

    assert tab.license_filter_edit.text() == ""
    assert tab.results_column_filter_edits[1].text() == ""
    assert not tab.hide_downloaded_checkbox.isChecked()
    assert tab.filters_toggle_button.text() == "Filters"
    assert not tab.clear_filters_button.isEnabled()
    # The licence filter narrowed the catalogue query, so clearing it searches again.
    assert searches == [{}]

    tab._set_active_results_view("local", persist=False)
    tab.local_texture_filter_combo.setCurrentIndex(tab.local_texture_filter_combo.findData("missing"))
    assert tab.filters_toggle_button.text() == "Filters (1)"


def test_column_filters_sit_over_their_columns_through_resize_and_scroll(tab) -> None:
    app = _app()
    tab._set_filters_visible(True, persist=False)
    app.processEvents()
    header = tab.results_tree.header()

    def assert_aligned() -> None:
        for column, edit in tab.results_column_filter_edits.items():
            section_left = header.mapTo(tab, QPoint(header.sectionViewportPosition(column), 0)).x()
            assert edit.mapTo(tab, QPoint(0, 0)).x() == section_left + 1, column
            assert edit.width() == header.sectionSize(column) - 2, column

    assert_aligned()
    header.resizeSection(1, 340)
    app.processEvents()
    assert_aligned()
    scroll_bar = tab.results_tree.horizontalScrollBar()
    assert scroll_bar.maximum() > 0
    scroll_bar.setValue(scroll_bar.maximum())
    app.processEvents()
    assert_aligned()


def test_empty_states_name_the_next_step(tab) -> None:
    assert tab.empty_results_label.isVisibleTo(tab)
    assert "Build the search index under Sources" in tab.empty_results_label.text()

    tab._set_active_results_view("local", persist=False)
    tab._update_empty_results_message(0, 0)
    assert tab.empty_results_label.text() == "No local models are loaded. Add a model folder under Sources."

    tab._update_empty_results_message(0, 5)
    assert tab.empty_results_label.text() == "No results match the current filters."


def test_disabled_primary_button_paints_as_disabled() -> None:
    app = _app()
    theme_key = "crimson_desert"
    theme = get_theme(theme_key)
    previous_style = app.styleSheet()
    app.setStyleSheet(build_app_stylesheet(theme_key))
    button = QPushButton("Use in Create New Item")
    button.setObjectName("EditorPrimaryButton")
    button.resize(220, 30)
    try:
        button.setEnabled(False)
        disabled = button.grab().toImage().pixelColor(4, 15)
        button.setEnabled(True)
        enabled = button.grab().toImage().pixelColor(4, 15)
    finally:
        button.deleteLater()
        app.setStyleSheet(previous_style)

    assert disabled == QColor(theme["button_disabled"])
    assert enabled == QColor(theme["accent"])
