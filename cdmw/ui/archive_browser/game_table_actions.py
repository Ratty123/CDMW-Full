"""Archive Browser: edit whitelisted values in game data tables and write a DMM mod folder.

Opened from a `.staticinfoheader`/`.staticinfobody` entry. Loading a table and writing the
mod run on the shell's utility worker; the dialog only collects edits. The archives are
never written: the edited base tables go into a new DMM mod folder.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QVBoxLayout, QWidget)

from cdmw.core.static_table_records import editable_kinds
from cdmw.models import ArchiveEntry
from cdmw.services.game_table_edits import (
    TableEditError,
    TableEditIndex,
    TableModResult,
    archive_table_layers,
    compose_table_edits,
    composed_files,
    group_edits,
    load_table_index,
    mod_destination,
    write_table_edit_mod,
)
from cdmw.services.game_table_speed import (
    BULK_MAX_FACTOR,
    BULK_MIN_FACTOR,
    bulk_message,
    scale_speed_rows,
    speed_choices,
    speed_row_count,
)
from cdmw.ui.new_item.game_tables_editor import GameTablesEditor

#: Above this many changes from one multiply, the page asks first: writing them takes a while.
BULK_ASK_ABOVE = 5000
_SUFFIXES = (".staticinfoheader", ".staticinfobody")


def table_kind(path: str) -> str:
    """The table an archive path belongs to (`inventory.dlc_01.staticinfobody` -> `inventory`)."""

    name = PurePosixPath(str(path).replace("\\", "/")).name.lower()
    for suffix in _SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)].split(".", 1)[0]
    return ""


class GameTableEditPanel(QWidget):
    """`GameTablesEditor` with a mod name and a Write button; the owner does the work.

    Speed & Prefabs shows one in its Game tables page; `GameTableEditDialog` wraps one for
    tables opened from Browse Archives. With ``bulk`` (the speed tables only) a row under the
    rows list multiplies one speed value on every row the filter matches.
    """

    def __init__(self, parent=None, *, side_by_side: bool = False, bulk: bool = False):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.editor = GameTablesEditor(include_speed=True, side_by_side=side_by_side)
        layout.addWidget(self.editor, 1)
        self.scale_button = None
        #: Answers "add this many changes?"; a test or a tool can put its own answer here.
        self.confirm_bulk = self._ask_bulk
        if bulk and self.editor.rows_layout is not None:
            self._build_bulk_row()
        row = QHBoxLayout()
        row.addWidget(QLabel("Mod name:"))
        self.mod_name = QLineEdit("Game table edits")
        row.addWidget(self.mod_name, 1)
        self.write = QPushButton("Write DMM Mod…")
        self.write.setProperty("primaryAction", True)
        self.write.setToolTip("Write the changed tables into a new mod folder in DMM's mods folder. "
                              "The game archives are not changed.")
        row.addWidget(self.write)
        if self.editor.pending_layout is not None:
            # Side by side, the mod name and Write button close the "Changes in this mod" frame.
            self.editor.pending_layout.addLayout(row)
        else:
            layout.addLayout(row)
        self.layers: dict[str, list] = {}
        #: Tables being read or waiting to be, so a second click starts no second read.
        self.loading: set[str] = set()
        self.editor.edits_changed.connect(self._update_write)
        self._update_write()

    def _update_write(self, *_args) -> None:
        self.write.setEnabled(bool(self.editor.edits()))

    # --- one factor on every matching row ---------------------------------------------------

    def _build_bulk_row(self) -> None:
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(QLabel("Multiply"))
        self.scale_field = QComboBox()
        self.scale_field.setObjectName("tableScaleFieldCombo")
        self.scale_field.setToolTip("The speed value to multiply. Move and minimum speed are the move speed and "
                                    "the minimum move speed of every speed entry of a row; they change together.")
        self.scale_field.currentIndexChanged.connect(lambda _index: self._refresh_bulk())
        row.addWidget(self.scale_field, 1)
        row.addWidget(QLabel("by"))
        self.scale_factor = QDoubleSpinBox()
        self.scale_factor.setObjectName("tableScaleFactorSpin")
        self.scale_factor.setProperty("cleanField", True)
        self.scale_factor.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.scale_factor.setRange(BULK_MIN_FACTOR, BULK_MAX_FACTOR)
        self.scale_factor.setDecimals(2)
        self.scale_factor.setSingleStep(0.1)
        self.scale_factor.setSuffix("x")
        self.scale_factor.setValue(1.0)
        self.scale_factor.setFixedWidth(76)
        self.scale_factor.lineEdit().setTextMargins(4, 0, 6, 0)
        row.addWidget(self.scale_factor)
        self.scale_button = QPushButton("Add matching rows")
        self.scale_button.setObjectName("tableScaleButton")
        self.scale_button.setToolTip(
            "Adds a change for every row the filter matches, not only the 500 listed. The game's value is "
            "multiplied, so pressing twice does not stack; 1.00x takes the changes back. Units are not known "
            "and these edits have not been tested in game.")
        self.scale_button.clicked.connect(self.add_scaled_rows)
        row.addWidget(self.scale_button)
        layout = self.editor.rows_layout
        layout.insertLayout(layout.indexOf(self.editor.message), row)
        self._bulk_table = ""
        self.editor.rows_changed.connect(lambda _count: self._refresh_bulk())
        self._refresh_bulk()

    def _refresh_bulk(self) -> None:
        """The value list follows the loaded table, and the button carries the real number of matches."""

        index = self.editor.index()
        table = index.table if index is not None else ""
        if table != self._bulk_table:
            self._bulk_table = table
            self.scale_field.blockSignals(True)
            self.scale_field.clear()
            for choice, label in speed_choices(table):
                self.scale_field.addItem(label, choice)
            self.scale_field.blockSignals(False)
        choice = str(self.scale_field.currentData() or "")
        count = speed_row_count(index, choice, self.editor.search.text()) if index is not None and choice else 0
        usable = bool(choice)
        self.scale_field.setEnabled(usable)
        self.scale_factor.setEnabled(usable)
        self.scale_button.setEnabled(usable and count > 0)
        self.scale_button.setText(f"Add {count:,} matching rows" if usable else "Add matching rows")

    def add_scaled_rows(self) -> bool:
        """Multiply the chosen value on every matching row into Changes in this mod; False when not done."""

        index = self.editor.index()
        choice = str(self.scale_field.currentData() or "") if self.scale_button is not None else ""
        if index is None or not choice:
            return False
        try:
            result = scale_speed_rows(index, choice=choice, factor=float(self.scale_factor.value()),
                                      query=self.editor.search.text())
        except TableEditError as exc:
            self.editor.message.setText(str(exc))
            return False
        if len(result.edits) > BULK_ASK_ABOVE and not self.confirm_bulk(len(result.edits)):
            return False
        self.editor.merge_edits(result.edits, result.labels, result.owners, remove=result.restore)
        self.editor.message.setText(bulk_message(result))
        return True

    def _ask_bulk(self, count: int) -> bool:
        answer = QMessageBox.question(
            self, "Edit Game Table Values",
            f"Add {count:,} changes? Writing a mod with this many changes can take minutes and cannot be "
            "stopped part-way.")
        return answer == QMessageBox.StandardButton.Yes


class GameTableEditDialog(QDialog):
    """A window around one `GameTableEditPanel`, for tables opened from Browse Archives."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Game Table Values")
        self.resize(1100, 720)
        layout = QVBoxLayout(self)
        self.panel = GameTableEditPanel(self)
        layout.addWidget(self.panel, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def editor(self) -> GameTablesEditor:
        return self.panel.editor

    @property
    def mod_name(self) -> QLineEdit:
        return self.panel.mod_name

    @property
    def write(self) -> QPushButton:
        return self.panel.write

    @property
    def layers(self) -> dict[str, list]:
        return self.panel.layers

    @property
    def loading(self) -> set[str]:
        return self.panel.loading

    def _update_write(self, *_args) -> None:
        self.panel._update_write()


class ArchiveGameTableActionsMixin:
    def _game_table_root(self) -> str:
        return str(self.archive_package_root_edit.text() or "").strip()

    def _open_game_table_editor(self, entry: ArchiveEntry) -> None:
        table = table_kind(entry.path)
        if table not in editable_kinds():
            self.shell.set_status_message(f"{entry.basename} has no values CDMW can change yet.", error=True)
            return
        dialog = getattr(self, "_game_table_dialog", None)
        if dialog is None:
            dialog = GameTableEditDialog(self)
            self._attach_game_table_panel(dialog)
            self._game_table_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        self._show_game_table(dialog, table)

    def _attach_game_table_panel(self, panel) -> None:
        """Wire a panel's Load and Write buttons to this browser's workers."""

        panel.editor.load_requested.connect(lambda name, p=panel: self._load_game_table(p, name))
        panel.write.clicked.connect(lambda _checked=False, p=panel: self._write_game_table_mod(p))

    def _show_game_table(self, panel, table: str) -> None:
        """Select ``table`` in the panel and read it unless it is already loaded."""

        position = panel.editor.table.findData(table)
        if position >= 0:
            panel.editor.table.setCurrentIndex(position)
        if panel.editor.loaded_table() != table:
            panel.editor.set_loading(True)
            self._load_game_table(panel, table)

    def _game_table_task_refused(self, dialog: GameTableEditDialog) -> bool:
        if self.shell._background_task_active():
            dialog.editor.show_error("Another background task is running. Try again when it has finished.")
            return True
        return False

    def _load_game_table(self, dialog: GameTableEditDialog, table: str) -> None:
        # Reading a table waits its turn behind another task (such as Speed & Prefabs reading
        # the action charts or searching prefabs) instead of refusing; writing still refuses, below.
        from cdmw.ui.archive_browser.shell_idle import run_task_when_shell_idle

        if table in dialog.loading:
            return
        dialog.loading.add(table)
        root = self._game_table_root()
        entries = tuple(getattr(self, "archive_entries", ()) or ())
        scan = (lambda _root: entries) if entries else None

        def _load(_log, stop_event):
            layers = archive_table_layers(root, table, scan=scan, stop_event=stop_event)
            return layers, load_table_index(table, layers, stop_event=stop_event)

        def _loaded(result) -> None:
            dialog.loading.discard(table)
            layers, index = result if isinstance(result, tuple) and len(result) == 2 else (None, None)
            if not isinstance(index, TableEditIndex):
                dialog.editor.show_error("Reading the table returned unexpected data.")
                return
            dialog.layers[table] = layers
            editor = dialog.editor
            if editor.current_table() != table and editor.loaded_table() == editor.current_table():
                # The user went back to the table that is still shown while this one was read.
                editor.refresh_loaded()
                return
            editor.set_index(index)

        def _failed(message: str) -> None:
            dialog.loading.discard(table)
            dialog.editor.show_error(message)

        def _waiting() -> None:
            dialog.editor.set_loading(True)
            dialog.editor.message.setText("Waiting for the current background task, then reading the table…")

        run_task_when_shell_idle(self.shell, dialog, status_message=f"Reading the {table} table...", task=_load,
                                 on_complete=_loaded, on_error=_failed, on_waiting=_waiting,
                                 on_start=lambda: dialog.editor.set_loading(True), task_accepts_cancel=True)

    def _write_game_table_mod(self, dialog: GameTableEditDialog) -> None:
        edits = dialog.editor.edits()
        missing = sorted(table for table in group_edits(edits) if table not in dialog.layers)
        if missing:
            dialog.editor.show_error("Load these tables again before writing: " + ", ".join(missing))
            return
        title = dialog.mod_name.text().strip()
        if not title:
            QMessageBox.warning(dialog, "Write DMM Mod", "Name the mod before writing it.")
            return
        from cdmw.ui.new_item.dmm_send_ui import choose_dmm_mods_folder

        parent = choose_dmm_mods_folder(dialog)
        if parent is None:
            return
        try:
            _folder, replaced = mod_destination(parent, title)
        except TableEditError as exc:
            QMessageBox.warning(dialog, "Write DMM Mod", str(exc))
            return
        if replaced and QMessageBox.question(
                dialog, "Write DMM Mod",
                f"Replace the mod named {title} that CDMW wrote earlier?") != QMessageBox.Yes:
            return
        if self._game_table_task_refused(dialog):
            return
        layers = dict(dialog.layers)
        root = self._game_table_root()

        def _write(log, stop_event):
            files = {}
            for table, table_edits in group_edits(edits).items():
                files.update(composed_files(compose_table_edits(table, layers[table], table_edits)))
            return write_table_edit_mod(files, parent=parent, title=title, edits=edits,
                                        game_root=Path(root) if root else None, on_log=log, stop_event=stop_event)

        def _written(result) -> None:
            if not isinstance(result, TableModResult):
                dialog.editor.show_error("Writing the mod returned unexpected data.")
                return
            message = (f"Wrote the DMM mod into:\n{result.folder}\n\n"
                       "In DMM, enable it and click Mount. Game table edits have not been confirmed in game yet.")
            if result.replaced:
                message += "\n\n" + "It replaced the copy CDMW wrote earlier."
            dialog.editor.show_error("")
            self.shell.set_status_message(f"Wrote game table mod {result.folder.name}.")
            QMessageBox.information(dialog, "Write DMM Mod", message)

        self.shell._run_utility_task(status_message=f"Writing game table mod {title}...", task=_write,
                                     on_complete=_written, on_error=dialog.editor.show_error,
                                     task_accepts_cancel=True)


__all__ = ["ArchiveGameTableActionsMixin", "GameTableEditDialog", "GameTableEditPanel", "table_kind"]
