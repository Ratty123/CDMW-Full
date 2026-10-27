"""Drafts & Mods: a tool page for saved Mesh Editor drafts, built mods and projects."""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
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
    SavedWorkProject,
    SavedWorkRow,
    add_built_mod_folder,
    assign_project,
    create_project,
    delete_project,
    delete_saved_draft,
    duplicate_saved_draft,
    list_projects,
    list_saved_work,
    remove_built_mod_from_list,
    rename_project,
    saved_work_status,
    update_saved_work_details,
)
from cdmw.ui.mesh_editor.saved_work_sources import normalized_archive_path

ALL_WORK = "\x00all"
NO_PROJECT = ""
_ROW_KEY_ROLE = Qt.ItemDataRole.UserRole
_SORT_ROLE = Qt.ItemDataRole.UserRole + 1


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


class _SortItem(QTableWidgetItem):
    """A cell that sorts by its stored key rather than its display text."""

    def __lt__(self, other: QTableWidgetItem) -> bool:
        mine, theirs = self.data(_SORT_ROLE), other.data(_SORT_ROLE)
        if mine is None or theirs is None or type(mine) is not type(theirs):
            return super().__lt__(other)
        return mine < theirs


class _Relay(QObject):
    done = Signal(int, object, object, str)


class SavedWorkPage(QWidget):
    """Every saved draft and built mod, grouped into the user's projects."""

    continue_requested = Signal(object)
    status_message_requested = Signal(str, bool)

    def __init__(
        self,
        *,
        draft_root: Path,
        source_resolver: object | None = None,
        active_draft_manifest: Callable[[], Path | None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("SavedWorkPage")
        self.draft_root = Path(draft_root)
        self.source_resolver = source_resolver
        self.active_draft_manifest = active_draft_manifest or (lambda: None)
        self._rows: tuple[SavedWorkRow, ...] = ()
        self._projects: tuple[SavedWorkProject, ...] = ()
        self._visible_rows: tuple[SavedWorkRow, ...] = ()
        self._statuses: dict[str, str] = {}
        self._hash_cache: dict[object, str] = {}
        self._token = 0
        self._selected_project = ALL_WORK
        self._project_keys: list[str] = [ALL_WORK, NO_PROJECT]
        self._detail_key = ""
        self._relay = _Relay(self)
        self._relay.done.connect(self._handle_background_done)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        title = QLabel("Drafts & Mods", self)
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        intro = QLabel(
            "Mesh Editor saves a draft each time you choose Finish Edit Mesh, and Build Mod keeps "
            "the editing state with the mod. Name your work, group it into projects, and choose "
            "Continue Editing to pick up where you left off.",
            self,
        )
        intro.setObjectName("HintLabel")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        toolbar = QHBoxLayout()
        self.filter_edit = QLineEdit(self)
        self.filter_edit.setObjectName("SavedWorkFilter")
        self.filter_edit.setPlaceholderText("Filter by name, game file or notes")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(lambda _text: self._populate())
        toolbar.addWidget(self.filter_edit, 1)
        self.add_folder_button = QPushButton("Add Mod Folder...", self)
        self.add_folder_button.setObjectName("SavedWorkAddFolder")
        self.add_folder_button.setToolTip(
            "List a mod folder built before saved drafts existed, or by someone else. "
            "Continue Editing then opens its finished mesh as a new edit pass."
        )
        self.refresh_button = QPushButton("Refresh", self)
        self.refresh_button.setObjectName("SavedWorkRefresh")
        toolbar.addWidget(self.add_folder_button)
        toolbar.addWidget(self.refresh_button)
        layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)
        splitter.addWidget(self._build_projects_panel(splitter))
        splitter.addWidget(self._build_table_panel(splitter))
        splitter.addWidget(self._build_details_panel(splitter))
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([210, 760, 320])

        self.add_folder_button.clicked.connect(self._add_mod_folder)
        self.refresh_button.clicked.connect(self.refresh)
        self._sync_buttons()

    # ------------------------------------------------------------ layout

    def _build_projects_panel(self, parent: QWidget) -> QWidget:
        panel = QWidget(parent)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 6, 0)
        heading = QLabel("Projects", panel)
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)
        self.project_list = QListWidget(panel)
        self.project_list.setObjectName("SavedWorkProjects")
        self.project_list.setProperty("_i18n_translate_items", True)
        self.project_list.currentItemChanged.connect(self._project_selected)
        layout.addWidget(self.project_list, 1)
        self.new_project_button = QPushButton("New Project...", panel)
        self.new_project_button.setObjectName("SavedWorkNewProject")
        self.rename_project_button = QPushButton("Rename Project...", panel)
        self.rename_project_button.setObjectName("SavedWorkRenameProject")
        self.delete_project_button = QPushButton("Delete Project...", panel)
        self.delete_project_button.setObjectName("SavedWorkDeleteProject")
        self.delete_project_button.setToolTip(
            "Delete this project. Its drafts and built mods are kept and move to No project."
        )
        for button in (self.new_project_button, self.rename_project_button, self.delete_project_button):
            layout.addWidget(button)
        self.new_project_button.clicked.connect(self._new_project)
        self.rename_project_button.clicked.connect(self._rename_project)
        self.delete_project_button.clicked.connect(self._delete_project)
        return panel

    def _build_table_panel(self, parent: QWidget) -> QWidget:
        panel = QWidget(parent)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 0, 6, 0)
        self.table = QTableWidget(0, 7, panel)
        self.table.setObjectName("SavedWorkTable")
        self.table.setHorizontalHeaderLabels(
            ["Saved on", "File name", "Game file", "Draft or mod", "Edit pass", "Status", "Project"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.SortOrder.DescendingOrder)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.itemDoubleClicked.connect(lambda _item: self._continue_selected())
        layout.addWidget(self.table, 1)
        self.empty_label = QLabel("", panel)
        self.empty_label.setObjectName("SavedWorkEmpty")
        self.empty_label.setWordWrap(True)
        layout.addWidget(self.empty_label)
        return panel

    def _build_details_panel(self, parent: QWidget) -> QWidget:
        panel = QGroupBox("Details", parent)
        panel.setObjectName("SavedWorkDetails")
        layout = QVBoxLayout(panel)
        form = QFormLayout()
        self.name_edit = QLineEdit(panel)
        self.name_edit.setObjectName("SavedWorkName")
        self.project_combo = QComboBox(panel)
        self.project_combo.setObjectName("SavedWorkProject")
        self.notes_edit = QPlainTextEdit(panel)
        self.notes_edit.setObjectName("SavedWorkNotes")
        self.notes_edit.setPlaceholderText("Notes for yourself, such as what this version changes")
        self.notes_edit.setMaximumHeight(120)
        form.addRow("Name in list", self.name_edit)
        form.addRow("Project", self.project_combo)
        form.addRow("Your notes", self.notes_edit)
        layout.addLayout(form)
        self.save_details_button = QPushButton("Save Changes", panel)
        self.save_details_button.setObjectName("SavedWorkSaveDetails")
        self.save_details_button.setToolTip("Save the name, project and notes. Folders keep their names.")
        layout.addWidget(self.save_details_button)
        facts = QFormLayout()
        self.game_file_value = QLabel("", panel)
        self.kind_value = QLabel("", panel)
        self.edit_pass_value = QLabel("", panel)
        self.status_value = QLabel("", panel)
        self.folder_value = QLabel("", panel)
        for label in (self.game_file_value, self.folder_value):
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        facts.addRow("Game file", self.game_file_value)
        facts.addRow("Draft or mod", self.kind_value)
        facts.addRow("Edit pass", self.edit_pass_value)
        facts.addRow("Status", self.status_value)
        facts.addRow("Folder", self.folder_value)
        layout.addLayout(facts)
        layout.addStretch(1)
        self.continue_button = QPushButton("Continue Editing", panel)
        self.continue_button.setObjectName("SavedWorkContinue")
        self.open_folder_button = QPushButton("Open Folder", panel)
        self.open_folder_button.setObjectName("SavedWorkOpenFolder")
        self.duplicate_button = QPushButton("Duplicate...", panel)
        self.duplicate_button.setObjectName("SavedWorkDuplicate")
        self.duplicate_button.setToolTip("Copy this draft into a new one, to try a variation.")
        self.move_button = QPushButton("Move to Project...", panel)
        self.move_button.setObjectName("SavedWorkMove")
        self.move_button.setToolTip("Put every selected draft and mod into a project.")
        self.delete_button = QPushButton("Delete...", panel)
        self.delete_button.setObjectName("SavedWorkDelete")
        for button in (self.continue_button, self.open_folder_button, self.duplicate_button,
                       self.move_button, self.delete_button):
            layout.addWidget(button)
        self.save_details_button.clicked.connect(self._save_details)
        self.continue_button.clicked.connect(self._continue_selected)
        self.open_folder_button.clicked.connect(self._open_selected_folder)
        self.duplicate_button.clicked.connect(self._duplicate_selected)
        self.move_button.clicked.connect(self._move_selected)
        self.delete_button.clicked.connect(self._delete_selected)
        return panel

    # ------------------------------------------------------------ loading

    def set_path_filter(self, text: str) -> None:
        self.filter_edit.setText(str(text or ""))
        self._select_project(ALL_WORK)

    def rows(self) -> tuple[SavedWorkRow, ...]:
        return self._visible_rows

    def projects(self) -> tuple[SavedWorkProject, ...]:
        return self._projects

    def status_code(self, row: SavedWorkRow) -> str:
        return self._statuses.get(_row_key(row), STATUS_CHECKING)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.refresh()

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
                pass  # The page closed while this ran.

        threading.Thread(target=run, name="mesh-saved-work", daemon=True).start()

    def refresh(self) -> None:
        self._token += 1
        cancel = getattr(self.source_resolver, "cancel", None)
        if callable(cancel):
            cancel()
        if not self._rows:
            self.empty_label.setText("Reading saved work...")
        root = self.draft_root
        self._run(lambda: (list_saved_work(root), list_projects(root)), self._list_done)

    def _handle_background_done(self, token: int, on_done: object, result: object, error: str) -> None:
        if callable(on_done):
            on_done(int(token), result, error)

    def _action_done(self, _token: int, _result: object, error: str) -> None:
        if error:
            QMessageBox.warning(self, "Drafts & Mods", f"That did not work: {error}")
        self.refresh()

    def _list_done(self, token: int, result: object, error: str) -> None:
        if token != self._token:
            return
        if error:
            self._rows, self._projects = (), ()
            self._populate()
            self.empty_label.setText(f"Saved work could not be read: {error}")
            return
        rows, projects = result
        self._rows, self._projects = tuple(rows), tuple(projects)
        known = {project.project_id for project in self._projects}
        if self._selected_project not in (ALL_WORK, NO_PROJECT) and self._selected_project not in known:
            self._selected_project = ALL_WORK
        self._statuses = {key: code for key, code in self._statuses.items()
                          if any(_row_key(row) == key for row in self._rows)}
        self._populate_projects()
        self._populate()
        self._check_statuses()

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
        cache = self._hash_cache

        def compute() -> dict[str, str]:
            from cdmw.services.archive_read_service import read_archive_entry_data

            statuses: dict[str, str] = {}
            for row in rows:
                entry = live.get(normalized_archive_path(row.source_archive_path))
                current = ""
                if entry is not None:
                    key = (entry.identity, int(entry.comp_size), int(entry.orig_size), str(entry.prepared_path or ""))
                    if key not in cache:
                        try:
                            cache[key] = hashlib.sha256(read_archive_entry_data(entry)[0]).hexdigest()
                        except Exception:
                            cache[key] = ""
                    current = cache[key]
                statuses[_row_key(row)] = saved_work_status(row, found=entry is not None, current_sha256=current)
            return statuses

        self._run(compute, self._status_done)

    def _status_done(self, token: int, result: object, _error: str) -> None:
        if token == self._token and isinstance(result, dict):
            self._statuses.update(result)
            self._populate()

    # ------------------------------------------------------------ projects

    def _project_name(self, project_id: str) -> str:
        return next((project.name for project in self._projects if project.project_id == project_id), "")

    def _populate_projects(self) -> None:
        counts: dict[str, int] = {}
        for row in self._rows:
            key = row.project_id if self._project_name(row.project_id) else NO_PROJECT
            counts[key] = counts.get(key, 0) + 1
        self.project_list.blockSignals(True)
        self.project_list.clear()
        # The list rows follow these keys; the keys never become display text.
        self._project_keys = [ALL_WORK, NO_PROJECT, *(project.project_id for project in self._projects)]
        self.project_list.addItem(QListWidgetItem(f"All work ({len(self._rows)})"))
        self.project_list.addItem(QListWidgetItem(f"No project ({counts.get(NO_PROJECT, 0)})"))
        for project in self._projects:
            self.project_list.addItem(QListWidgetItem(f"{project.name} ({counts.get(project.project_id, 0)})"))
        if self._selected_project in self._project_keys:
            self.project_list.setCurrentRow(self._project_keys.index(self._selected_project))
        self.project_list.blockSignals(False)
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        self.project_combo.addItem("No project", NO_PROJECT)
        for project in self._projects:
            self.project_combo.addItem(project.name, project.project_id)
        self.project_combo.blockSignals(False)

    def _select_project(self, project_id: str) -> None:
        self._selected_project = project_id
        if project_id in self._project_keys:
            self.project_list.blockSignals(True)
            self.project_list.setCurrentRow(self._project_keys.index(project_id))
            self.project_list.blockSignals(False)
        self._populate()

    def _project_selected(self, _current: QListWidgetItem | None = None, _previous: object = None) -> None:
        row = self.project_list.currentRow()
        self._selected_project = self._project_keys[row] if 0 <= row < len(self._project_keys) else ALL_WORK
        self._populate()

    def _new_project(self) -> None:
        name, accepted = QInputDialog.getText(self, "New Project", "Project name:")
        if not accepted or not str(name or "").strip():
            return
        root = self.draft_root
        self._run(lambda: create_project(root, name), self._project_created)

    def _project_created(self, token: int, result: object, error: str) -> None:
        if isinstance(result, SavedWorkProject):
            self._selected_project = result.project_id
        self._action_done(token, result, error)

    def _rename_project(self) -> None:
        project_id = self._selected_project
        if project_id in (ALL_WORK, NO_PROJECT):
            return
        name, accepted = QInputDialog.getText(
            self, "Rename Project", "Project name:", text=self._project_name(project_id),
        )
        if not accepted or not str(name or "").strip():
            return
        root = self.draft_root
        self._run(lambda: rename_project(root, project_id, name), self._action_done)

    def _delete_project(self) -> None:
        project_id = self._selected_project
        if project_id in (ALL_WORK, NO_PROJECT):
            return
        answer = QMessageBox.question(
            self,
            "Delete Project",
            f"Delete the project {self._project_name(project_id)}?\n\n"
            "Its drafts and built mods are kept and move to No project.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            root = self.draft_root
            self._selected_project = ALL_WORK
            self._run(lambda: delete_project(root, project_id), self._action_done)

    # ------------------------------------------------------------ the table

    def _row_in_selected_project(self, row: SavedWorkRow) -> bool:
        if self._selected_project == ALL_WORK:
            return True
        if self._selected_project == NO_PROJECT:
            return not self._project_name(row.project_id)
        return row.project_id == self._selected_project

    def _populate(self) -> None:
        selected_keys = {_row_key(row) for row in self._selected_rows()}
        wanted = self.filter_edit.text().strip().casefold()
        rows = tuple(row for row in self._rows if self._row_in_selected_project(row) and (
            not wanted
            or wanted in row.display_name.casefold()
            or wanted in row.source_archive_path.replace("\\", "/").casefold()
            or wanted in row.notes.casefold()))
        self._visible_rows = rows
        self.table.blockSignals(True)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            saved = time.strftime("%Y-%m-%d %H:%M", time.localtime(row.saved_at)) if row.saved_at else ""
            edit_pass = str(row.edit_pass) if row.edit_pass > 0 else "Unknown"
            cells = (
                (_SortItem(saved), float(row.saved_at)),
                (_SortItem(row.display_name), row.display_name.casefold()),
                (_SortItem(row.source_archive_path), row.source_archive_path.casefold()),
                (_SortItem(saved_work_kind_text(row)), row.kind),
                (_SortItem(edit_pass), int(row.edit_pass)),
                (_SortItem(saved_work_status_text(self.status_code(row))), self.status_code(row)),
                (_SortItem(self._project_name(row.project_id)), self._project_name(row.project_id).casefold()),
            )
            for column, (item, key) in enumerate(cells):
                item.setData(_SORT_ROLE, key)
                item.setData(_ROW_KEY_ROLE, _row_key(row))
                self.table.setItem(index, column, item)
            if row.notes:
                cells[1][0].setToolTip(row.notes)
            cells[2][0].setToolTip(row.source_package)
        self.table.setSortingEnabled(True)
        self.table.clearSelection()
        # selectRow would replace the selection in extended mode; add each row.
        model = self.table.selectionModel()
        flags = model.SelectionFlag.Select | model.SelectionFlag.Rows
        for index in range(self.table.rowCount()):
            if self.table.item(index, 0).data(_ROW_KEY_ROLE) in selected_keys:
                model.select(self.table.model().index(index, 0), flags)
        self.table.blockSignals(False)
        if self._rows and not rows:
            self.empty_label.setText("No saved work matches this project or filter.")
        elif not self._rows:
            self.empty_label.setText(
                "No saved work yet. Open a mesh from Archive Browser, finish an edit, and it is saved here."
            )
        else:
            self.empty_label.setText("")
        self._selection_changed()

    def _selected_rows(self) -> list[SavedWorkRow]:
        model = self.table.selectionModel()
        if model is None:
            return []
        by_key = {_row_key(row): row for row in self._visible_rows}
        keys = []
        for index in sorted(model.selectedRows(), key=lambda item: item.row()):
            item = self.table.item(index.row(), 0)
            key = item.data(_ROW_KEY_ROLE) if item is not None else None
            if key in by_key and key not in keys:
                keys.append(key)
        return [by_key[key] for key in keys]

    def _selected_row(self) -> SavedWorkRow | None:
        rows = self._selected_rows()
        return rows[0] if rows else None

    def select_row(self, row: SavedWorkRow) -> None:
        for index in range(self.table.rowCount()):
            if self.table.item(index, 0).data(_ROW_KEY_ROLE) == _row_key(row):
                self.table.selectRow(index)
                return

    def _row_is_open(self, row: SavedWorkRow) -> bool:
        try:
            active = self.active_draft_manifest()
        except RuntimeError:
            active = None
        return bool(active is not None and row.manifest_path is not None
                    and Path(active).resolve() == Path(row.manifest_path).resolve())

    def _selection_changed(self) -> None:
        row = self._selected_row()
        key = _row_key(row) if row is not None else ""
        if key != self._detail_key:
            self._detail_key = key
            self.name_edit.setText(row.display_name if row is not None else "")
            self.notes_edit.setPlainText(row.notes if row is not None else "")
            index = self.project_combo.findData(row.project_id if row is not None and
                                                self._project_name(row.project_id) else NO_PROJECT)
            self.project_combo.setCurrentIndex(max(0, index))
        if row is not None:
            self.game_file_value.setText(row.source_archive_path)
            self.kind_value.setText(saved_work_kind_text(row))
            self.edit_pass_value.setText(str(row.edit_pass) if row.edit_pass > 0 else "Unknown")
            self.status_value.setText(saved_work_status_text(self.status_code(row)))
            self.folder_value.setText(str(row.folder))
        else:
            for label in (self.game_file_value, self.kind_value, self.edit_pass_value,
                          self.status_value, self.folder_value):
                label.setText("")
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        rows = self._selected_rows()
        row = rows[0] if rows else None
        single = len(rows) == 1
        for widget in (self.name_edit, self.project_combo, self.notes_edit, self.save_details_button,
                       self.continue_button, self.open_folder_button):
            widget.setEnabled(single)
        self.move_button.setEnabled(bool(rows))
        self.duplicate_button.setEnabled(single and row is not None and not row.is_built_mod)
        self.delete_button.setEnabled(single)
        if row is not None and row.is_built_mod:
            self.delete_button.setText("Remove from List...")
            self.delete_button.setToolTip("Remove this mod from the list. The mod folder and its files are kept.")
        else:
            self.delete_button.setText("Delete...")
            self.delete_button.setToolTip("Delete this draft from your computer.")
        if single and row is not None and not row.is_built_mod and self._row_is_open(row):
            self.delete_button.setEnabled(False)
            self.delete_button.setToolTip("This draft is open in Mesh Editor. Close it first.")
        if single and row is not None:
            self.open_folder_button.setEnabled(row.folder.is_dir())
        project_chosen = self._selected_project not in (ALL_WORK, NO_PROJECT)
        self.rename_project_button.setEnabled(project_chosen)
        self.delete_project_button.setEnabled(project_chosen)

    # ------------------------------------------------------------ actions

    def _save_details(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        name = self.name_edit.text()
        notes = self.notes_edit.toPlainText()
        project_id = str(self.project_combo.currentData() or NO_PROJECT)
        root = self.draft_root
        self._detail_key = ""
        self._run(lambda: update_saved_work_details(root, row, name=name, notes=notes, project_id=project_id),
                  self._action_done)

    def _continue_selected(self) -> None:
        row = self._selected_row()
        if row is not None:
            self.continue_requested.emit(row)

    def _open_selected_folder(self) -> None:
        row = self._selected_row()
        if row is not None and row.folder.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(row.folder)))

    def _duplicate_selected(self) -> None:
        row = self._selected_row()
        if row is None or row.is_built_mod:
            return
        name, accepted = QInputDialog.getText(
            self, "Duplicate Draft", "Name of the copy:", text=f"{row.display_name} copy",
        )
        if not accepted or not str(name or "").strip():
            return
        root = self.draft_root
        self._run(lambda: duplicate_saved_draft(root, row, name), self._action_done)

    def _move_selected(self) -> None:
        rows: Sequence[SavedWorkRow] = tuple(self._selected_rows())
        if not rows:
            return
        choices = ["No project", *(project.name for project in self._projects)]
        choice, accepted = QInputDialog.getItem(self, "Move to Project", "Project:", choices, 0, False)
        if not accepted:
            return
        index = choices.index(choice) if choice in choices else 0
        project_id = NO_PROJECT if index == 0 else self._projects[index - 1].project_id
        root = self.draft_root
        self._run(lambda: assign_project(root, rows, project_id), self._action_done)

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
        project_id = self._selected_project if self._selected_project != ALL_WORK else NO_PROJECT
        self._run(lambda: add_built_mod_folder(root, folder, project_id=project_id), self._action_done)


__all__ = ["SavedWorkPage", "saved_work_kind_text", "saved_work_status_text"]
