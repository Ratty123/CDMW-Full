"""Archive Browser actions for Speed Tuning (experimental): prepare on a worker, show, export.

Speed Tuning opens from the Action Charts button's menu, from the right-click menu of a
`.paac` file and as the registry command `browse.speed_tuning`. Its sets are read from
the same chart index the Action Chart Editor uses, and exports go through the action
chart mod writer, so the Action Chart Editor and Crimson Live Edit can open the mods.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from cdmw.core.action_chart_binary import ActionChartError
from cdmw.domain.archives.prefab_speed import CATEGORIES
from cdmw.models import ArchiveEntry
from cdmw.services.action_chart_edit_service import ChartArchiveIndex, chart_archive_index, chart_scan, mod_destination
from cdmw.services.animation_speed_service import (
    SpeedCharacter,
    SpeedExportResult,
    SpeedFactors,
    export_speed_mod,
    linked_sets,
    list_characters,
    plan_speed_set,
    read_speed_set,
)
from cdmw.services.archive_read_service import read_archive_entry_data

COMMAND_ID = "browse.speed_tuning"
COMMAND_LABEL = "Speed Tuning (Experimental)..."


def _read(entry: ArchiveEntry) -> bytes:
    return read_archive_entry_data(entry)[0]


@dataclass(frozen=True, slots=True)
class PreparedSpeedTuning:
    index: ChartArchiveIndex
    characters: tuple[SpeedCharacter, ...]


def prepare_speed_tuning(root: str, log: Callable[[str], None] = lambda _text: None) -> PreparedSpeedTuning:
    """The chart index, the chart scan and every character's sets; seconds the first time."""

    log("Indexing the game's action charts and clips (the first time takes a few seconds)")
    index = chart_archive_index(root)
    log("Finding which charts each set includes (the first time takes a few seconds)")
    try:
        includes = dict(chart_scan(index, _read).includes)
    except (ActionChartError, OSError, ValueError):
        includes = None
    characters = list_characters(index, _read, includes=includes)
    if not characters:
        raise ActionChartError("No character action charts were found in the game archives.")
    return PreparedSpeedTuning(index, characters)


class ArchiveSpeedTuningActionsMixin:
    """Open Speed Tuning, export its mods, and search prefabs for speed values."""

    def _open_speed_tuning(self, chart_path: str = "") -> None:
        root = self._action_chart_root()
        status_message = "Preparing Speed Tuning (experimental)..."
        self.shell.set_status_message(status_message)

        def _done(result: object) -> None:
            if not isinstance(result, PreparedSpeedTuning):
                self.shell.set_status_message(f"Could not open Speed Tuning: {result!r}", error=True)
                return
            self._show_speed_tuning(result, chart_path)

        self.shell._run_utility_task_when_idle(
            status_message=status_message,
            task=lambda log: prepare_speed_tuning(root, log),
            on_complete=_done,
            show_archive_progress=True,
        )

    def _open_current_archive_speed_tuning(self) -> None:
        entry = self._current_archive_action_chart_entry()
        self._open_speed_tuning(entry.path if entry is not None else "")

    def _show_speed_tuning(self, prepared: PreparedSpeedTuning, chart_path: str = ""):
        from cdmw.ui.archive_browser.speed_tuning_dialog import SpeedTuningDialog

        index = prepared.index
        holder: dict[str, object] = {}

        def _linked(path: str):
            try:
                return linked_sets(index, _read, path)
            except (ActionChartError, OSError, ValueError):
                return ()

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            dialog = SpeedTuningDialog(
                prepared.characters,
                load_set=lambda path: read_speed_set(index, _read, path, mod_folder=holder.get("mod_folder")),
                plan=lambda path, factors, linked: plan_speed_set(index, _read, path, factors, linked=linked),
                linked_of=_linked,
                export=lambda path, factors, linked: self._export_speed_tuning(dialog, index, path, factors, linked,
                                                                               holder),
                open_chart=self._open_action_chart_editor,
                prefab_search=lambda category: self._search_speed_prefabs(dialog, index, category),
                open_prefab=lambda path: self._open_speed_prefab(index, path),
                prefab_categories=tuple(CATEGORIES.items()),
                open_game_table=self._open_speed_game_table,
                parent=self,
            )
        finally:
            QApplication.restoreOverrideCursor()
        dialogs = getattr(self, "_speed_tuning_dialogs", None)
        if dialogs is None:
            dialogs = []
            self._speed_tuning_dialogs = dialogs
        dialogs.append(dialog)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.finished.connect(lambda _result, d=dialog: d in dialogs and dialogs.remove(d))
        dialog.setModal(False)
        if chart_path:
            dialog.select_set(chart_path)
        dialog.show()
        return dialog

    def _export_speed_tuning(self, dialog, index: ChartArchiveIndex, path: str, factors: SpeedFactors,
                             linked: Sequence[str], holder: dict) -> None:
        from cdmw.ui.archive_browser.action_chart_export_dialog import SEND_TO_DMM, ActionChartExportDialog

        label = PurePosixPath(path).name.removesuffix(".paac")
        previous = holder.get("plan")
        details = ActionChartExportDialog(
            title=getattr(previous, "title", "") or "Speed Tuning",
            description="", author=getattr(previous, "author", ""), parent=dialog,
        )
        details.setWindowTitle("Export Speed Tuning Mod (Experimental)")
        details.keep_checkbox.setChecked(True)
        details.keep_checkbox.setEnabled(False)
        details.keep_checkbox.setToolTip("Sets exported under one mod name collect in one mod; "
                                         "a set at 1x everywhere leaves it.")
        if not details.exec() or not details.choice:
            return
        parent = self._choose_action_chart_mod_parent(details.choice, dialog)
        if parent is None:
            return
        try:
            mod_destination(parent, details.mod_title)
        except ActionChartError as exc:
            QMessageBox.warning(dialog, "Export Speed Tuning Mod (Experimental)", str(exc))
            return
        plan = _Plan(parent, details.choice == SEND_TO_DMM, details.mod_title, details.mod_author,
                     details.mod_version, details.mod_description)
        holder["plan"] = plan

        def _task(log: Callable[[str], None]) -> SpeedExportResult:
            log(f"Speed Tuning (experimental): {path} ({label})")
            return export_speed_mod(index, _read, path, factors, parent=plan.parent, title=plan.title,
                                    author=plan.author, version=plan.version, description=plan.description,
                                    linked=linked, on_log=log)

        def _done(result: object) -> None:
            if not isinstance(result, SpeedExportResult):
                self.shell.set_status_message(f"Speed Tuning export failed: {result!r}", error=True)
                return
            if result.folder is not None:
                holder["mod_folder"] = result.folder
            QMessageBox.information(dialog, "Speed Tuning Mod", speed_export_message(result, plan.sent))
            self.shell.set_status_message(f"Speed Tuning: wrote {result.folder or 'nothing'}")

        self.shell._run_utility_task_when_idle(
            status_message=f"Writing the Speed Tuning mod {plan.title}...",
            task=_task,
            on_complete=_done,
            show_archive_progress=True,
        )

    # --- prefabs --------------------------------------------------------------------------

    def _search_speed_prefabs(self, dialog, index: ChartArchiveIndex, category: str) -> None:
        from cdmw.services.prefab_speed_service import search_speed_prefabs

        def _task(log: Callable[[str], None]):
            entries = [entry for path in index.paths_by_extension.get(".prefab", ())
                       if (entry := index.entry_for_path(path)) is not None]
            log(f"Reading the type tables of {len(entries):,} prefabs (the first search takes a few minutes)")
            return search_speed_prefabs(entries, _read, category=category, key=index,
                                        on_progress=lambda done, total: log(f"{done:,} of {total:,} prefabs read"))

        def _done(result: object) -> None:
            if not isinstance(result, tuple):
                dialog.show_prefab_results((), note=f"The search failed: {result!r}")
                return
            dialog.show_prefab_results([hit.to_data() for hit in result])

        self.shell._run_utility_task_when_idle(
            status_message="Searching prefabs for speed values...",
            task=_task,
            on_complete=_done,
            on_error=lambda message: dialog.show_prefab_results((), note=f"The search failed: {message}"),
            show_archive_progress=True,
        )

    def _open_speed_game_table(self, table: str) -> None:
        from types import SimpleNamespace

        from cdmw.services.game_table_edits import STATIC_TABLE_ROOT

        name = f"{table}.staticinfobody"
        self._open_game_table_editor(SimpleNamespace(path=STATIC_TABLE_ROOT + name, basename=name))

    def _open_speed_prefab(self, index: ChartArchiveIndex, path: str) -> None:
        entry = index.entry_for_path(path)
        if entry is None:
            self.shell.set_status_message(f"{path} is not in the game archives.", error=True)
            return
        try:
            data = _read(entry)
        except Exception as exc:  # noqa: BLE001 - reported to the user
            self.shell.set_status_message(f"Could not read {path}: {exc}", error=True)
            return
        self._show_prefab_inspector(entry, data, {}, speed_filter=True)


@dataclass(frozen=True, slots=True)
class _Plan:
    parent: Path
    sent: bool
    title: str
    author: str
    version: str
    description: str


def speed_export_message(result: SpeedExportResult, sent: bool) -> str:
    if result.folder is None:
        return (f"Every set in {result.title} is back at the game's speed, so the mod was removed."
                if result.removed else "Nothing was written: these factors change nothing.")
    where = "Sent the Speed Tuning mod to DMM" if sent else "Wrote the Speed Tuning DMM mod"
    lines = [f"{where}:\n{result.folder}", ""]
    if result.removed:
        lines.append("Back at the game's speed, so taken out of the mod: " + ", ".join(result.removed))
    lines.append("Charts in this mod:\n" + "\n".join(f"  {path}" for path in result.charts))
    lines.append("")
    lines.append("In DMM, enable it and click Mount. Speed Tuning is experimental: check the moves in game.")
    return "\n".join(lines)


def install_speed_tuning_command(browser):
    """Register browse.speed_tuning so the palette, app.run_command and AI tools reach it."""

    from cdmw.mcp.names import READ
    from cdmw.ui.commands.registry import Command, command_registry

    registry = command_registry()
    if registry is None:
        return None

    def reason() -> str:
        return "" if browser._action_chart_root() else "Set the game folder in Archive Browser first."

    registry.register(Command(COMMAND_ID, COMMAND_LABEL, "browse", lambda: browser._open_speed_tuning(), reason,
                              keywords=("speed", "animation speed", "attack speed", "action chart"), effect=READ),
                      replace=True)
    return registry


__all__ = [
    "COMMAND_ID",
    "COMMAND_LABEL",
    "ArchiveSpeedTuningActionsMixin",
    "PreparedSpeedTuning",
    "install_speed_tuning_command",
    "prepare_speed_tuning",
    "speed_export_message",
]
