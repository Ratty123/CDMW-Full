"""Archive Browser: edit whitelisted values in game data tables and write a DMM mod folder.

Opened from a `.staticinfoheader`/`.staticinfobody` entry. Loading a table and writing the
mod run on the shell's utility worker; the dialog only collects edits. The archives are
never written: the edited base tables go into a new DMM mod folder.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout

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
from cdmw.ui.new_item.game_tables_editor import GameTablesEditor

_SUFFIXES = (".staticinfoheader", ".staticinfobody")


def table_kind(path: str) -> str:
    """The table an archive path belongs to (`inventory.dlc_01.staticinfobody` -> `inventory`)."""

    name = PurePosixPath(str(path).replace("\\", "/")).name.lower()
    for suffix in _SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)].split(".", 1)[0]
    return ""


class GameTableEditDialog(QDialog):
    """Hosts `GameTablesEditor` with a mod name and a Write button; the owner does the work."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Game Table Values")
        self.resize(1100, 720)
        layout = QVBoxLayout(self)
        self.editor = GameTablesEditor()
        layout.addWidget(self.editor, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("Mod name:"))
        self.mod_name = QLineEdit("Game table edits")
        row.addWidget(self.mod_name, 1)
        self.write = QPushButton("Write DMM Mod…")
        self.write.setToolTip("Write the changed tables into a new mod folder in DMM's mods folder. "
                              "The game archives are not changed.")
        row.addWidget(self.write)
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.layers: dict[str, list] = {}
        self.editor.edits_changed.connect(self._update_write)
        self._update_write()

    def _update_write(self, *_args) -> None:
        self.write.setEnabled(bool(self.editor.edits()))


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
            dialog.editor.load_requested.connect(lambda name, d=dialog: self._load_game_table(d, name))
            dialog.write.clicked.connect(lambda _checked=False, d=dialog: self._write_game_table_mod(d))
            self._game_table_dialog = dialog
        position = dialog.editor.table.findData(table)
        if position >= 0:
            dialog.editor.table.setCurrentIndex(position)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        if dialog.editor.loaded_table() != table:
            dialog.editor.set_loading(True)
            self._load_game_table(dialog, table)

    def _game_table_task_refused(self, dialog: GameTableEditDialog) -> bool:
        if self.shell._background_task_active():
            dialog.editor.show_error("Another background task is running. Try again when it has finished.")
            return True
        return False

    def _load_game_table(self, dialog: GameTableEditDialog, table: str) -> None:
        if self._game_table_task_refused(dialog):
            return
        root = self._game_table_root()
        entries = tuple(getattr(self, "archive_entries", ()) or ())
        scan = (lambda _root: entries) if entries else None

        def _load(_log, stop_event):
            layers = archive_table_layers(root, table, scan=scan, stop_event=stop_event)
            return layers, load_table_index(table, layers, stop_event=stop_event)

        def _loaded(result) -> None:
            layers, index = result
            if not isinstance(index, TableEditIndex):
                dialog.editor.show_error("Reading the table returned unexpected data.")
                return
            dialog.layers[table] = layers
            dialog.editor.set_index(index)

        self.shell._run_utility_task(status_message=f"Reading the {table} table...", task=_load,
                                     on_complete=_loaded, on_error=dialog.editor.show_error,
                                     task_accepts_cancel=True)

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


__all__ = ["ArchiveGameTableActionsMixin", "GameTableEditDialog", "table_kind"]
