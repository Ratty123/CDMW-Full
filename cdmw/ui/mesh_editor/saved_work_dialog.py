"""Saved Drafts and Built Mods: list earlier Mesh Editor work and continue it."""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.services.mesh_saved_work_service import (
    STATUS_CHECKING,
    STATUS_GAME_NOT_LOADED,
    STATUS_GAME_UPDATED,
    STATUS_MATCHES,
    STATUS_MOD_MISSING,
    STATUS_ORIGINAL_UNKNOWN,
    STATUS_SOURCE_MISSING,
    SavedWorkRow,
    add_built_mod_folder,
    delete_saved_draft,
    list_saved_work,
    remove_built_mod_from_list,
    rename_saved_work,
    saved_work_status,
)
from cdmw.ui.mesh_editor.saved_work_sources import normalized_archive_path


def saved_work_status_text(code: str) -> str:
    if code == STATUS_MATCHES:
        return "Matches the current game files"
    if code == STATUS_GAME_UPDATED:
        return "Game updated since this was made"
    if code == STATUS_SOURCE_MISSING:
        return "Source file not found"
    if code == STATUS_MOD_MISSING:
        return "Mod folder not found"
    if code == STATUS_ORIGINAL_UNKNOWN:
        return "Original game version unknown"
    if code == STATUS_GAME_NOT_LOADED:
        return "Load the game in Archive Browser to check"
    return "Checking the game files..."


def saved_work_kind_text(row: SavedWorkRow) -> str:
    if not row.is_built_mod:
        return "Saved draft"
    if row.has_draft:
        return "Built mod"
    return "Built mod (no draft)"


def _row_key(row: SavedWorkRow) -> str:
    return f"{row.kind}:{row.row_id}"


class _Relay(QObject):
    done = Signal(int, object, object, str)


class MeshSavedWorkDialog(QDialog):
    """Modeless list of saved drafts and built mods with their actions."""

    continue_requested = Signal(object)

    def __init__(
        self,
        parent: QWidget | None,
        *,
        draft_root: Path,
        source_resolver: object | None = None,
        active_draft_manifest: Callable[[], Path | None] | None = None,
        path_filter: str = "",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("MeshSavedWorkDialog")
        self.setWindowTitle("Saved Drafts and Built Mods")
        self.resize(980, 460)
        self.draft_root = Path(draft_root)
        self.source_resolver = source_resolver
        self.active_draft_manifest = active_draft_manifest or (lambda: None)
        self._rows: tuple[SavedWorkRow, ...] = ()
        self._visible_rows: tuple[SavedWorkRow, ...] = ()
        self._statuses: dict[str, str] = {}
        self._token = 0
        self._relay = _Relay(self)
        self._relay.done.connect(self._handle_background_done)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Mesh Editor saves a draft each time you choose Finish Edit Mesh, and Build Mod keeps "
            "the editing state with the mod. Select a row and choose Continue Editing to pick up where you left off.",
            self,
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        filter_row = QHBoxLayout()
        self.filter_edit = QLineEdit(path_filter, self)
        self.filter_edit.setObjectName("MeshSavedWorkFilter")
        self.filter_edit.setPlaceholderText("Filter by name or game file")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(lambda _text: self._populate())
        filter_row.addWidget(self.filter_edit, 1)
        layout.addLayout(filter_row)

        self.table = QTableWidget(0, 6, self)
        self.table.setObjectName("MeshSavedWorkTable")
        self.table.setHorizontalHeaderLabels(["Saved on", "File name", "Game file", "Draft or mod", "Edit pass", "Status"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._sync_buttons)
        self.table.itemDoubleClicked.connect(lambda _item: self._continue_selected())
        layout.addWidget(self.table, 1)

        self.empty_label = QLabel("", self)
        self.empty_label.setObjectName("MeshSavedWorkEmpty")
        self.empty_label.setWordWrap(True)
        layout.addWidget(self.empty_label)
        self.detail_label = QLabel("", self)
        self.detail_label.setObjectName("MeshSavedWorkDetail")
        self.detail_label.setWordWrap(True)
        self.detail_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.detail_label)

        buttons = QHBoxLayout()
        self.continue_button = QPushButton("Continue Editing", self)
        self.continue_button.setObjectName("MeshSavedWorkContinue")
        self.continue_button.setDefault(True)
        self.open_folder_button = QPushButton("Open Folder", self)
        self.open_folder_button.setObjectName("MeshSavedWorkOpenFolder")
        self.rename_button = QPushButton("Rename...", self)
        self.rename_button.setObjectName("MeshSavedWorkRename")
        self.delete_button = QPushButton("Delete...", self)
        self.delete_button.setObjectName("MeshSavedWorkDelete")
        self.add_folder_button = QPushButton("Add Mod Folder...", self)
        self.add_folder_button.setObjectName("MeshSavedWorkAddFolder")
        self.add_folder_button.setToolTip(
            "List a mod folder built before saved drafts existed, or by someone else. "
            "Continue Editing then opens its finished mesh as a new edit pass."
        )
        self.refresh_button = QPushButton("Refresh", self)
        self.refresh_button.setObjectName("MeshSavedWorkRefresh")
        close_button = QPushButton("Close", self)
        for button in (self.continue_button, self.open_folder_button, self.rename_button, self.delete_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        for button in (self.add_folder_button, self.refresh_button, close_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.continue_button.clicked.connect(self._continue_selected)
        self.open_folder_button.clicked.connect(self._open_selected_folder)
        self.rename_button.clicked.connect(self._rename_selected)
        self.delete_button.clicked.connect(self._delete_selected)
        self.add_folder_button.clicked.connect(self._add_mod_folder)
        self.refresh_button.clicked.connect(self.refresh)
        close_button.clicked.connect(self.close)
        self._sync_buttons()

    # ------------------------------------------------------------ loading

    def set_path_filter(self, text: str) -> None:
        self.filter_edit.setText(str(text or ""))

    def rows(self) -> tuple[SavedWorkRow, ...]:
        return self._visible_rows

    def status_code(self, row: SavedWorkRow) -> str:
        return self._statuses.get(_row_key(row), STATUS_CHECKING)

    def _run(self, task: Callable[[], object], on_done: Callable[[int, object, str], None]) -> None:
        """Run file work off the UI thread; ``on_done`` gets the token, result and error."""
        token, relay = self._token, self._relay

        def run() -> None:
            try:
                result, error = task(), ""
            except Exception as exc:
                result, error = None, f"{type(exc).__name__}: {exc}"
            try:
                relay.done.emit(token, on_done, result, error)
            except RuntimeError:
                pass  # The dialog closed while this ran.

        threading.Thread(target=run, name="mesh-saved-work", daemon=True).start()

    def refresh(self) -> None:
        self._token += 1
        self._statuses = {}
        cancel = getattr(self.source_resolver, "cancel", None)
        if callable(cancel):
            cancel()
        self.empty_label.setText("Reading saved work...")
        root = self.draft_root
        self._run(lambda: list_saved_work(root), self._list_done)

    def _handle_background_done(self, token: int, on_done: object, result: object, error: str) -> None:
        if callable(on_done):
            on_done(int(token), result, error)

    def _action_done(self, _token: int, _result: object, error: str) -> None:
        if error:
            QMessageBox.warning(self, "Saved Drafts and Built Mods", f"That did not work: {error}")
        self.refresh()

    def _list_done(self, token: int, result: object, error: str) -> None:
        if token != self._token:
            return
        if error:
            self._rows = ()
            self._populate()
            self.empty_label.setText(f"Saved work could not be read: {error}")
            return
        self._rows = tuple(result or ())
        self._populate()
        self._check_statuses()

    def _status_done(self, token: int, result: object, _error: str) -> None:
        if token == self._token and isinstance(result, dict):
            self._statuses.update(result)
            self._populate()

    def _check_statuses(self) -> None:
        rows = self._rows
        if not rows:
            return
        resolve = getattr(self.source_resolver, "resolve", None)
        if not callable(resolve):
            self._sources_resolved(self._token, None)
            return
        token = self._token
        resolve([row.source_archive_path for row in rows],
                lambda sources, target=token: self._sources_resolved(target, sources))

    def _sources_resolved(self, token: int, sources: object) -> None:
        if int(token) != self._token:
            return
        rows = self._rows
        if sources is None:
            for row in rows:
                missing_mod = saved_work_status(row, found=True) == STATUS_MOD_MISSING
                self._statuses[_row_key(row)] = STATUS_MOD_MISSING if missing_mod else STATUS_GAME_NOT_LOADED
            self._populate()
            return
        live = dict(sources)

        def compute() -> dict[str, str]:
            from cdmw.services.archive_read_service import read_archive_entry_data

            hashes: dict[object, str] = {}
            statuses: dict[str, str] = {}
            for row in rows:
                entry = live.get(normalized_archive_path(row.source_archive_path))
                current = ""
                if entry is not None:
                    key = (entry.identity, int(entry.comp_size), int(entry.orig_size), str(entry.prepared_path or ""))
                    if key not in hashes:
                        try:
                            hashes[key] = hashlib.sha256(read_archive_entry_data(entry)[0]).hexdigest()
                        except Exception:
                            hashes[key] = ""
                    current = hashes[key]
                statuses[_row_key(row)] = saved_work_status(row, found=entry is not None, current_sha256=current)
            return statuses

        self._run(compute, self._status_done)

    def _populate(self) -> None:
        selected = self._selected_row()
        wanted = self.filter_edit.text().strip().casefold()
        rows = tuple(row for row in self._rows if not wanted
                     or wanted in row.display_name.casefold()
                     or wanted in row.source_archive_path.replace("\\", "/").casefold())
        self._visible_rows = rows
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            saved = time.strftime("%Y-%m-%d %H:%M", time.localtime(row.saved_at)) if row.saved_at else ""
            edit_pass = str(row.edit_pass) if row.edit_pass > 0 else "Unknown"
            cells = (
                QTableWidgetItem(saved),
                QTableWidgetItem(row.display_name),
                QTableWidgetItem(row.source_archive_path),
                QTableWidgetItem(saved_work_kind_text(row)),
                QTableWidgetItem(edit_pass),
                QTableWidgetItem(saved_work_status_text(self.status_code(row))),
            )
            cells[2].setToolTip(row.source_package)
            for column, item in enumerate(cells):
                self.table.setItem(index, column, item)
        if self._rows and not rows:
            self.empty_label.setText("No saved work matches this filter.")
        elif not self._rows:
            self.empty_label.setText(
                "No saved work yet. Open a mesh from Archive Browser, finish an edit, and it is saved here."
            )
        else:
            self.empty_label.setText("")
        if selected is not None:
            for index, row in enumerate(rows):
                if _row_key(row) == _row_key(selected):
                    self.table.selectRow(index)
                    break
        self._sync_buttons()

    # ------------------------------------------------------------ actions

    def _selected_row(self) -> SavedWorkRow | None:
        indexes = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not indexes:
            return None
        index = indexes[0].row()
        return self._visible_rows[index] if 0 <= index < len(self._visible_rows) else None

    def _row_is_open(self, row: SavedWorkRow) -> bool:
        try:
            active = self.active_draft_manifest()
        except RuntimeError:
            active = None
        return bool(active is not None and row.manifest_path is not None
                    and Path(active).resolve() == Path(row.manifest_path).resolve())

    def _sync_buttons(self) -> None:
        row = self._selected_row()
        has_row = row is not None
        for button in (self.continue_button, self.open_folder_button, self.rename_button, self.delete_button):
            button.setEnabled(has_row)
        if row is not None and row.is_built_mod:
            self.delete_button.setText("Remove from List...")
            self.delete_button.setToolTip(
                "Remove this mod from the list. The mod folder and its files are kept."
            )
        else:
            self.delete_button.setText("Delete...")
            self.delete_button.setToolTip("Delete this draft from your computer.")
        if row is not None and not row.is_built_mod and self._row_is_open(row):
            self.delete_button.setEnabled(False)
            self.delete_button.setToolTip("This draft is open in Mesh Editor. Close it first.")
        if row is not None:
            self.open_folder_button.setEnabled(row.folder.is_dir())
            self.detail_label.setText(f"Folder: {row.folder}")
        else:
            self.detail_label.setText("")

    def _continue_selected(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        self.continue_requested.emit(row)

    def _open_selected_folder(self) -> None:
        row = self._selected_row()
        if row is not None and row.folder.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(row.folder)))

    def _rename_selected(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        name, accepted = QInputDialog.getText(
            self, "Rename", "Name shown in this list (folders keep their names):", text=row.display_name,
        )
        if not accepted or not str(name or "").strip():
            return
        root = self.draft_root
        self._run(lambda: rename_saved_work(root, row, name), self._action_done)

    def _delete_selected(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        root = self.draft_root
        if row.is_built_mod:
            answer = QMessageBox.question(
                self,
                "Remove from List",
                f"Remove {row.display_name} from this list?\n\n"
                f"The mod folder is kept:\n{row.folder}\n\n"
                "Its saved editing state is removed from CDMW. Use Open Folder if you want to delete the mod's files yourself.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._run(lambda: remove_built_mod_from_list(root, row), self._action_done)
            return
        if self._row_is_open(row):
            return
        answer = QMessageBox.question(
            self,
            "Delete Draft",
            f"Delete the draft {row.display_name}?\n\n"
            "Its saved editing state is removed from this computer. Built mods are not affected.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._run(lambda: delete_saved_draft(root, row), self._action_done)

    def _add_mod_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add a Mod Folder", "")
        if not folder:
            return
        root = self.draft_root
        self._run(lambda: add_built_mod_folder(root, folder), self._action_done)


__all__ = ["MeshSavedWorkDialog", "saved_work_kind_text", "saved_work_status_text"]
