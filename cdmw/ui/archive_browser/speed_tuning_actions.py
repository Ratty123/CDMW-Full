"""Archive Browser actions behind Speed & Prefabs (experimental): read on a worker, export.

Speed & Prefabs is an Authoring tab. The Archive Browser builds it (it owns the archive
reads and the workers) and still opens it from the Action Charts button's menu, from the
right-click menu of a `.paac` file and as the registry command `browse.speed_tuning`.
Its sets are read from the same chart index the Action Chart Editor uses, and exports go
through the action chart mod writer, so the Action Chart Editor and Crimson Live Edit can
open the mods.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping, Optional, Sequence

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from shiboken6 import isValid

from cdmw.core.action_chart_binary import ActionChartError
from cdmw.domain.archives.prefab_speed import CATEGORIES
from cdmw.models import ArchiveEntry
from cdmw.services.action_chart_edit_service import ChartArchiveIndex, chart_archive_index, chart_scan, mod_destination
from cdmw.services.animation_speed_service import (
    SpeedCharacter,
    SpeedExportResult,
    SpeedFactors,
    SpeedModSummary,
    SpeedProfileOutcome,
    SpeedProfilePlan,
    export_speed_mod,
    export_speed_profile,
    linked_sets,
    list_characters,
    plan_speed_profile,
    plan_speed_set,
    read_speed_set,
    served_by,
    speed_mod_summary,
    speed_profile_outcome,
)
from cdmw.services.archive_read_service import read_archive_entry_data
from cdmw.services.independent_prefab_package import MAX_PREFAB_REPLACEMENTS
from cdmw.ui.archive_browser.shell_idle import run_task_when_shell_idle

COMMAND_ID = "browse.speed_tuning"
COMMAND_LABEL = "Speed & Prefabs (Experimental)..."


def _read(entry: ArchiveEntry) -> bytes:
    return read_archive_entry_data(entry)[0]


@dataclass(frozen=True, slots=True)
class PreparedSpeedTuning:
    index: ChartArchiveIndex
    characters: tuple[SpeedCharacter, ...]
    #: chart -> the charts it includes, when the scan could be read (for the AI tools).
    includes: Optional[Mapping[str, Sequence[str]]] = None


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
    return PreparedSpeedTuning(index, characters, includes)


TOOL_KEY = "speed_prefabs"


class ArchiveSpeedTuningActionsMixin:
    """Build Speed & Prefabs, export its mods, and search prefabs for speed values."""

    def _open_speed_tuning(self, chart_path: str = "") -> None:
        """Show the Speed & Prefabs tab, on ``chart_path``'s set when one is given."""

        def _show(workspace) -> None:
            if workspace.load_failed:
                self._load_speed_workspace(workspace)
            if not workspace.open_set(chart_path):
                self._report_unlisted_speed_set(chart_path)

        shell = self.shell
        container = getattr(shell, "speed_prefabs_tab", None)
        activate = getattr(shell, "_activate_tool_key", None)
        if container is None or not callable(activate):
            return
        activate(TOOL_KEY)
        when_created = getattr(container, "when_created", None)
        if callable(when_created):
            when_created(_show)
        else:
            _show(container)

    def _report_unlisted_speed_set(self, chart_path: str) -> None:
        # Only the charts of playable characters are sets; say so instead of showing another set unexplained.
        self.shell.set_status_message(f"Speed & Prefabs lists no set for {chart_path}.", error=True)

    def _open_current_archive_speed_tuning(self) -> None:
        entry = self._current_archive_action_chart_entry()
        self._open_speed_tuning(entry.path if entry is not None else "")

    def create_speed_workspace(self):
        """The Speed & Prefabs tab, on its loading page; the charts are read on a worker."""

        from cdmw.ui.archive_browser.game_table_actions import GameTableEditPanel
        from cdmw.ui.speed_prefabs.workspace import SpeedPrefabsWorkspace

        state: dict[str, object] = {}
        self._speed_state = state
        holder: dict[str, object] = {}
        self._speed_holder = holder

        def index() -> ChartArchiveIndex:
            found = state.get("index")
            if found is None:
                raise ActionChartError("The game's action charts are still being read.")
            return found  # type: ignore[return-value]

        def _linked(path: str):
            try:
                return linked_sets(index(), _read, path)
            except (ActionChartError, OSError, ValueError):
                return ()

        panel = GameTableEditPanel(side_by_side=True, bulk=True)
        panel.setObjectName("speedGameTablePanel")
        panel.editor.set_table_choice_visible(False)  # the page's own AI movement / Pushed objects buttons choose
        self._attach_game_table_panel(panel)
        workspace = SpeedPrefabsWorkspace(
            (),
            load_set=lambda path: read_speed_set(index(), _read, path, mod_folder=holder.get("mod_folder")),
            plan=lambda path, factors, linked: plan_speed_set(index(), _read, path, factors, linked=linked),
            linked_of=_linked,
            export=lambda path, factors, linked: self._export_speed_tuning(workspace, index(), path, factors,
                                                                           linked, holder),
            export_sets=lambda paths, factors: self._export_speed_sets(workspace, index(), paths, factors, holder),
            open_mod=lambda summary=None: (self._choose_speed_mod(workspace, holder) if summary is None
                                           else self._use_speed_mod(workspace, holder, summary)),
            close_mod=lambda: self._close_speed_mod(workspace, holder),
            open_chart=self._open_action_chart_editor,
            prefab_search=lambda category: self._search_speed_prefabs(workspace, index(), category),
            open_prefab=lambda path: self._open_speed_prefab(workspace, index(), path),
            scale_prefabs=lambda paths, factor, category: self._scale_speed_prefabs(
                workspace, index(), paths, factor, category),
            prefab_categories=tuple(CATEGORIES.items()),
            open_game_table=lambda table: self._show_game_table(panel, table),
            game_table_panel=panel,
            retry_load=lambda: self._load_speed_workspace(workspace),
            on_show=lambda: self._refresh_speed_workspace(workspace),
        )
        workspace.setObjectName(TOOL_KEY)
        self._speed_workspace = workspace
        self._load_speed_workspace(workspace)
        return workspace

    def _refresh_speed_workspace(self, workspace) -> None:
        """Called when the tab is shown: read again when the game folder changed or was set meanwhile."""

        state = getattr(self, "_speed_state", None) or {}
        if state.get("reading") or not isValid(workspace):
            return
        root = self._action_chart_root()
        if root and root != state.get("root"):
            if state.get("index") is not None:
                holder = getattr(self, "_speed_holder", None)
                if holder is not None:
                    holder.pop("mod_folder", None)  # the open mod belongs to the other folder's sets
                workspace.clear_sets()  # sets and prefabs of the other game folder
            self._load_speed_workspace(workspace)

    def _load_speed_workspace(self, workspace) -> None:
        """Read the chart index and every character's sets on a worker, showing each step."""

        state = getattr(self, "_speed_state", None)
        if state is None:
            state = self._speed_state = {}
        if state.get("reading"):
            return
        root = self._action_chart_root()
        state["root"] = root
        state.pop("index", None)
        if not root:
            workspace.show_load_error("Set the game folder in Browse Archives first.")
            return
        state["reading"] = True
        workspace.show_loading()
        relay = _LoadingRelay(self)
        relay.message.connect(lambda text: isValid(workspace) and workspace.loading and workspace.show_loading(text))

        def _task(log: Callable[[str], None]) -> PreparedSpeedTuning:
            def _log(text: str) -> None:
                log(text)
                relay.message.emit(text)
            return prepare_speed_tuning(root, _log)

        def _failed(message: str) -> None:
            state["reading"] = False
            relay.deleteLater()
            if isValid(workspace):
                workspace.show_load_error(message)

        def _done(result: object) -> None:
            if not isinstance(result, PreparedSpeedTuning):
                self.shell.set_status_message(f"Could not read the action charts: {result!r}", error=True)
                _failed(str(result))
                return
            state["reading"] = False
            relay.deleteLater()
            if not isValid(workspace):
                return
            state["index"] = result.index
            wanted = workspace.pending_set
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                workspace.set_characters(result.characters)
            finally:
                QApplication.restoreOverrideCursor()
            if wanted and not workspace.has_set(wanted):
                self._report_unlisted_speed_set(wanted)
            else:
                self.shell.set_status_message("Speed & Prefabs (experimental) is ready.")

        run_task_when_shell_idle(
            self.shell, workspace,
            status_message="Preparing Speed & Prefabs (experimental)...",
            task=_task,
            on_complete=_done,
            on_error=_failed,
            on_waiting=lambda: workspace.show_loading("Waiting for the current background task to finish…"),
            show_archive_progress=True,
        )

    def _ask_speed_export(self, dialog, holder: dict) -> Optional["_Plan"]:
        """The export dialog and the folder choice; None when the user cancels or the name is taken."""

        from cdmw.ui.archive_browser.action_chart_export_dialog import SEND_TO_DMM, ActionChartExportDialog

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
            return None
        parent = self._choose_action_chart_mod_parent(details.choice, dialog)
        if parent is None:
            return None
        try:
            mod_destination(parent, details.mod_title)
        except ActionChartError as exc:
            QMessageBox.warning(dialog, "Export Speed Tuning Mod (Experimental)", str(exc))
            return None
        plan = _Plan(parent, details.choice == SEND_TO_DMM, details.mod_title, details.mod_author,
                     details.mod_version, details.mod_description)
        holder["plan"] = plan
        return plan

    def _speed_export_done(self, workspace, holder: dict, plan: "_Plan", result: SpeedExportResult) -> None:
        """Say what an export wrote and mark the mod's sets in the list."""

        holder["mod_folder"] = result.folder
        if not isValid(workspace):
            return
        if result.folder is not None:
            try:
                self._show_speed_mod(workspace, speed_mod_summary(result.folder, result.charts), reload=False)
            except (ActionChartError, OSError, ValueError):
                pass  # the marks are a help; the export itself is done
        else:
            workspace.set_mod("", {}, reload=False)
        QMessageBox.information(workspace, "Speed Tuning Mod", speed_export_message(result, plan.sent))
        self.shell.set_status_message(f"Speed Tuning: wrote {result.folder or 'nothing'}")

    def _export_speed_tuning(self, dialog, index: ChartArchiveIndex, path: str, factors: SpeedFactors,
                             linked: Sequence[str], holder: dict) -> None:
        plan = self._ask_speed_export(dialog, holder)
        if plan is None:
            return
        label = PurePosixPath(path).name.removesuffix(".paac")

        def _task(log: Callable[[str], None], stop=None) -> SpeedExportResult:
            log(f"Speed Tuning (experimental): {path} ({label})")
            return export_speed_mod(index, _read, path, factors, parent=plan.parent, title=plan.title,
                                    author=plan.author, version=plan.version, description=plan.description,
                                    linked=linked, on_log=log, stop_event=stop)

        def _failed(message: str) -> None:
            self.shell.set_status_message(f"Speed Tuning export failed: {message}", error=True)
            if isValid(dialog):
                QMessageBox.warning(dialog, "Export Speed Tuning Mod (Experimental)", str(message))

        def _done(result: object) -> None:
            if not isinstance(result, SpeedExportResult):
                _failed(repr(result))
                return
            self._speed_export_done(dialog, holder, plan, result)

        run_task_when_shell_idle(
            self.shell, dialog,
            status_message=f"Writing the Speed Tuning mod {plan.title}...",
            task=_task,
            on_complete=_done,
            on_error=_failed,
            show_archive_progress=True,
            task_accepts_cancel=True,
        )

    def _export_speed_sets(self, workspace, index: ChartArchiveIndex, paths: Sequence[str], factors: SpeedFactors,
                           holder: dict) -> None:
        """One mod for every listed set: check them all on a worker, ask, then write once."""

        plan = self._ask_speed_export(workspace, holder)
        if plan is None:
            return
        paths = tuple(paths)
        title = "Export Speed Tuning Mod (Experimental)"
        relay = _ProgressRelay(self)
        relay.progress.connect(lambda done, total, text: isValid(workspace)
                               and workspace.show_batch_progress(done, total, text))

        def _ended() -> None:
            relay.deleteLater()
            if isValid(workspace):
                workspace.end_batch()

        def _failed(message: str) -> None:
            _ended()
            self.shell.set_status_message(f"Speed Tuning export failed: {message}", error=True)
            if isValid(workspace):
                QMessageBox.warning(workspace, title, str(message))

        def _check(log: Callable[[str], None], stop=None) -> "_CheckedSets":
            log(f"Speed Tuning (experimental): checking {len(paths)} listed set(s)")
            checked = plan_speed_profile(index, _read, paths, factors, stop_event=stop,
                                         on_progress=lambda done, total, path: relay.progress.emit(done, total, path))
            outcome = speed_profile_outcome(checked, parent=plan.parent, title=plan.title)
            root = getattr(index, "root", None)
            served = tuple((path, mod) for path in outcome.written if root and (mod := served_by(root, path)))
            return _CheckedSets(checked, outcome, served)

        def _write(checked: "_CheckedSets") -> None:
            def _task(log: Callable[[str], None], stop=None) -> SpeedExportResult:
                log(f"Speed Tuning (experimental): writing {len(checked.outcome.written)} set(s) into {plan.title}")
                return export_speed_profile(index, _read, paths, factors, parent=plan.parent, title=plan.title,
                                            author=plan.author, version=plan.version, description=plan.description,
                                            plan=checked.plan, on_log=log, stop_event=stop)

            def _done(result: object) -> None:
                if not isinstance(result, SpeedExportResult):
                    _failed(repr(result))
                    return
                _ended()
                self._speed_export_done(workspace, holder, plan, result)

            run_task_when_shell_idle(
                self.shell, workspace,
                status_message=f"Writing the Speed Tuning mod {plan.title}...",
                task=_task,
                on_complete=_done,
                on_error=_failed,
                show_archive_progress=True,
                task_accepts_cancel=True,
            )

        def _checked(result: object) -> None:
            if not isinstance(result, _CheckedSets):
                _failed(repr(result))
                return
            if not isValid(workspace):
                relay.deleteLater()
                return
            text, details = profile_summary(result.plan, result.outcome, result.served, plan.title)
            if not result.outcome.written and not result.outcome.removed:
                _ended()
                box = QMessageBox(QMessageBox.Icon.Information, title, text, QMessageBox.StandardButton.Ok, workspace)
                box.setDetailedText(details)
                box.exec()
                return
            box = QMessageBox(QMessageBox.Icon.Question, title, text,
                              QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, workspace)
            box.setDefaultButton(QMessageBox.StandardButton.Yes)
            box.setDetailedText(details)
            if box.exec() != QMessageBox.StandardButton.Yes:
                _ended()
                return
            _write(result)

        workspace.show_batch_progress(0, 0)
        run_task_when_shell_idle(
            self.shell, workspace,
            status_message="Checking the listed sets...",
            task=_check,
            on_complete=_checked,
            on_error=_failed,
            show_archive_progress=True,
            task_accepts_cancel=True,
        )

    # --- reopening a speed mod ------------------------------------------------------------

    def _show_speed_mod(self, workspace, summary: SpeedModSummary, *, reload: bool = True) -> None:
        workspace.set_mod(summary.title, summary.charts, folder=str(summary.folder), derived=summary.derived,
                          reload=reload)

    def _choose_speed_mod(self, workspace, holder: dict) -> None:
        """Start from > A speed mod you made: choose its folder and show its factors."""

        selected = QFileDialog.getExistingDirectory(workspace, "Choose a Speed Tuning Mod Folder",
                                                    str(self._action_chart_mods_start()))
        if selected:
            self._open_speed_mod(workspace, holder, Path(selected))

    def _open_speed_mod(self, workspace, holder: dict, folder: Path) -> None:
        """Read the mod in ``folder`` on a worker; its sets then open with the mod's factors."""

        def _task(log: Callable[[str], None]) -> SpeedModSummary:
            log(f"Reading the speed mod: {folder}")
            return speed_mod_summary(folder)

        def _failed(message: str) -> None:
            self.shell.set_status_message(f"Could not read the speed mod: {message}", error=True)
            if isValid(workspace):
                QMessageBox.warning(workspace, "Speed & Prefabs", str(message))

        def _done(result: object) -> None:
            if not isinstance(result, SpeedModSummary):
                _failed(repr(result))
                return
            self._use_speed_mod(workspace, holder, result)

        run_task_when_shell_idle(
            self.shell, workspace,
            status_message="Reading the speed mod...",
            task=_task,
            on_complete=_done,
            on_error=_failed,
            show_archive_progress=True,
        )

    def _use_speed_mod(self, workspace, holder: dict, summary: SpeedModSummary) -> None:
        """Make ``summary``'s mod the open one: its sets open with its factors, and exports update it."""

        holder["mod_folder"] = summary.folder
        # The next export is prefilled with this mod's name, so it updates the mod.
        holder["plan"] = _Plan(summary.folder.parent, False, summary.title, summary.author, summary.version, "")
        if isValid(workspace):
            self._show_speed_mod(workspace, summary)
            self.shell.set_status_message(f"Speed & Prefabs shows the mod {summary.title}.")

    def _close_speed_mod(self, workspace, holder: dict) -> None:
        holder.pop("mod_folder", None)
        holder.pop("plan", None)
        workspace.set_mod("", {})

    # --- prefabs --------------------------------------------------------------------------

    def _search_speed_prefabs(self, workspace, index: ChartArchiveIndex, category: str) -> None:
        from cdmw.services.prefab_speed_service import search_speed_prefabs

        relay = _ProgressRelay(self)
        relay.progress.connect(lambda done, total, text: isValid(workspace)
                               and workspace.show_prefab_progress(done, total, text))

        def _task(log: Callable[[str], None], stop=None):
            entries = [entry for path in index.paths_by_extension.get(".prefab", ())
                       if (entry := index.entry_for_path(path)) is not None]
            first = f"Reading the type tables of {len(entries):,} prefabs (the first search takes a few minutes)"
            log(first)
            relay.progress.emit(0, len(entries), first)

            def _progress(done: int, total: int) -> None:
                log(f"{done:,} of {total:,} prefabs read")
                relay.progress.emit(done, total, f"{done:,} of {total:,} prefabs read…")

            return search_speed_prefabs(entries, _read, category=category, key=index, on_progress=_progress,
                                        stop_event=stop)

        def _done(result: object) -> None:
            relay.deleteLater()
            if not isValid(workspace):
                return
            if not isinstance(result, tuple):
                workspace.show_prefab_results((), note=f"The search failed: {result!r}")
                return
            workspace.show_prefab_results([hit.to_data(category) for hit in result])

        def _failed(message: str) -> None:
            relay.deleteLater()
            if isValid(workspace):
                workspace.show_prefab_results((), note=f"The search failed: {message}")

        run_task_when_shell_idle(
            self.shell, workspace,
            status_message="Searching prefabs for speed values...",
            task=_task,
            on_complete=_done,
            on_error=_failed,
            on_waiting=lambda: workspace.show_prefab_progress(
                0, 0, "Waiting for the current background task to finish…"),
            show_archive_progress=True,
            task_accepts_cancel=True,
        )

    def _scale_speed_prefabs(self, workspace, index: ChartArchiveIndex, paths: Sequence[str], factor: float,
                             category: str) -> None:
        """One item package for every listed prefab: scale them on a worker, ask, then write once."""

        from cdmw.constants import PACKAGE_EXTENSION, PACKAGE_EXTENSIONS
        from cdmw.services.independent_prefab_authoring import prepare_prefab_packages, write_prefab_package
        from cdmw.services.prefab_speed_service import scale_speed_prefabs

        title = "Scale Listed Prefabs (Experimental)"
        package_root = self._action_chart_root()
        if not package_root:
            self.shell.set_status_message("Set the game package root before saving an item package.", error=True)
            return
        paths = tuple(paths)
        relay = _ProgressRelay(self)
        relay.progress.connect(lambda done, total, text: isValid(workspace)
                               and workspace.show_prefab_progress(done, total, text))

        def _ended() -> None:
            relay.deleteLater()
            if isValid(workspace):
                workspace.end_prefab_scaling()

        def _failed(message: str) -> None:
            _ended()
            self.shell.set_status_message(f"Scaling the listed prefabs failed: {message}", error=True)
            if isValid(workspace):
                QMessageBox.warning(workspace, title, str(message))

        def _scale(log: Callable[[str], None], stop=None) -> "_ScaledPrefabs":
            log(f"Speed & Prefabs (experimental): scaling {len(paths)} listed prefab(s) by {factor:g}x")
            missing = tuple(path for path in paths if index.entry_for_path(path) is None)
            entries = [entry for path in paths if (entry := index.entry_for_path(path)) is not None]
            outcomes = scale_speed_prefabs(
                entries, _read, factor, category=category, stop_event=stop,
                on_progress=lambda done, total: relay.progress.emit(
                    done, total, f"{done:,} of {total:,} listed prefabs read…"))
            return _ScaledPrefabs(outcomes, missing)

        def _write(scaled: "_ScaledPrefabs", destination: Path) -> None:
            edits = {item.path: (item.source, item.patched) for item in scaled.outcomes if item.patched is not None}

            def _task(log: Callable[[str], None], stop=None) -> tuple[Path, tuple[str, ...]]:
                log(f"Checking {len(edits)} prefab(s) against the game's own copies...")
                review = prepare_prefab_packages(package_root, edits, title=destination.stem, stop_event=stop,
                                                 on_log=log)
                write_prefab_package(review, destination, stop_event=stop, on_log=log)
                return destination, review.lines

            def _done(result: object) -> None:
                if not isinstance(result, tuple) or len(result) != 2:
                    _failed(repr(result))
                    return
                _ended()
                written, lines = result
                self.shell.set_status_message(f"Wrote prefab item package: {written}")
                if isValid(workspace):
                    QMessageBox.information(workspace, title,
                                            f"Wrote prefab item package:\n{written}\n\n" + "\n".join(lines))

            run_task_when_shell_idle(
                self.shell, workspace,
                status_message="Building the prefab item package...",
                task=_task,
                on_complete=_done,
                on_error=_failed,
                show_archive_progress=True,
                task_accepts_cancel=True,
            )

        def _scaled(result: object) -> None:
            if not isinstance(result, _ScaledPrefabs):
                _failed(repr(result))
                return
            if not isValid(workspace):
                relay.deleteLater()
                return
            text, details, count = prefab_batch_summary(result.outcomes, factor, result.missing)
            if not count or count > MAX_PREFAB_REPLACEMENTS:
                _ended()
                box = QMessageBox(QMessageBox.Icon.Information, title, text, QMessageBox.StandardButton.Ok, workspace)
                box.setDetailedText(details)
                box.exec()
                return
            box = QMessageBox(QMessageBox.Icon.Question, title, text,
                              QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, workspace)
            box.setDefaultButton(QMessageBox.StandardButton.Yes)
            box.setDetailedText(details)
            if box.exec() != QMessageBox.StandardButton.Yes:
                _ended()
                return
            name = f"{category or 'prefab'}_speed_{factor:g}x".replace(".", "_")
            default = self.shell.settings_file_path.parent / "prefab_packages" / f"{name}{PACKAGE_EXTENSION}"
            selected, _filter = QFileDialog.getSaveFileName(workspace, "Save Prefab Package", str(default),
                                                            "Independent items (*.cdmw)")
            if not selected:
                _ended()
                return
            destination = Path(selected)
            if destination.suffix.lower() not in PACKAGE_EXTENSIONS:
                destination = destination.with_name(f"{destination.name}{PACKAGE_EXTENSION}")
            _write(result, destination)

        workspace.begin_prefab_scaling()
        run_task_when_shell_idle(
            self.shell, workspace,
            status_message="Scaling the listed prefabs...",
            task=_scale,
            on_complete=_scaled,
            on_error=_failed,
            show_archive_progress=True,
            task_accepts_cancel=True,
        )

    def _open_speed_game_table(self, table: str) -> None:
        """Speed & Prefabs' Game tables page on ``table``."""

        def _show(workspace) -> None:
            workspace.open_table(table)  # first, so the page's first visit reads no other table
            workspace.show_page("tables")

        shell = self.shell
        container = getattr(shell, "speed_prefabs_tab", None)
        activate = getattr(shell, "_activate_tool_key", None)
        if container is None or not callable(activate):
            return
        activate(TOOL_KEY)
        when_created = getattr(container, "when_created", None)
        if callable(when_created):
            when_created(_show)  # at once when the tab exists, else as soon as it is built
        else:
            _show(container)

    def _open_speed_prefab(self, workspace, index: ChartArchiveIndex, path: str) -> None:
        """Show ``path`` in the Prefab Inspector beside the search results, speed values first."""

        from cdmw.ui.archive_browser.prefab_inspector_dialog import PrefabInspectorDialog

        entry = index.entry_for_path(path)
        if entry is None:
            workspace.show_prefab_inspector(path, None, note=f"{path} is not in the game archives.")
            return
        try:
            data = _read(entry)
        except Exception as exc:  # noqa: BLE001 - shown to the user
            workspace.show_prefab_inspector(path, None, note=f"Could not read {path}: {exc}")
            return

        def _save(patched: bytes, summary: str) -> bool:
            # As the Inspector's own window: nothing to export when nothing changed. False when the
            # user cancelled the export question, so the tab still counts the edits as unsaved.
            return patched == data or self._offer_prefab_export(entry, data, patched, summary) is not False

        users = getattr(self, "_prefab_users_finder", None)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            inspector = PrefabInspectorDialog(
                data,
                title=f"Prefab Inspector - {entry.basename}",
                parent=workspace,
                on_save=_save,
                find_users=users(entry) if callable(users) else None,
                speed_filter=True,
                embedded=True,
            )
        finally:
            QApplication.restoreOverrideCursor()
        inspector.setObjectName("speedPrefabInspector")
        inspector.title_label.setToolTip(path)
        workspace.show_prefab_inspector(path, inspector)


class _LoadingRelay(QObject):
    """Carries the worker's progress lines to the loading page on the UI thread."""

    message = Signal(str)


class _ProgressRelay(QObject):
    """Carries the prefab search's progress (done, total, line) to the Prefabs page."""

    progress = Signal(int, int, str)


@dataclass(frozen=True, slots=True)
class _Plan:
    parent: Path
    sent: bool
    title: str
    author: str
    version: str
    description: str


@dataclass(frozen=True, slots=True)
class _CheckedSets:
    """The listed sets checked against one set of factors and against the mod they go into."""

    plan: SpeedProfilePlan
    outcome: SpeedProfileOutcome
    served: tuple[tuple[str, str], ...]  # (chart, the mounted DMM mod that already serves it)


@dataclass(frozen=True)
class _ScaledPrefabs:
    """What the scaling worker hands back: an outcome per prefab, and listed paths the archives lack."""

    outcomes: tuple
    missing: tuple[str, ...] = ()


def _range(pair: Optional[tuple[float, float]]) -> str:
    if not pair:
        return ""
    low, high = pair
    return f"{low:g}" if low == high else f"{low:g} to {high:g}"


def prefab_batch_summary(outcomes: Sequence, factor: float, missing: Sequence[str] = ()) -> tuple[str, str, int]:
    """The question asked before the listed prefabs become one package, the list behind Show
    Details, and how many prefabs would be written."""

    changed = [item for item in outcomes if item.patched is not None]
    left: dict[str, int] = {}
    for item in outcomes:
        if item.patched is None:
            reason = item.reason.split(":", 1)[0]
            left[reason] = left.get(reason, 0) + 1
    if missing:
        left["not in the game archives"] = len(missing)
    values = sum(item.values for item in changed)
    lines = []
    if len(changed) > MAX_PREFAB_REPLACEMENTS:
        lines.append(f"A package holds at most {MAX_PREFAB_REPLACEMENTS} prefabs, and {len(changed)} would change. "
                     "Choose a category or search again.")
    elif changed:
        lines.append(f"Scale {values:,} value(s) in {len(changed):,} prefab(s) by {factor:g}x "
                     "and save them as one item package?")
    else:
        lines.append("None of the listed prefabs holds a speed value that can be scaled.")
    if left:
        lines.append("Left out: " + ", ".join(f"{count:,} {reason}" for reason, count in left.items()) + ".")
    if changed:
        lines.append("")
        lines.append("Prefab speed edits have not been tested in game.")
    details = [f"{item.path}: {item.values} value(s), {_range(item.before)} -> {_range(item.after)}"
               for item in changed]
    details += [f"{item.path}: left out, {item.reason}" for item in outcomes if item.patched is None]
    details += [f"{path}: left out, not in the game archives" for path in missing]
    return "\n".join(lines), "\n".join(details), len(changed)


def profile_summary(plan: SpeedProfilePlan, outcome: SpeedProfileOutcome, served: Sequence[tuple[str, str]],
                    title: str) -> tuple[str, str]:
    """The question asked before a many-set export, and the per-chart list behind Show Details."""

    plans = {item.path.lower(): item for item in plan.plans}
    written = [plans[path.lower()] for path in outcome.written if path.lower() in plans]
    values = sum(item.changed_values for item in written)
    lines = []
    if written:
        lines.append(f"{len(written)} set(s) change ({values:,} speed values).")
    else:
        lines.append("These factors change no speed value in the listed sets.")
    if plan.unchanged:
        lines.append(f"No change in {len(plan.unchanged)} set(s).")
    if outcome.left_out:
        lines.append(f"Left out: {len(outcome.left_out)}.")
    if served:
        lines.append(f"Already served by another mounted DMM mod: {len(served)}.")
    if outcome.removed:
        lines.append(f"Taken out of the mod because these factors change nothing there: {len(outcome.removed)}.")
    if written or outcome.removed:
        lines.append("")
        lines.append(f"Write the mod {title}?")
    details = []
    for item in written:
        kinds = ", ".join(f"{kind.label} {kind.values}" for kind in item.kinds)
        details.append(f"{item.path}: {item.changed_values} value(s)" + (f" ({kinds})" if kinds else ""))
    details += [f"{path}: no change" for path in plan.unchanged]
    details += [f"{path}: left out. {reason}" for path, reason in outcome.left_out]
    details += [f"{path}: also served by the mounted DMM mod {mod}" for path, mod in served]
    details += [f"{path}: taken out of the mod" for path in outcome.removed]
    return "\n".join(lines), "\n".join(details)


def speed_export_message(result: SpeedExportResult, sent: bool) -> str:
    left_out = [f"  {path}: {reason}" for path, reason in result.left_out]
    if result.folder is None:
        text = (f"Every set in {result.title} is back at the game's speed, so the mod was removed."
                if result.removed else "Nothing was written: these factors change nothing.")
        return text + ("\n\nLeft out:\n" + "\n".join(left_out) if left_out else "")
    where = "Sent the Speed Tuning mod to DMM" if sent else "Wrote the Speed Tuning DMM mod"
    lines = [f"{where}:\n{result.folder}", ""]
    if result.removed:
        lines.append("Back at the game's speed, so taken out of the mod: " + ", ".join(result.removed))
    if result.kept:
        lines.append("Kept as its own set, with its own factors: " + ", ".join(result.kept))
    if left_out:
        lines.append("Left out:\n" + "\n".join(left_out))
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
    "TOOL_KEY",
    "PreparedSpeedTuning",
    "install_speed_tuning_command",
    "prefab_batch_summary",
    "prepare_speed_tuning",
    "profile_summary",
    "speed_export_message",
]
