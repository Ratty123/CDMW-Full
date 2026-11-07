"""Production dialog geometry under application palettes, fonts and translations."""

from __future__ import annotations

import os
from itertools import combinations
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QItemSelection, QItemSelectionModel, QObject, QPoint, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMenu, QPushButton, QTreeWidget, QTreeWidgetItem, QWidget

from cdmw.domain.localization import BUILTIN_LANGUAGES
from cdmw.models import ArchiveEntry
from cdmw.ui.archive_browser import actions
from cdmw.ui.archive_browser.mesh_batch_export_controller import BatchMeshSelection
from cdmw.ui.archive_browser.mesh_batch_export_dialog import BatchMeshExportDialog
from cdmw.ui.display_scaling import protect_control_text
from cdmw.ui.localization import UiLocalizer
from cdmw.ui.themes import UI_THEME_SCHEMES, build_app_palette, build_app_stylesheet
from tests.qt_font_metrics_support import ensure_default_ui_font_available
from tests.test_archive_mesh_export_modes import _ExportWindow


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    assert ensure_default_ui_font_available()
    return app


def _make_dialog(tmp_path, export_format="fbx"):
    archive = QWidget()
    archive.shell = SimpleNamespace(settings_file_path=tmp_path / "settings.json")
    entry = ArchiveEntry("character/very_long_model_name_123456789.pac", tmp_path / "0.pamt", tmp_path / "0.paz", 0, 1, 1, 0, 0)
    dialog = BatchMeshExportDialog(archive, (BatchMeshSelection(entry),), export_format)
    return archive, dialog


@pytest.mark.parametrize("export_format", ["glb", "fbx", "obj"])
def test_mesh_only_choice_is_available_for_rigged_formats(app, tmp_path, export_format):
    archive, dialog = _make_dialog(tmp_path, export_format)
    try:
        assert dialog.windowTitle() == f"Batch Export Selected Models as {export_format.upper()}"
        assert dialog.mesh_only.isHidden() == (export_format == "obj")
        assert not dialog.mesh_only.isChecked()
    finally:
        dialog.close()
        archive.close()


CASES = [(theme, "en", 10) for theme in UI_THEME_SCHEMES]
CASES += [(theme, language.code, size) for theme in ("light", "graphite")
          for language in BUILTIN_LANGUAGES for size in (9, 15)]


@pytest.mark.parametrize("theme,language,size", CASES)
def test_dialog_controls_fit_without_overlaps(app, tmp_path, theme, language, size):
    original = app.palette(), app.styleSheet(), app.font()
    app.setPalette(build_app_palette(theme))
    app.setStyleSheet(build_app_stylesheet(theme, base_font_size=size))
    app.setFont(QFont("Segoe UI", size))
    archive, dialog = _make_dialog(tmp_path)
    localizer = UiLocalizer(language_dir=tmp_path / "languages", language_code=language)
    try:
        localizer.apply(dialog)
        for button in dialog.findChildren(QPushButton):
            protect_control_text(button)
        dialog.resize(640, 480)
        dialog.show()
        for _ in range(5):
            app.processEvents()
        buttons = (dialog.copy_button, dialog.start_button, dialog.cancel_button)
        for button in (*buttons, dialog.browse_button):
            assert button.width() >= button.fontMetrics().horizontalAdvance(button.text()) + 12
            assert button.height() >= button.fontMetrics().height() + 8
        for first, second in combinations(buttons, 2):
            assert not first.geometry().intersects(second.geometry())
        for button in buttons:
            assert dialog.rect().contains(button.geometry())
        for first, second in zip((dialog.options_scroll, dialog.status, dialog.progress_bar, dialog.report),
                                 (dialog.status, dialog.progress_bar, dialog.report, dialog.start_button)):
            assert first.geometry().bottom() < second.geometry().top()
        assert dialog.report.height() >= dialog.report.fontMetrics().height() * 3
        assert dialog.options_scroll.horizontalScrollBar().maximum() == 0
        assert dialog.mesh_only.width() >= dialog.mesh_only.sizeHint().width()
        assert dialog.status.height() >= dialog.status.sizeHint().height()
    finally:
        localizer.shutdown()
        dialog.close()
        archive.close()
        app.setPalette(original[0])
        app.setStyleSheet(original[1])
        app.setFont(original[2])


@pytest.mark.parametrize("format", ["glb", "fbx", "obj"])
def test_context_menu_preserves_all_selected_rows_before_batch_dispatch(app, tmp_path, monkeypatch, format):
    entry = ArchiveEntry("object/a.pam", tmp_path / "0.pamt", tmp_path / "0.paz", 0, 1, 1, 0, 0)
    window = _ExportWindow(entry, tmp_path)
    tree = QTreeWidget(window)
    tree.setSelectionMode(QTreeWidget.ExtendedSelection)
    items = [QTreeWidgetItem(tree, [name]) for name in ("a", "b", "c")]
    tree.setCurrentItem(items[0])
    for item in items[:2]:
        item.setSelected(True)
    tree.show()
    window.show()
    app.processEvents()
    window.archive_tree = tree
    calls = []
    window._export_selected_archive_models = lambda selected_format: calls.append((selected_format, [i.text(0) for i in tree.selectedItems()]))

    class Menu(QMenu):
        def exec(self, position):
            formats = [a.text() for a in self.actions() if a.text().startswith("Batch Export Selected Models as")]
            assert formats == ["Batch Export Selected Models as GLB...", "Batch Export Selected Models as FBX...", "Batch Export Selected Models as OBJ..."]
            action = next(a for a in self.actions() if a.text() == f"Batch Export Selected Models as {format.upper()}...")
            action.trigger()

    monkeypatch.setattr(actions, "QMenu", Menu)
    try:
        window._show_archive_tree_context_menu(tree.visualItemRect(items[1]).center())
        assert calls == [(format, ["a", "b"])]
    finally:
        window.close()


@pytest.mark.parametrize("layout_name", ["compact_rail", "legacy"])
def test_real_archive_export_menu_dispatches_batch_in_both_layouts(app, tmp_path, monkeypatch, layout_name):
    from cdmw.app.events import AppEventBus
    from cdmw.services.service_container import ServiceContainer
    from cdmw.services.settings_service import create_settings
    from cdmw.ui.main_window import MainWindow
    from cdmw.ui.shell.app_context import AppContext
    from cdmw.ui.shell.compact.config import SHELL_VARIANT_SETTING

    monkeypatch.setenv("CDMW_GUI_STARTUP_SMOKE", "1")
    settings = create_settings(settings_file_path=tmp_path / "batch-menu.cfg")
    settings.setValue(SHELL_VARIANT_SETTING, layout_name)
    context = AppContext(settings=settings, services=ServiceContainer.create_default(settings=settings), event_bus=AppEventBus())
    window = MainWindow(app_context=context)
    calls = []
    try:
        assert window.is_compact_shell == (layout_name == "compact_rail")
        archive = window.archive
        assert not archive.archive_model_batch_glb_button.isEnabled()
        assert not archive.archive_model_batch_obj_button.isEnabled()
        assert not archive.archive_model_batch_fbx_button.isEnabled()
        entry = ArchiveEntry("object/model.pam", tmp_path / "0.pamt", tmp_path / "0.paz", 0, 1, 1, 0, 0)
        archive.archive_filtered_entries = [entry]
        monkeypatch.setattr(archive.archive_tree, "selectedItems", lambda: [SimpleNamespace(kind="file", value=0)])
        monkeypatch.setattr(archive, "_export_selected_archive_models", calls.append)
        archive._update_archive_model_action_controls(None)
        menu = archive.archive_export_menu_button.menu()
        formats = [a.text() for a in menu.actions() if a.text().startswith("Batch Export Selected Models as")]
        assert formats == ["Batch Export Selected Models as GLB", "Batch Export Selected Models as FBX", "Batch Export Selected Models as OBJ"]
        for format in ("GLB", "FBX", "OBJ"):
            action = next(a for a in menu.actions() if a.text() == f"Batch Export Selected Models as {format}")
            assert action.isEnabled()
            action.trigger()
        assert calls == ["glb", "fbx", "obj"]
        single_calls = []
        monkeypatch.setattr(archive, "_current_archive_entry", lambda: entry)
        monkeypatch.setattr(archive, "_current_archive_mesh_entry", lambda: entry)
        monkeypatch.setattr(archive, "_start_archive_mesh_export", lambda selected, format_name: single_calls.append((selected, format_name)))
        archive._update_archive_model_action_controls(None)
        assert archive.archive_model_export_glb_button.isEnabled()
        single_formats = [a.text() for a in menu.actions() if a.text() in {"Export This Model as GLB", "Export This Model as FBX", "Export This Model as OBJ"}]
        assert single_formats == ["Export This Model as GLB", "Export This Model as FBX", "Export This Model as OBJ"]
        next(a for a in menu.actions() if a.text() == "Export This Model as GLB").trigger()
        assert single_calls == [(entry, "glb")]
        monkeypatch.setattr(archive.archive_tree, "selectedItems", lambda: [])
        archive._update_archive_model_action_controls(None)
        assert not archive.archive_model_batch_glb_button.isEnabled()
        assert not archive.archive_model_batch_obj_button.isEnabled()
        assert not archive.archive_model_batch_fbx_button.isEnabled()
    finally:
        window.close()
        app.processEvents()


def test_progress_and_final_report_localize_immediately_and_can_switch_back(app, tmp_path):
    from cdmw.services.archive_mesh_batch_export import BatchMeshExportResult

    archive, dialog = _make_dialog(tmp_path)
    localizer = UiLocalizer(language_dir=tmp_path / "languages", language_code="de")
    localizer.activate_runtime_tracking(dialog, application=app)
    try:
        localizer.apply(dialog)
        english_title = "Batch Export Selected Models as FBX"
        assert dialog.windowTitle() == localizer.translate_rendered(english_title)
        assert dialog.windowTitle() != english_title
        dialog._progress(0, 1, "Preparing files", "model.pac")
        assert dialog.status.text() == localizer.translate("Preparing files")
        dialog.controller.results = [BatchMeshExportResult(1, "exported", "model.pac")]
        dialog._finished()
        english_summary = "Exported: 1 | Failed: 0 | Cancelled: 0"
        assert dialog.status.text() == localizer.translate_rendered(english_summary)
        assert dialog.status.text() != english_summary
        assert dialog.report.toPlainText().count("model.pac") == 1
        assert dialog.cancel_button.text() == localizer.translate("Close")
        localizer.load_language("en")
        localizer.apply(dialog)
        assert dialog.windowTitle() == english_title
        assert dialog.status.text() == english_summary
        assert dialog.cancel_button.text() == "Close"
    finally:
        localizer.shutdown()
        dialog.close()
        archive.close()


class _PageService(QObject):
    result_ready = Signal(str, str, object)
    request_failed = Signal(str, object)
    request_cancelled = Signal(str)

    def __init__(self):
        super().__init__()
        self.fetches = []
        self.cancelled = []

    def fetch_page(self, request, *, ui_generation):
        self.fetches.append((request, ui_generation))
        return f"page-{len(self.fetches)}"

    def cancel(self, request_id):
        self.cancelled.append(request_id)
        return True


def _flat_window(app, tmp_path, monkeypatch, rows, *, loaded=4):
    """An Archive Browser whose flat view holds only its first page of `rows`."""
    from cdmw.domain.archives.catalogue import ArchivePage, ArchiveQueryHandle, ArchiveViewMode
    from cdmw.ui.archive_browser import mesh_batch_export_dialog, mesh_import_export
    from cdmw.ui.archive_browser.model import ArchiveBrowserTreeView
    from cdmw.ui.archive_browser.remote_model import RemoteArchiveBrowserModel

    window = _ExportWindow(ArchiveEntry("object/a.pam", tmp_path / "0.pamt", tmp_path / "0.paz", 0, 1, 1, 0, 0), tmp_path)
    view = ArchiveBrowserTreeView(window)
    model = RemoteArchiveBrowserModel(page_size=4, parent=view)
    model.publish_query(ArchiveQueryHandle("session-a", "query-a", 3, len(rows)), view_mode=ArchiveViewMode.FLAT, prime=False)
    assert model.accept_page(ArchivePage("session-a", "query-a", 3, len(rows), 0, rows[:loaded]))
    view.use_remote_model(model)
    view.selectionModel().select(
        QItemSelection(model.index(0, 0), model.index(len(rows) - 1, model.columnCount() - 1)),
        QItemSelectionModel.Select | QItemSelectionModel.Rows)
    window.archive_tree = view
    window.archive_catalogue_service = _PageService()
    window.archive_remote_bridge = SimpleNamespace(model=model, controller=SimpleNamespace(generation=7))
    opened, warnings = [], []

    class Dialog:
        def __init__(self, _archive, selections, export_format):
            opened.append((export_format, [selection.entry.path for selection in selections]))
            self.controller = SimpleNamespace(close=lambda: None)

        def exec(self):
            return 0

        def deleteLater(self):
            pass

    monkeypatch.setattr(mesh_batch_export_dialog, "BatchMeshExportDialog", Dialog)
    monkeypatch.setattr(mesh_import_export.QMessageBox, "warning", lambda _parent, _title, text: warnings.append(text))
    monkeypatch.setattr(mesh_import_export.QMessageBox, "information", lambda _parent, _title, text: warnings.append(text))
    return window, model, opened, warnings


def _page(rows, start, *, generation=3):
    from cdmw.domain.archives.catalogue import ArchivePage

    return ArchivePage("session-a", "query-a", generation, len(rows), start, rows[start:start + 4])


def test_batch_export_reads_selected_rows_the_flat_view_never_loaded(app, tmp_path, monkeypatch):
    """Ctrl+A over a long filtered list used to export only the pages scrolled through."""
    from tests.test_archive_remote_preview_dependencies import _dto

    rows = tuple(_dto(n, f"texture/{n}.dds" if n % 5 == 0 else f"object/{n}.pam") for n in range(10))
    window, model, opened, warnings = _flat_window(app, tmp_path, monkeypatch, rows)
    service = window.archive_catalogue_service
    try:
        # Rows without a loaded page are not selectable, so the selected items name only the
        # loaded page while the selection itself still spans every row.
        assert len(window.archive_tree.selectedItems()) == 4
        assert [(r.top(), r.bottom()) for r in window.archive_tree.selectionModel().selection()] == [(0, 9)]
        window._export_selected_archive_models("obj")
        assert not opened and [(r.query_id, r.page_start, r.page_size, g) for r, g in service.fetches] == [("query-a", 4, 4, 7)]
        assert window.status_messages[-1][0] == "Reading the selected rows from the archive list..."
        window._export_selected_archive_models("obj")
        assert len(service.fetches) == 1, "a second request waits for the first read"
        service.result_ready.emit("page-1", "fetch_page", _page(rows, 4))
        assert [r.page_start for r, _g in service.fetches] == [4, 8]
        service.result_ready.emit("page-2", "fetch_page", _page(rows, 8))
        _drain(app, lambda: opened)
        assert opened == [("obj", [f"object/{n}.pam" for n in range(10) if n % 5])]
        assert not warnings
    finally:
        window.close()


def test_batch_export_refuses_rows_read_from_a_changed_list(app, tmp_path, monkeypatch):
    from tests.test_archive_remote_preview_dependencies import _dto

    rows = tuple(_dto(n, f"object/{n}.pam") for n in range(10))
    window, _model, opened, warnings = _flat_window(app, tmp_path, monkeypatch, rows)
    service = window.archive_catalogue_service
    try:
        window._export_selected_archive_models("glb")
        service.result_ready.emit("page-1", "fetch_page", _page(rows, 4, generation=4))
        _drain(app, lambda: warnings)
        assert warnings == ["The archive list changed while the selected rows were read. Select the models again."]
        assert not opened and len(service.fetches) == 1
        window._export_selected_archive_models("glb")
        service.request_failed.emit("page-2", RuntimeError("worker stopped"))
        _drain(app, lambda: len(warnings) == 2)
        assert warnings[-1] == "The archives could not be read: worker stopped"
        assert not opened
    finally:
        window.close()


def test_batch_export_bounds_the_rows_it_reads(app, tmp_path, monkeypatch):
    from cdmw.ui.archive_browser import mesh_batch_export_controller
    from tests.test_archive_remote_preview_dependencies import _dto

    rows = tuple(_dto(n, f"object/{n}.pam") for n in range(10))
    window, _model, opened, warnings = _flat_window(app, tmp_path, monkeypatch, rows)
    monkeypatch.setattr(mesh_batch_export_controller, "MAX_BATCH_SELECTED_ROWS", 9)
    try:
        window._export_selected_archive_models("fbx")
        assert warnings == ["Select at most 9 rows for a batch export. Narrow the filter to the models you want."]
        assert not opened and not window.archive_catalogue_service.fetches
    finally:
        window.close()


def _drain(app, predicate, timeout=5.0):
    import time

    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    assert predicate()
