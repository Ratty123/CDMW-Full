from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QModelIndex
from PySide6.QtWidgets import QApplication, QWidget

from cdmw.domain.archives.catalogue import (
    ArchiveChildNode,
    ArchiveChildrenResult,
    ArchiveDurableIdentity,
    ArchiveEntryDto,
    ArchiveEntryRole,
    ArchiveQueryHandle,
    ArchiveViewMode,
)
from cdmw.ui.archive_browser.actions import ArchiveBrowserActionMixin
from cdmw.ui.archive_browser.controller import ArchiveBrowserTreeControllerMixin
from cdmw.ui.archive_browser.model import ArchiveBrowserTreeView
from cdmw.ui.archive_browser.remote_model import RemoteArchiveBrowserModel, RemoteChildrenFetch


_APPLICATION: QApplication | None = None

# The tree view queues a deferred prefetch when a remote model is attached. Letting a
# window die with that timer pending fires it into a deleted C++ object, and the abort
# lands in whatever test runs next, not this one.
_WINDOWS: list[QWidget] = []


def _app() -> QApplication:
    global _APPLICATION
    _APPLICATION = QApplication.instance() or QApplication([])
    return _APPLICATION


def _drain_events() -> None:
    app = _app()
    for _ in range(5):
        app.processEvents()


class _FolderMenuWindow(ArchiveBrowserActionMixin, ArchiveBrowserTreeControllerMixin, QWidget):
    """The smallest host that can build the browser's folder context menu."""

    def __init__(self) -> None:
        super().__init__()
        self.archive_tree = ArchiveBrowserTreeView("", "", parent=self)
        self.archive_context_menu_selection_suppressed = False
        self.archive_filtered_entries = []
        self.status_messages: list[str] = []
        self.extract_calls = 0

    def set_status_message(self, message: str, *, error: bool = False) -> None:
        self.status_messages.append(message)

    def _schedule_archive_selection_state_update(self) -> None:
        return None

    def extract_selected_archive_entries(self) -> None:
        self.extract_calls += 1


def _entry(entry_id: int, path: str) -> ArchiveEntryDto:
    return ArchiveEntryDto(
        session_id="session-a",
        entry_id=entry_id,
        identity=ArchiveDurableIdentity(path, "0009/0.pamt", 0, entry_id * 64),
        path=path,
        source_pamt="C:/game/0009/0.pamt",
        paz_file="C:/game/0009/0.paz",
        paz_index=0,
        offset=entry_id * 64,
        stored_size=64,
        original_size=64,
        flags=0,
        extension=".pac",
        package="0009/0.pamt",
        role=ArchiveEntryRole.MODEL,
        category="model_mesh_physics",
        is_previewable=True,
    )


def _window_with_folder_tree() -> _FolderMenuWindow:
    _app()
    window = _FolderMenuWindow()
    model = RemoteArchiveBrowserModel(parent=window)
    model.publish_query(
        ArchiveQueryHandle("session-a", "query-a", 1, 12),
        view_mode=ArchiveViewMode.FOLDERS,
        prime=False,
    )
    fetch = RemoteChildrenFetch("session-a", "query-a", 1, "root", None, None, 0, 512)
    assert model.accept_children(
        fetch,
        ArchiveChildrenResult(
            "session-a",
            "query-a",
            (
                ArchiveChildNode("character/appearance", "appearance", True, 11),
                ArchiveChildNode("entry:9", "loose.pac", False, 1, _entry(9, "loose.pac")),
            ),
            False,
            offset=0,
            total_children=2,
            next_offset=None,
        ),
    )
    window.archive_tree.use_remote_model(model)
    _WINDOWS.append(window)
    _drain_events()
    return window


def test_right_clicking_a_folder_offers_export_folder_and_runs_the_folder_extract() -> None:
    window = _window_with_folder_tree()
    model = window.archive_tree.archive_model()
    folder_node = model.node_from_index(model.index(0, 0, QModelIndex()))
    assert folder_node is not None and folder_node.kind == "folder"

    menu = window._build_archive_folder_context_menu(folder_node)

    assert menu is not None
    labels = [action.text() for action in menu.actions() if not action.isSeparator() and action.text()]
    assert "Export Folder..." in labels

    export_action = next(action for action in menu.actions() if action.text() == "Export Folder...")
    export_action.trigger()
    assert window.extract_calls == 1
    # Right-clicking makes the folder the selection, which is what the export reads.
    assert window.archive_tree.currentIndex().isValid()


def test_the_folder_menu_reports_the_entry_path_not_a_package_path() -> None:
    window = _window_with_folder_tree()
    model = window.archive_tree.archive_model()
    folder_node = model.node_from_index(model.index(0, 0, QModelIndex()))

    assert window._archive_tree_folder_path(folder_node) == "character/appearance"


def test_the_file_context_menu_path_is_unchanged_for_file_nodes() -> None:
    window = _window_with_folder_tree()
    model = window.archive_tree.archive_model()
    file_node = model.node_from_index(model.index(1, 0, QModelIndex()))
    assert file_node is not None and file_node.kind == "file"

    # A file node carries no folder path, so the folder menu declines to build.
    assert window._build_archive_folder_context_menu(file_node) is None
