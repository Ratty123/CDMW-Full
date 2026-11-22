"""Browse Archives > Files DMM adds: files a DMM mod serves that the game does not have (experimental).

The archive catalogue lists the game's own files only. DMM 5 serves its mods at run
time, and a mod can add files the game never had, such as a new mesh or texture.
This list reads DMM's manifest, asks the catalogue which of the served paths it
has, and lists the rest. They open from CDMW's own copy; DMM's files are only read.
"""

from __future__ import annotations

import shutil
import threading
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QVBoxLayout, QWidget,
)

from cdmw.domain.archives.constants import ARCHIVE_MESH_EXTENSIONS
from cdmw.services.dmm_runtime_mount import (
    KEEP_GAME_EXTENSIONS, DmmServedFile, current_overlay, normalized_game_path,
)

DMM_ADDED_FILES_EMPTY = "Press Find to list the files DMM's mounted mods add to the game."


@dataclass(frozen=True, slots=True)
class DmmAddedFile:
    game_path: str
    mod: str
    source: Path


class _OpenRelay(QObject):
    """Brings a prepared open back to the UI thread."""

    done = Signal(int, object, object)


def _prepare_open(game_root: str, row: DmmAddedFile):
    """CDMW's copy of ``row`` as an archive entry, with the files DMM serves that it names.

    Read off the UI thread: it copies DMM's file and reads it for names.
    """
    from cdmw.services.dmm_runtime_mount import added_dependency_entries, added_entry
    from cdmw.ui.archive_browser.workflow_dependencies import ArchiveWorkflowDependencyContext

    overlay = current_overlay()
    mount, error = overlay.mount(game_root)
    served = overlay.served_file(game_root, row.game_path)
    prepared = overlay.prepare(game_root, row.game_path) if served is not None else None
    if mount is None or served is None or prepared is None:
        raise ValueError(error or f"DMM no longer serves {row.game_path}. Press Find again.")
    entry = added_entry(mount, served, prepared)
    entries = (entry, *added_dependency_entries(game_root, (entry,), overlay=overlay))
    paths: dict[str, list] = {}
    basenames: dict[str, list] = {}
    for item in entries:
        paths.setdefault(normalized_game_path(item.path), []).append(item)
        basenames.setdefault(item.basename.casefold(), []).append(item)
    context = ArchiveWorkflowDependencyContext(
        entry, entries,
        MappingProxyType({key: tuple(value) for key, value in paths.items()}),
        MappingProxyType({key: tuple(value) for key, value in basenames.items()}),
        remote=True,
    )
    return entry, context


def added_files(served: dict[str, DmmServedFile], found_paths: set[str]) -> list[DmmAddedFile]:
    """The served files whose game path the catalogue does not have, by game path."""

    rows = [DmmAddedFile(item.game_path, item.mod, item.source) for key, item in served.items()
            if key not in found_paths and PurePosixPath(key).suffix not in KEEP_GAME_EXTENSIONS]
    return sorted(rows, key=lambda row: row.game_path.casefold())


class DmmAddedFilesGroup(QGroupBox):
    def __init__(self, archive, parent=None):
        super().__init__(parent)
        self.setTitle("Files DMM adds (experimental)")
        self.setObjectName("ArchiveDmmAddedFiles")
        self.setToolTip("Files a mod mounted in DMM adds that the game does not have. Browse Archives lists "
                        "the game's files only. CDMW opens and copies its own copy; DMM's files are only read.")
        self._archive = archive
        #: The lookup helper finds the catalogue through ``owner.archive``.
        self.archive = archive
        self._lookup = None
        self._open_generation = 0
        self._open_relay = _OpenRelay(self)
        self._open_relay.done.connect(self._open_prepared)
        self.rows: list[DmmAddedFile] = []
        layout = QVBoxLayout(self)
        self.status_label = QLabel(DMM_ADDED_FILES_EMPTY)
        self.status_label.setObjectName("HintLabel")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.file_list = QListWidget()
        self.file_list.setObjectName("ArchiveDmmAddedFilesList")
        self.file_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.file_list.setMaximumHeight(160)
        self.file_list.itemDoubleClicked.connect(lambda _item: self.open_selected())
        self.file_list.itemSelectionChanged.connect(self._sync_buttons)
        layout.addWidget(self.file_list)
        buttons = QHBoxLayout()
        self.find_button = QPushButton("Find")
        self.find_button.setToolTip("Read DMM's list again and ask the catalogue which files the game lacks.")
        self.open_button = QPushButton("Open in Mesh Editor")
        self.copy_button = QPushButton("Copy to Folder...")
        self.show_button = QPushButton("Show DMM's File")
        for button in (self.find_button, self.open_button, self.copy_button, self.show_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.find_button.clicked.connect(self.find)
        self.open_button.clicked.connect(self.open_selected)
        self.copy_button.clicked.connect(self.copy_selected_dialog)
        self.show_button.clicked.connect(self.show_selected)
        self._sync_buttons()
        overlay = current_overlay()
        overlay.add_listener(self._overlay_changed)
        self.destroyed.connect(lambda _object=None, overlay=overlay, listener=self._overlay_changed:
                               overlay.remove_listener(listener))

    def _overlay_changed(self) -> None:
        """Turned on or off, or Check again: previews kept from before show other files."""

        clear = getattr(self._archive, "_clear_archive_preview_cache", None)
        if callable(clear):
            clear()
        clear_family = getattr(self._archive, "_clear_archive_asset_family_cache", None)
        if callable(clear_family):
            clear_family()
        if self._lookup is None:
            self._show_rows([], DMM_ADDED_FILES_EMPTY)

    # ------------------------------------------------------------ finding

    def _game_root(self) -> str:
        bridge = getattr(self._archive, "archive_remote_bridge", None)
        session = getattr(bridge, "current_session", None)
        return str(getattr(session, "package_root", "") or "")

    def find(self) -> bool:
        """Start listing; False with the reason in the status line when it cannot start."""

        from cdmw.domain.archives.catalogue import ArchiveLookupKind
        from cdmw.ui.archive_browser.remote_entry_lookup import lookup_requests, start_live_catalogue_lookup

        overlay = current_overlay()
        game_root = self._game_root()
        if not game_root:
            return self._show_rows([], "Load the game archives first.")
        if not overlay.enabled:
            return self._show_rows([], "Showing DMM's files is turned off in Settings > Paths.")
        mount, error = overlay.mount(game_root)
        if error or mount is None or not mount.serving:
            return self._show_rows([], error or (mount.problem if mount is not None else
                                                 "DMM has nothing mounted at run time."))
        served = {key: item for key, item in mount.files.items() if PurePosixPath(key).suffix not in KEEP_GAME_EXTENSIONS}
        if not served:
            return self._show_rows([], "DMM's mounted mods change only game tables.")
        bridge = getattr(self._archive, "archive_remote_bridge", None)
        session = getattr(bridge, "current_session", None)
        requests = lookup_requests(session.session_id, ArchiveLookupKind.EXACT_PATHS, [item.game_path for item in served.values()])
        self.status_label.setText(f"Checking {len(served):,} file(s) DMM serves against the game's catalogue...")
        self.find_button.setEnabled(False)

        def done(outcome) -> None:
            found = {normalized_game_path(entry.path) for entry in outcome.entries}
            self._show_rows(added_files(served, found), "")

        def failed(message: str) -> None:
            self._show_rows([], message)

        lookup = start_live_catalogue_lookup(self, "_lookup", requests, on_done=done, on_error=failed)
        return lookup is not None

    def _show_rows(self, rows: list[DmmAddedFile], message: str) -> bool:
        self.rows = rows
        self.file_list.clear()
        for row in rows:
            item = QListWidgetItem(f"{PurePosixPath(row.game_path).name}  ({row.mod})")
            item.setToolTip(row.game_path)
            item.setData(Qt.ItemDataRole.UserRole, row.game_path)
            self.file_list.addItem(item)
        if not message:
            message = (f"{len(rows):,} file(s) the game does not have, from DMM's mounted mods." if rows
                       else "DMM's mounted mods add no files the game does not have.")
        self.status_label.setText(message)
        self.find_button.setEnabled(True)
        self._sync_buttons()
        return bool(rows) or not message

    # ------------------------------------------------------------ actions

    def selected_rows(self) -> list[DmmAddedFile]:
        chosen = {item.data(Qt.ItemDataRole.UserRole) for item in self.file_list.selectedItems()}
        return [row for row in self.rows if row.game_path in chosen]

    def select_paths(self, paths) -> list[str]:
        wanted = {normalized_game_path(path) for path in paths}
        self.file_list.clearSelection()
        chosen = []
        for index in range(self.file_list.count()):
            item = self.file_list.item(index)
            if normalized_game_path(item.data(Qt.ItemDataRole.UserRole)) in wanted:
                item.setSelected(True)
                chosen.append(item.data(Qt.ItemDataRole.UserRole))
        return chosen

    def _sync_buttons(self) -> None:
        rows = self.selected_rows()
        self.open_button.setEnabled(len(rows) == 1 and PurePosixPath(rows[0].game_path).suffix.casefold()
                                    in ARCHIVE_MESH_EXTENSIONS)
        self.copy_button.setEnabled(bool(rows))
        self.show_button.setEnabled(len(rows) == 1)

    def _prepared(self, row: DmmAddedFile):
        prepared = current_overlay().prepare(self._game_root(), row.game_path)
        if prepared is None:
            raise ValueError(f"DMM no longer serves {row.game_path}. Press Find again.")
        return prepared

    def _show_dmm_status(self, message: str, *, error: bool = False) -> None:
        """The status line, and the window's, which stays visible when the Actions panel closes."""

        self.status_label.setText(message)
        shell = getattr(self._archive, "shell", None)
        status = getattr(shell, "set_status_message", None)
        if callable(status):
            try:
                status(message, error=error)
            except TypeError:
                status(message)

    def open_selected(self) -> str:
        """Open the selected mesh as an archive mesh, like Edited results; the game path when started.

        The copy and the search for the files it names run on a worker. The open
        then asks about an unfinished edit, or opens beside it, as every archive
        open does.
        """
        rows = self.selected_rows()
        if len(rows) != 1 or PurePosixPath(rows[0].game_path).suffix.casefold() not in ARCHIVE_MESH_EXTENSIONS:
            return ""
        row = rows[0]
        shell = getattr(self._archive, "shell", None)
        if getattr(shell, "mesh_editor_tab", None) is None or not callable(
                getattr(shell, "_prepare_mesh_editor_archive_launch", None)):
            self._show_dmm_status("The Mesh Editor is unavailable.", error=True)
            return ""
        from cdmw.ui.archive_browser.command_strip import hide_enclosing_popup

        hide_enclosing_popup(self)
        game_root = self._game_root()
        self._open_generation += 1
        generation, relay = self._open_generation, self._open_relay

        def run() -> None:
            try:
                outcome: object = _prepare_open(game_root, row)
            except (OSError, ValueError, RuntimeError) as exc:
                outcome = exc
            try:
                relay.done.emit(generation, row, outcome)
            except RuntimeError:
                pass  # the list was deleted meanwhile

        threading.Thread(target=run, name="dmm-added-file-open", daemon=True).start()
        self._show_dmm_status(f"Opening {row.game_path} from DMM's {row.mod} in the Mesh Editor.")
        return row.game_path

    def _open_prepared(self, generation: int, row: object, outcome: object) -> None:
        if generation != self._open_generation:
            return
        if isinstance(outcome, BaseException):
            self._show_dmm_status(str(outcome), error=True)
            return
        entry, context = outcome
        shell = getattr(self._archive, "shell", None)
        tab = getattr(shell, "mesh_editor_tab", None)
        try:
            blocked = getattr(shell, "_mesh_editor_open_blocked", None)
            if callable(blocked) and blocked():
                return
            # Finish, Discard or Keep editing for an unfinished edit; another file opens beside it.
            if not shell._prepare_mesh_editor_archive_launch(entry):
                return
            tab.open_archive_session(entry, archive_dependencies=context)
            activate = getattr(shell, "_activate_tool_widget", None)
            if callable(activate):
                activate(tab)
        except (AttributeError, OSError, ValueError, RuntimeError) as exc:
            self._show_dmm_status(str(exc), error=True)

    def copy_selected(self, folder: Path | str) -> list[str]:
        """Copy the selected files into ``folder`` under their game paths; never into the game folder."""

        from cdmw.domain.output_paths import check_output_path

        target_root = check_output_path(folder, game_folder=self._game_root() or None, allow_existing=True)
        written = []
        for row in self.selected_rows():
            prepared = self._prepared(row)
            target = target_root.joinpath(*PurePosixPath(row.game_path).parts)
            if not target.resolve().is_relative_to(target_root.resolve()):
                raise ValueError(f"{row.game_path} is not a path inside the folder.")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(prepared.path, target)
            written.append(str(target))
        self._show_dmm_status(f"Copied {len(written):,} file(s) to {target_root}.")
        return written

    def copy_selected_dialog(self) -> None:
        from cdmw.ui.archive_browser.command_strip import hide_enclosing_popup

        # The folder dialog would close the Actions panel and its status line with it.
        hide_enclosing_popup(self)
        parent = self._archive if isinstance(self._archive, QWidget) else self.window()
        folder = QFileDialog.getExistingDirectory(parent, "Copy DMM's files to a folder")
        if not folder:
            return
        try:
            self.copy_selected(folder)
        except (OSError, ValueError) as exc:
            self._show_dmm_status(str(exc), error=True)

    def show_selected(self) -> None:
        rows = self.selected_rows()
        if len(rows) == 1:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(rows[0].source.parent)))
