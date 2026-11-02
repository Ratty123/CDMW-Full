"""Archive Browser actions for `.paac` action charts: find, edit, and export as a DMM mod.

Charts, clips and the character package description are looked up in an index the
service builds from the game's archive tables on a worker and keeps for the session.
The editor is not modal, so the Archive Browser stays usable while a chart is open.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Optional

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMenu, QMessageBox, QToolButton

from cdmw.core.action_chart_binary import ActionChartError
from cdmw.models import ArchiveEntry
from cdmw.services.action_chart_edit_service import (
    ActionChartChanges,
    ActionChartModResult,
    ChartArchiveIndex,
    ChartMod,
    build_resource_catalog,
    change_summary,
    character_rows_from_index,
    chart_archive_index,
    chart_scan,
    chart_users,
    clip_info,
    compare_charts,
    is_editable_action_chart_path,
    load_editable_chart,
    mod_destination,
    read_chart_mod,
    write_action_chart_mod,
)
from cdmw.services.archive_read_service import read_archive_entry_data
from cdmw.ui.archive_browser.action_chart_editor_dialog import ActionChartEditorDialog, ActionChartEditorResult
from cdmw.ui.archive_browser.action_chart_export_dialog import SEND_TO_DMM, ActionChartExportDialog
from cdmw.ui.archive_browser.action_chart_finder_dialog import ActionChartFinderDialog


def _normal(path: object) -> str:
    return str(path or "").replace("\\", "/").strip().strip("/").lower()


def _read(entry: ArchiveEntry) -> bytes:
    return read_archive_entry_data(entry)[0]


@dataclass(frozen=True, slots=True)
class _ExportPlan:
    parent: Path
    sent: bool
    title: str
    author: str
    version: str
    description: str
    keep_existing: bool = True


@dataclass(frozen=True, slots=True)
class _PreparedChart:
    index: ChartArchiveIndex
    entry: ArchiveEntry
    path: str
    data: bytes
    edited: Optional[bytes]
    changes: Optional[ActionChartChanges]
    catalogs: dict
    used_by: tuple[str, ...]
    character_rows: tuple = ()
    clip_uses: Optional[dict] = None
    includes: Optional[dict] = None


class ArchiveActionChartActionsMixin:
    """Find a chart, edit it, and write it as a DMM mod."""

    # --- entry points -------------------------------------------------------------------

    def _build_action_chart_button(self) -> QToolButton:
        """The Archive Browser's Action Charts button: works with nothing selected."""

        button = QToolButton()
        button.setText("Action Charts")
        button.setToolTip("Find a character's action chart to edit, or continue an action chart mod CDMW wrote.")
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(button)
        find_action = menu.addAction("Find Action Chart by Character...")
        find_action.triggered.connect(lambda _checked=False: self._open_action_chart_finder())
        open_action = menu.addAction("Open Action Chart Mod...")
        open_action.triggered.connect(lambda _checked=False: self._open_action_chart_mod())
        button.setMenu(menu)
        return button

    def _current_archive_action_chart_entry(self) -> ArchiveEntry | None:
        if self.archive_preview_showing_loose:
            return None
        selected = self._current_archive_entry()
        return selected if isinstance(selected, ArchiveEntry) and is_editable_action_chart_path(selected.path) else None

    def _action_chart_root(self) -> str:
        return str(self.archive_package_root_edit.text() or "").strip()

    def _open_current_archive_action_chart_editor(self) -> None:
        entry = self._current_archive_action_chart_entry()
        if entry is None:
            self.shell.set_status_message("Select a .paac archive entry before opening the Action Chart Editor.", error=True)
            return
        self._open_action_chart_editor(entry.path)

    # --- opening the editor -------------------------------------------------------------

    def _open_action_chart_editor(self, chart_path: str, *, mod: Optional[ChartMod] = None) -> None:
        name = PurePosixPath(str(chart_path).replace("\\", "/")).name
        status_message = f"Preparing Action Chart Editor for {name}..."
        self.shell.set_status_message(status_message)
        root = self._action_chart_root()

        def _prepare_action_chart(log: Callable[[str], None]) -> _PreparedChart:
            log("Indexing the game's action charts and clips (the first time takes a few seconds)")
            index = chart_archive_index(root)
            entry = index.entry_for_path(chart_path)
            if entry is None:
                raise ActionChartError(f"{chart_path} is not in the game archives.")
            log(f"Reading action chart: {entry.path}")
            data = _read(entry)
            # Refuse the shared action tables here, not after the dialog is built.
            chart = load_editable_chart(data, entry.path)
            edited = changes = None
            if mod is not None:
                edited = next((payload for path, payload in mod.charts.items() if _normal(path) == _normal(chart_path)), None)
                if edited is not None:
                    changes = compare_charts(data, edited, virtual_path=entry.path)
            log("Matching the chart's clips, blend spaces and sequencers to archive files")
            catalogs = build_resource_catalog(chart, index.paths_by_extension)
            try:
                rows = character_rows_from_index(index, _read)
            except (ActionChartError, OSError, ValueError):
                rows = ()
            log("Finding which charts play each clip (the first time takes a few seconds)")
            try:
                scan = chart_scan(index, _read)
                clip_uses, includes = dict(scan.clip_uses), dict(scan.includes)
            except (ActionChartError, OSError, ValueError):
                clip_uses = includes = None
            return _PreparedChart(index, entry, entry.path, data, edited, changes, catalogs,
                                  chart_users(rows, entry.path, includes), tuple(rows), clip_uses, includes)

        def _open_prepared_action_chart(result: object) -> None:
            if not isinstance(result, _PreparedChart):
                self.shell.set_status_message(f"Could not open {chart_path}: {result!r}", error=True)
                return
            self._show_action_chart_editor(result, mod)

        self.shell._run_utility_task_when_idle(
            status_message=status_message,
            task=_prepare_action_chart,
            on_complete=_open_prepared_action_chart,
            show_archive_progress=True,
        )

    def _show_action_chart_editor(self, prepared: _PreparedChart, mod: Optional[ChartMod] = None) -> None:
        index = prepared.index
        # Large charts hold thousands of animations; the tables fill before the window paints.
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            dialog = ActionChartEditorDialog(
                prepared.data,
                virtual_path=prepared.path,
                catalogs=prepared.catalogs,
                used_by=prepared.used_by,
                edited=prepared.edited,
                edited_changes=prepared.changes,
                clip_info=lambda clip: clip_info(index, clip, _read),
                show_in_browser=self._show_action_chart_clip_in_browser,
                clip_uses=prepared.clip_uses,
                chart_users_of=lambda path: chart_users(prepared.character_rows, path, prepared.includes),
                export_details=lambda payload: self._ask_action_chart_export(prepared.entry, payload, mod),
                export_writer=self._action_chart_export_writer(prepared),
                export_done=self._action_chart_mod_written,
                title=f"Action Chart Editor - {PurePosixPath(prepared.path).name}",
                parent=self,
            )
        except ActionChartError as exc:
            self.shell.set_status_message(f"Cannot edit {prepared.path}: {exc}", error=True)
            return
        finally:
            QApplication.restoreOverrideCursor()
        editors = getattr(self, "_action_chart_editors", None)
        if editors is None:
            editors = []
            self._action_chart_editors = editors
        editors.append(dialog)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.finished.connect(lambda _result, dialog=dialog: self._action_chart_editor_finished(dialog, prepared))
        dialog.setModal(False)
        dialog.show()

    def _action_chart_editor_finished(self, dialog: ActionChartEditorDialog, prepared: _PreparedChart) -> None:
        # The export has already run inside the editor; nothing is left to write here.
        editors = getattr(self, "_action_chart_editors", [])
        if dialog in editors:
            editors.remove(dialog)

    def _show_action_chart_clip_in_browser(self, clip: str) -> None:
        name = PurePosixPath(str(clip).replace("\\", "/")).name
        self.archive_filter_edit.setText(name)
        self.archive_path_search_button.click()
        self.shell.set_status_message(f"Searching the Archive Browser for {name}.")

    # --- export -------------------------------------------------------------------------

    def _choose_action_chart_mod_parent(self, choice: str, owner=None, start: Optional[Path] = None) -> Optional[Path]:
        owner = owner if owner is not None else self
        if choice == SEND_TO_DMM:
            from cdmw.ui.new_item.dmm_send_ui import choose_dmm_mods_folder

            return choose_dmm_mods_folder(owner)
        from cdmw.services.workspace_layout import workspace_paths

        default = start or workspace_paths(self.shell.settings_file_path.parent)["mod_ready_export_root"]
        selected = QFileDialog.getExistingDirectory(owner, "Choose Where to Save the Mod Folder", str(default))
        return Path(selected) if selected else None

    def _ask_action_chart_export(
        self, entry: ArchiveEntry, payload: ActionChartEditorResult, mod: Optional[ChartMod] = None
    ) -> Optional[_ExportPlan]:
        """Mod details and destination, asked while the editor is still open; None keeps it open."""
        stem = Path(PurePosixPath(entry.path.replace("\\", "/")).name).stem or "action_chart"
        # Asked from inside the open editor, so the editor owns these dialogs.
        owner = QApplication.activeModalWidget() or QApplication.activeWindow() or self
        details = ActionChartExportDialog(
            title=mod.title if mod is not None else f"{stem} chart edit",
            description=mod.description if mod is not None
            else f"Action chart edit for {entry.path}: {change_summary(payload.changes)}",
            author=mod.author if mod is not None else "",
            version=mod.version if mod is not None else "1.0",
            parent=owner,
        )
        if not details.exec() or not details.choice:
            return None
        start = mod.folder.parent if mod is not None else None
        parent = self._choose_action_chart_mod_parent(details.choice, owner, start)
        if parent is None:
            return None
        try:
            # Refuse a folder the export may not replace now, while the user can pick again.
            mod_destination(parent, details.mod_title)
        except ActionChartError as exc:
            QMessageBox.warning(owner, "Export Action Chart Mod", str(exc))
            return None
        return _ExportPlan(parent, details.choice == SEND_TO_DMM, details.mod_title, details.mod_author,
                           details.mod_version, details.mod_description, details.keep_existing)

    def _action_chart_export_writer(
        self, prepared: _PreparedChart
    ) -> Callable[[ActionChartEditorResult, object, Callable[[str], None]], ActionChartModResult]:
        """The export the editor runs on its own worker; it stays open until this succeeds."""

        entry, original, index = prepared.entry, prepared.data, prepared.index

        def _write(payload: ActionChartEditorResult, plan: object, log: Callable[[str], None]) -> ActionChartModResult:
            if not isinstance(plan, _ExportPlan):
                raise ActionChartError("The export has no destination.")
            return write_action_chart_mod(
                entry, original, payload.data, parent=plan.parent, title=plan.title, description=plan.description,
                author=plan.author, version=plan.version, keep_existing=plan.keep_existing,
                shipped_entries=index.entry_for_path, linked=payload.linked, read_shipped=_read, on_log=log,
            )

        return _write

    def _action_chart_mod_written(self, plan: object, result: object) -> None:
        if not isinstance(result, ActionChartModResult) or not isinstance(plan, _ExportPlan):
            self.shell.set_status_message("Action chart export finished with an unexpected result payload.", error=True)
            return
        charts = "\n".join(f"  {path}" for path in result.charts)
        if plan.sent:
            message = (f"Sent the action chart mod to DMM:\n{result.folder}\n\n"
                       "In DMM, enable it and click Mount. Action chart edits have not been confirmed in game yet.")
        else:
            message = (f"Wrote the action chart DMM mod into:\n{result.folder}\n\n"
                       "Add it in DMM and enable it there. Action chart edits have not been confirmed in game yet.")
        if result.replaced:
            message += "\n\n" + "It replaced the copy CDMW wrote earlier."
        if charts:
            message += "\n\n" + f"Charts in this mod:\n{charts}"
        QMessageBox.information(self, "Action Chart Mod Complete", message)
        self.shell.set_status_message(f"Wrote action chart DMM mod: {result.folder}")

    # --- finder and mods ----------------------------------------------------------------

    def _open_action_chart_finder(self) -> None:
        root = self._action_chart_root()

        def _read_action_packages(log: Callable[[str], None]) -> tuple:
            log("Indexing the game's action charts and clips (the first time takes a few seconds)")
            index = chart_archive_index(root)
            log("Reading the character action packages")
            rows = character_rows_from_index(index, _read)
            log("Finding which charts each slot chart includes (the first time takes a few seconds)")
            includes = dict(chart_scan(index, _read).includes)
            return rows, {path.lower() for path in index.paths_by_extension.get(".paac", ())}, includes

        def _show_action_chart_finder(result: object) -> None:
            if not isinstance(result, tuple) or len(result) != 3:
                self.shell.set_status_message(f"Could not read the character action packages: {result!r}", error=True)
                return
            rows, available, includes = result
            dialog = ActionChartFinderDialog(rows, available=available, includes=includes, parent=self)
            if dialog.exec() and dialog.selected_path:
                self._open_action_chart_editor(dialog.selected_path)

        self.shell._run_utility_task_when_idle(
            status_message="Reading the character action packages...",
            task=_read_action_packages,
            on_complete=_show_action_chart_finder,
            show_archive_progress=True,
        )

    def _action_chart_mods_start(self) -> Path:
        from cdmw.services.dmm_send import DMM_FOLDER_SETTING, dmm_mods_folder, find_dmm
        from cdmw.services.workspace_layout import workspace_paths

        settings = QSettings(str(self.shell.settings_file_path), QSettings.Format.IniFormat)
        install = find_dmm(str(settings.value(DMM_FOLDER_SETTING, "") or ""))
        if install is not None:
            try:
                return dmm_mods_folder(install)
            except ValueError:
                pass
        return workspace_paths(self.shell.settings_file_path.parent)["mod_ready_export_root"]

    def _open_action_chart_mod(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "Choose an Action Chart Mod Folder", str(self._action_chart_mods_start())
        )
        if not selected:
            return
        folder = Path(selected)

        def _read_action_chart_mod(log: Callable[[str], None]) -> ChartMod:
            log(f"Reading action chart mod: {folder}")
            return read_chart_mod(folder)

        def _choose_chart_in_mod(result: object) -> None:
            if not isinstance(result, ChartMod):
                self.shell.set_status_message(f"Could not read {folder}: {result!r}", error=True)
                return
            paths = sorted(result.charts, key=str.lower)
            path = paths[0]
            if len(paths) > 1:
                path, accepted = QInputDialog.getItem(self, "Open Action Chart Mod", "Chart to edit:", paths, 0, False)
                if not accepted:
                    return
            self._open_action_chart_editor(path, mod=result)

        self.shell._run_utility_task_when_idle(
            status_message=f"Reading action chart mod {folder.name}...",
            task=_read_action_chart_mod,
            on_complete=_choose_chart_in_mod,
            show_archive_progress=True,
        )


__all__ = ["ArchiveActionChartActionsMixin"]
