"""Production dialog geometry under application palettes, fonts and translations."""

from __future__ import annotations

import os
from itertools import combinations
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt
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


def _make_dialog(tmp_path):
    archive = QWidget()
    archive.shell = SimpleNamespace(settings_file_path=tmp_path / "settings.json")
    entry = ArchiveEntry("character/very_long_model_name_123456789.pac", tmp_path / "0.pamt", tmp_path / "0.paz", 0, 1, 1, 0, 0)
    dialog = BatchMeshExportDialog(archive, (BatchMeshSelection(entry),), "fbx")
    return archive, dialog


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


@pytest.mark.parametrize("format", ["obj", "fbx"])
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
            action = next(a for a in self.actions() if a.text() == f"Export Selected as {format.upper()}...")
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
        assert not archive.archive_model_batch_obj_button.isEnabled()
        assert not archive.archive_model_batch_fbx_button.isEnabled()
        entry = ArchiveEntry("object/model.pam", tmp_path / "0.pamt", tmp_path / "0.paz", 0, 1, 1, 0, 0)
        archive.archive_filtered_entries = [entry]
        monkeypatch.setattr(archive.archive_tree, "selectedItems", lambda: [SimpleNamespace(kind="file", value=0)])
        monkeypatch.setattr(archive, "_export_selected_archive_models", calls.append)
        archive._update_archive_model_action_controls(None)
        menu = archive.archive_export_menu_button.menu()
        for format in ("OBJ", "FBX"):
            action = next(a for a in menu.actions() if a.text() == f"Export Selected as {format}")
            assert action.isEnabled()
            action.trigger()
        assert calls == ["obj", "fbx"]
        monkeypatch.setattr(archive.archive_tree, "selectedItems", lambda: [])
        archive._update_archive_model_action_controls(None)
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
        assert dialog.status.text() == english_summary
        assert dialog.cancel_button.text() == "Close"
    finally:
        localizer.shutdown()
        dialog.close()
        archive.close()
