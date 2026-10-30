"""Original-format extraction through the real Archive Browser controls."""
from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QApplication, QMenu, QToolButton

from cdmw.app.events import AppEventBus
from cdmw.domain.archives.catalogue import (
    ArchiveChildNode, ArchiveChildrenResult, ArchivePage, ArchiveQuery,
    ArchiveQueryHandle, ArchiveSessionHandle, ArchiveViewMode,
)
from cdmw.domain.archives.catalogue_operations import ArchiveExportCollisionPolicy, ArchiveExportSelectionKind
from cdmw.services.service_container import ServiceContainer
from cdmw.services.settings_service import create_settings
from cdmw.ui.archive_browser import actions
from cdmw.ui.archive_browser.remote_model import RemoteChildrenFetch
from cdmw.ui.main_window import MainWindow
from cdmw.ui.shell.app_context import AppContext
from cdmw.ui.shell.compact.config import SHELL_VARIANT_SETTING
from tests.test_archive_remote_window_bridge import _remote


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(params=["compact_rail", "legacy"])
def window(request, app, tmp_path, monkeypatch):
    monkeypatch.setenv("CDMW_GUI_STARTUP_SMOKE", "1")
    settings = create_settings(settings_file_path=tmp_path / "extract.cfg")
    settings.setValue(SHELL_VARIANT_SETTING, request.param)
    context = AppContext(settings=settings, services=ServiceContainer.create_default(settings=settings), event_bus=AppEventBus())
    window = MainWindow(app_context=context)
    archive = window.archive
    monkeypatch.setattr(archive, "_render_archive_preview", lambda *_args: None)
    monkeypatch.setattr(archive, "_prompt_remote_archive_extract_target", lambda root, **_kwargs: (root, True))
    monkeypatch.setattr(archive, "_prompt_remote_archive_extract_options", lambda *_args: (False, ArchiveExportCollisionPolicy.RENAME))
    monkeypatch.setattr(window, "_suggest_archive_extract_root", lambda: tmp_path / "exports")
    window.extract_requests = []
    monkeypatch.setattr(archive.archive_catalogue_service, "export", lambda request, **_kwargs: window.extract_requests.append(request) or "extract-1")
    yield window
    archive._archive_remote_export_request_id = None
    window._finalize_close()
    window.deleteLater()
    app.processEvents()


def _publish(window, view=ArchiveViewMode.FLAT, *, total=5001, folder=False):
    archive = window.archive
    bridge = archive.archive_remote_bridge
    bridge.controller._current_session = ArchiveSessionHandle("session-a", "C:/Game", "fixture", total, 1, True)
    bridge.controller._current_query = ArchiveQuery("session-a", include_text="object/", view_mode=view)
    handle = ArchiveQueryHandle("session-a", "filtered-files", 1, total)
    model = bridge.model
    model.publish_query(handle, view_mode=view, prime=False)
    model.suspend_requests(True)
    rows = tuple(replace(_remote(index + 1, "object/" + name, extension=Path(name).suffix), is_previewable=False)
                 for index, name in enumerate(("data.custom", "image.dds", "mesh.pac")))
    if total:
        if view is ArchiveViewMode.FLAT:
            assert model.accept_page(ArchivePage("session-a", "filtered-files", 1, total, 0, rows))
        else:
            children = ((ArchiveChildNode("object", "object", True, total),) if folder else
                        tuple(ArchiveChildNode(row.path, Path(row.path).name, False, 1, row) for row in rows))
            fetch = RemoteChildrenFetch("session-a", "filtered-files", 1, "root", None, None, 0, 512)
            assert model.accept_children(fetch, ArchiveChildrenResult("session-a", "filtered-files", children, False, total_children=len(children)))
    archive.archive_tree.use_remote_model(model)
    archive.archive_remote_actions_safe = True
    archive._update_archive_selection_state()
    return bridge


def test_filtered_extract_uses_all_query_results_and_survives_busy_updates(window, app):
    archive = window.archive
    bridge = _publish(window)
    assert not archive.archive_filtered_entries
    assert not archive.archive_tree.selectedItems()
    assert not archive.archive_extract_selected_button.isEnabled()
    assert archive.archive_extract_filtered_button.isEnabled()
    window.set_busy(True)
    assert not archive.archive_extract_filtered_button.isEnabled()
    window.set_busy(False)
    assert archive.archive_extract_filtered_button.isEnabled()
    if window.is_compact_shell:
        menu = archive.findChild(QToolButton, "CompactArchiveActionsButton").menu()
        menu.aboutToShow.emit()
        action = next(action for action in menu.actions() if action.text() == "Extract Filtered")
        assert action.isEnabled()
        action.trigger()
    else:
        archive.archive_extract_filtered_button.click()
    request, = window.extract_requests
    assert request.selection_kind is ArchiveExportSelectionKind.QUERY
    assert request.query_id == "filtered-files"
    assert not request.entry_ids and not request.extensions
    archive._update_archive_selection_state()
    assert not archive.archive_extract_filtered_button.isEnabled()
    archive._finish_remote_archive_export()
    assert archive.archive_extract_filtered_button.isEnabled()
    bridge._handle_actions_safe(False)
    archive._update_archive_selection_state()
    assert not archive.archive_extract_filtered_button.isEnabled()
    _publish(window, total=0)
    assert not archive.archive_extract_filtered_button.isEnabled()


@pytest.mark.parametrize("view", [ArchiveViewMode.FLAT, ArchiveViewMode.FOLDERS])
def test_right_click_extracts_mixed_selection_or_whole_filter(window, app, monkeypatch, view):
    archive = window.archive
    bridge = _publish(window, view)
    tree = archive.archive_tree
    tree.resize(800, 400)
    selection = tree.selectionModel()
    tree.setCurrentIndex(bridge.model.index(0, 0))
    for row in (0, 1):
        selection.select(bridge.model.index(row, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
    selected_label = "Extract Selected"

    class Menu(QMenu):
        def exec(self, _position):
            menu_actions = {action.text(): action for action in self.actions()}
            assert {"Extract File...", "Extract Selected", "Extract Filtered"} <= menu_actions.keys()
            menu_actions[selected_label].trigger()

    monkeypatch.setattr(actions, "QMenu", Menu)
    # Right-click an already selected non-mesh row; retain the mixed selection.
    for label, kind, ids in (
        ("Extract Selected", ArchiveExportSelectionKind.ENTRY_IDS, (1, 2)),
        ("Extract Filtered", ArchiveExportSelectionKind.QUERY, ()),
        ("Extract File...", ArchiveExportSelectionKind.ENTRY_IDS, (2,)),
    ):
        selected_label = label
        view_widget = tree._flat_table if view is ArchiveViewMode.FLAT else tree
        position = view_widget.visualRect(bridge.model.index(1, 0)).center()
        assert tree.indexAt(position).row() == 1
        archive._show_archive_tree_context_menu(position)
        request = window.extract_requests[-1]
        assert request.selection_kind is kind
        assert request.entry_ids == ids
        if kind is ArchiveExportSelectionKind.QUERY:
            assert request.query_id == "filtered-files"
        assert len(tree.selectedItems()) == 2
        archive._finish_remote_archive_export()
    # A file outside the selection starts a new selection, as a normal context menu does.
    selected_label = "Extract Selected"
    position = view_widget.visualRect(bridge.model.index(2, 0)).center()
    archive._show_archive_tree_context_menu(position)
    assert window.extract_requests[-1].entry_ids == (3,)
    assert len(tree.selectedItems()) == 1


def test_selected_folder_keeps_extract_enabled_after_busy_update(window):
    archive = window.archive
    bridge = _publish(window, ArchiveViewMode.FOLDERS, folder=True)
    archive.archive_tree.setCurrentIndex(bridge.model.index(0, 0))
    window.set_busy(False)
    assert archive.archive_extract_selected_button.isEnabled()
    archive.archive_extract_selected_button.click()
    request, = window.extract_requests
    assert request.selection_kind is ArchiveExportSelectionKind.FOLDER
    assert request.folder_path == "object" and request.query_id == "filtered-files"
    assert not request.include_package_root
