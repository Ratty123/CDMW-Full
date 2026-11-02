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


class _RunningThread:
    def isRunning(self) -> bool:  # noqa: N802
        return True


def test_row_identity_survives_import_path_being_filled_in(tab) -> None:
    mirror = {"kind": "mirror", "uid": "abc123", "name": "Axe"}
    local = {"kind": "local", "path": "D:/models/axe.zip", "name": "axe"}
    before = (tab._payload_population_key(mirror), tab._payload_population_key(local))

    mirror["import_path"] = "D:/downloads/Axe-abc123/gltf/scene.gltf"
    local["import_path"] = "D:/cache/axe/scene.gltf"

    assert (tab._payload_population_key(mirror), tab._payload_population_key(local)) == before


def test_new_selection_supersedes_a_running_inline_preview(tab, tmp_path: Path, monkeypatch) -> None:
    import threading

    model = tmp_path / "next.glb"
    model.write_bytes(b"glTF")
    payload = {"kind": "local", "path": str(model), "import_path": str(model), "name": "next"}
    running_stop = threading.Event()
    tab._task_thread = _RunningThread()
    tab._inline_preview_task_running = True
    tab._stop_event = running_stop
    previous_preview_request = tab._inline_preview_request_id
    resolved: list[Path] = []
    monkeypatch.setattr(tab, "_selected_payload", lambda: payload)

    tab._request_payload_import_path(
        payload,
        status="Resolving model for inline preview...",
        on_resolved=resolved.append,
        on_missing=lambda: resolved.append(Path("missing")),
    )

    assert running_stop.is_set()
    assert tab._inline_preview_request_id > previous_preview_request
    assert resolved == [] and tab._pending_model_action_after_task is not None
    retry = tab._pending_model_action_after_task
    tab._pending_model_action_after_task = None
    tab._task_thread = None
    tab._stop_event = None
    tab._inline_preview_task_running = False
    retry()
    assert resolved == [model]


def test_returning_to_local_restores_the_saved_sort(tab) -> None:
    tab.settings.setValue("model_library/result_sort_column", 6)
    tab.settings.setValue("model_library/result_sort_order", "desc")
    tab._set_active_results_view("mirror", persist=False)
    tab._use_result_source_order()
    assert tab._result_sort_column == -1

    tab._set_active_results_view("local", persist=False)

    assert tab._result_sort_column == 6
    assert tab.results_tree.header().isSortIndicatorShown()


def test_icon_output_refuses_without_taking_over_a_running_task(tab, tmp_path: Path) -> None:
    import threading

    from PySide6.QtGui import QImage

    running_stop = threading.Event()
    tab._task_thread = _RunningThread()
    tab._stop_event = running_stop
    try:
        tab._queue_inline_preview_icon_output(
            QImage(4, 4, QImage.Format.Format_ARGB32),
            payload={"kind": "local", "name": "axe"},
            loaded_path=tmp_path / "axe.glb",
            native_capture=True,
        )
        assert tab._stop_event is running_stop
        assert not tab._icon_output_active
    finally:
        tab._task_thread = None
        tab._stop_event = None


def test_showing_the_tab_mid_search_does_not_finish_an_empty_population(tab) -> None:
    tab._populating_results = True
    tab._results_population_active = False
    tab.hide()
    tab.show()
    assert not tab._results_population_timer.isActive()
    tab._populating_results = False


def test_search_during_a_results_task_is_queued_and_supersedes_it(tab) -> None:
    import threading

    results_stop = threading.Event()
    tab._task_thread = _RunningThread()
    tab._results_task_kind = "population"
    tab._results_task_stop_event = results_stop
    try:
        tab.search_mirror(query_override="axe")
        assert results_stop.is_set()
        assert tab._queued_results_action is not None
        tab._results_task_kind = "download"
        tab._results_task_stop_event = None
        tab.scan_local_roots()
        assert tab._queued_results_action == tab.scan_local_roots
    finally:
        tab._task_thread = None
        tab._results_task_kind = ""
        tab._queued_results_action = None


def test_reselecting_the_view_keeps_the_submitted_query(tab) -> None:
    tab._set_active_results_view("local", persist=False)
    tab.search_edit.setText("axe")
    tab._apply_active_results_query()
    tab.search_edit.setText("sword")

    tab._set_active_results_view("local", persist=False)

    assert tab.applied_results_query() == "axe"
    assert tab.search_edit.text() == "sword"


def test_row_clicks_do_not_reenable_actions_during_a_task(tab) -> None:
    tab._task_thread = _RunningThread()
    try:
        tab._update_selection_state()
        assert not tab.preview_button.isEnabled()
        assert not tab.delete_local_button.isEnabled()
        tab._inline_preview_task_running = True
        payload = {"kind": "local", "path": "x.glb", "name": "x"}
        tab._payload_can_preview_here = lambda _payload: True
        tab._selected_payload = lambda: payload
        tab._update_selection_state()
        assert tab.preview_button.isEnabled()
        assert not tab.generate_icon_button.isEnabled()
    finally:
        tab._task_thread = None
        tab._inline_preview_task_running = False
        del tab._payload_can_preview_here
        del tab._selected_payload


def test_stale_generated_icon_is_removed_instead_of_orphaned(tab, tmp_path: Path, monkeypatch) -> None:
    from PySide6.QtGui import QImage

    from cdmw.workers.model_library_workers import ModelLibraryIconOutputResult

    captured: dict[str, object] = {}
    monkeypatch.setattr(tab, "catalogue_dir", lambda: tmp_path)
    monkeypatch.setattr(tab, "_run_task", lambda _status, _task, complete, **_kwargs: captured.update(complete=complete))
    monkeypatch.setattr(tab, "_selected_payload", lambda: {"kind": "local", "name": "other"})
    tab._queue_inline_preview_icon_output(
        QImage(4, 4, QImage.Format.Format_ARGB32),
        payload={"kind": "local", "name": "axe"},
        loaded_path=tmp_path / "axe.glb",
        native_capture=True,
    )
    published = tmp_path / "generated_icons" / "axe-1.png"
    published.parent.mkdir(parents=True)
    published.write_bytes(b"png")

    captured["complete"](ModelLibraryIconOutputResult(tab._icon_output_request_id, published, False))

    assert not published.exists()
