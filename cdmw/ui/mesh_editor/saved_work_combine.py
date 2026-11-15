"""Drafts & Mods: Combine into One Mod (GitHub issue 31).

Two or more built Mesh Editor mods that change different game files become one
new mod. The flow has four stages, each in one dialog that can be cancelled:

1. Checking: a worker reads the selected builds and plans the combination.
   Nothing is written.
2. Review: the plan (every file, the files the builds share, the layout and the
   mod manager), or the refusal that names the file and the builds. The user
   gives a title and a new or empty output folder.
3. Writing: a worker writes the new mod and lists it in Drafts & Mods. The
   configured game folder is always passed, so an output inside the game is
   refused on every route. A cancel leaves no folder behind.
4. Done: the page refreshes and selects the new row.

The selected builds are never changed. The UI thread only shows dialogs.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cdmw.domain.packages.mesh_build_combine import LAYOUT_ARCHIVE_GROUP
from cdmw.services.mesh_saved_work_service import SavedWorkRow

COMMAND_ID = "saved_work.combine"
LABEL = "Combine into One Mod..."
REASON_TOO_FEW = "Select two or more built mods to combine them."
REASON_NOT_BUILT = "Select only built mods. Drafts and item packages cannot be combined."
REASON_MISSING = "A selected mod's folder no longer exists."
REASON_BUSY = "Wait for the current combine to finish."
ENABLED_TIP = "Write the selected built mods into one new mod. The selected mods are kept as they are."
STAGE_CHECKING = "checking"
STAGE_REVIEW = "review"
STAGE_REFUSED = "refused"
STAGE_WRITING = "writing"
STAGE_CANCELLING = "cancelling"


def combine_reason(rows: Sequence[SavedWorkRow], *, busy: bool = False) -> str:
    """Why the selected rows cannot be combined now; empty when they can."""

    if busy:
        return REASON_BUSY
    if any(not row.is_built_mod or row.is_item_package for row in rows):
        return REASON_NOT_BUILT
    if len(rows) < 2:
        return REASON_TOO_FEW
    if any(row.mod_root is None or not Path(row.mod_root).is_dir() for row in rows):
        return REASON_MISSING
    return ""


def layout_text(layout: str, manager: str) -> str:
    manager_name = "CDUMM" if str(manager).casefold() == "cdumm" else "DMM"
    if layout == LAYOUT_ARCHIVE_GROUP:
        return "DMM archive group (made from the game folder)"
    return f"Loose mod for {manager_name}"


def default_output_folder(rows: Sequence[SavedWorkRow], title: str) -> str:
    """Beside the first build, named after the title; the user can change it."""

    first = next((Path(row.mod_root) for row in rows if row.mod_root is not None), None)
    if first is None:
        return ""
    name = "".join("_" if char in '<>:"/\\|?*' else char for char in str(title or "").strip()).strip(" .")
    return str(first.parent / (name or "Combined mod"))


class _Relay(QObject):
    done = Signal(int, object, object, str, bool)
    message = Signal(int, str)


class SavedWorkCombineDialog(QDialog):
    """One dialog for every stage of Combine into One Mod."""

    combine_requested = Signal(str, str, bool)
    cancel_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SavedWorkCombineDialog")
        self.setWindowTitle("Combine into One Mod")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.stage = STAGE_CHECKING
        self._rows: tuple[SavedWorkRow, ...] = ()
        layout = QVBoxLayout(self)
        self.status_label = QLabel("", self)
        self.status_label.setObjectName("SavedWorkCombineStatus")
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status_label)
        self.plan_panel = QWidget(self)
        plan = QVBoxLayout(self.plan_panel)
        plan.setContentsMargins(0, 0, 0, 0)
        facts = QFormLayout()
        self.layout_value = QLabel("", self.plan_panel)
        self.layout_value.setObjectName("SavedWorkCombineLayout")
        self.layout_value.setWordWrap(True)
        facts.addRow("New mod", self.layout_value)
        plan.addLayout(facts)
        plan.addWidget(QLabel("Files in the new mod", self.plan_panel))
        self.files_list = QListWidget(self.plan_panel)
        self.files_list.setObjectName("SavedWorkCombineFiles")
        plan.addWidget(self.files_list, 1)
        self.shared_label = QLabel("Files more than one build carries, kept once", self.plan_panel)
        plan.addWidget(self.shared_label)
        self.shared_list = QListWidget(self.plan_panel)
        self.shared_list.setObjectName("SavedWorkCombineShared")
        plan.addWidget(self.shared_list)
        choices = QFormLayout()
        self.title_edit = QLineEdit(self.plan_panel)
        self.title_edit.setObjectName("SavedWorkCombineTitle")
        self.folder_edit = QLineEdit(self.plan_panel)
        self.folder_edit.setObjectName("SavedWorkCombineFolder")
        self.folder_edit.setPlaceholderText("A new or empty folder")
        self.browse_button = QPushButton("Browse...", self.plan_panel)
        self.browse_button.setObjectName("SavedWorkCombineBrowse")
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(self.browse_button)
        self.zip_check = QCheckBox("Also create a ZIP file", self.plan_panel)
        self.zip_check.setObjectName("SavedWorkCombineZip")
        choices.addRow("Title", self.title_edit)
        choices.addRow("Output folder", folder_row)
        choices.addRow("", self.zip_check)
        plan.addLayout(choices)
        layout.addWidget(self.plan_panel, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.combine_button = QPushButton("Combine", self)
        self.combine_button.setObjectName("EditorPrimaryButton")
        self.cancel_button = QPushButton("Cancel", self)
        self.cancel_button.setObjectName("SavedWorkCombineCancel")
        buttons.addWidget(self.combine_button)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)
        self.title_edit.textChanged.connect(self._sync_combine_button)
        self.folder_edit.textChanged.connect(self._sync_combine_button)
        self.browse_button.clicked.connect(self._browse)
        self.combine_button.clicked.connect(self._combine)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        self.show_checking(())

    # ----- stages --------------------------------------------------------------
    def show_checking(self, rows: Sequence[SavedWorkRow]) -> None:
        self.stage = STAGE_CHECKING
        self._rows = tuple(rows)
        self.status_label.setText(f"Checking {len(self._rows)} built mods. Nothing is written yet.")
        self.plan_panel.setVisible(False)
        self.combine_button.setVisible(False)
        self.cancel_button.setText("Cancel")
        self.cancel_button.setEnabled(True)

    def show_plan(self, prepared: object) -> None:
        plan = prepared.plan
        self.files_list.clear()
        for item, label in plan.files:
            self.files_list.addItem(f"{item.path}  ({label})")
        self.shared_list.clear()
        for path in plan.shared_companions:
            self.shared_list.addItem(str(path))
        self.shared_label.setVisible(bool(plan.shared_companions))
        self.shared_list.setVisible(bool(plan.shared_companions))
        self.layout_value.setText(layout_text(plan.layout, plan.manager_profile))
        if not plan.can_combine:
            self.stage = STAGE_REFUSED
            self.status_label.setText(str(prepared.refusal))
            self.plan_panel.setVisible(False)
            self.combine_button.setVisible(False)
            self.cancel_button.setText("Close")
            return
        self.stage = STAGE_REVIEW
        names = ", ".join(source.label for source in plan.sources)
        self.status_label.setText(
            f"These builds can be combined: {names}. Choose a title and a new or empty folder for the new mod."
        )
        if not self.title_edit.text().strip():
            self.title_edit.setText("Combined mod")
        if not self.folder_edit.text().strip():
            self.folder_edit.setText(default_output_folder(self._rows, self.title_edit.text()))
        self.plan_panel.setVisible(True)
        self.plan_panel.setEnabled(True)
        self.combine_button.setVisible(True)
        self.cancel_button.setText("Cancel")
        self._sync_combine_button()

    def show_writing(self) -> None:
        self.stage = STAGE_WRITING
        self.status_label.setText("Writing the combined mod...")
        self.plan_panel.setEnabled(False)
        self.combine_button.setEnabled(False)
        self.cancel_button.setEnabled(True)

    def show_cancelling(self) -> None:
        self.stage = STAGE_CANCELLING
        self.status_label.setText("Cancelling. Anything already written is removed.")
        self.cancel_button.setEnabled(False)
        self.combine_button.setEnabled(False)

    def show_error(self, message: str) -> None:
        """An export refusal or failure; the review stays so the user can change the folder."""

        self.stage = STAGE_REVIEW
        self.status_label.setText(f"The mod was not written: {message}")
        self.plan_panel.setEnabled(True)
        self.cancel_button.setEnabled(True)
        self.cancel_button.setText("Cancel")
        self._sync_combine_button()

    # ----- choices -------------------------------------------------------------
    def _sync_combine_button(self, _text: str = "") -> None:
        ready = (self.stage == STAGE_REVIEW and bool(self.title_edit.text().strip())
                 and bool(self.folder_edit.text().strip()))
        self.combine_button.setEnabled(ready)

    def _browse(self) -> None:
        start = str(Path(self.folder_edit.text().strip()).parent) if self.folder_edit.text().strip() else ""
        folder = QFileDialog.getExistingDirectory(self, "Choose a new or empty folder for the combined mod", start)
        if folder:
            self.folder_edit.setText(folder)

    def _combine(self) -> None:
        if self.combine_button.isEnabled():
            self.combine_requested.emit(self.title_edit.text().strip(), self.folder_edit.text().strip(),
                                        self.zip_check.isChecked())

    def reject(self) -> None:
        # Escape and the window's close button are a Cancel.
        self.cancel_requested.emit()


class SavedWorkCombineFlow(QObject):
    """Runs Combine into One Mod for a Drafts & Mods page.

    ``game_root`` returns the configured game folder ("" when none is set).
    ``list_entries`` lists the game's catalogue for the archive-group route; the
    default reads the package tables in the worker.
    """

    finished = Signal(object)
    status_message = Signal(str, bool)
    busy_changed = Signal(bool)

    def __init__(
        self,
        parent: QWidget,
        *,
        draft_root: Callable[[], Path],
        game_root: Callable[[], str],
        list_entries: Callable | None = None,
    ) -> None:
        super().__init__(parent)
        self._parent = parent
        self._draft_root = draft_root
        self._game_root = game_root
        self._list_entries = list_entries
        self._relay = _Relay(self)
        self._relay.done.connect(self._worker_done)
        self._relay.message.connect(self._worker_message)
        self._generation = 0
        self._stop: threading.Event | None = None
        self._running = False
        self._rows: tuple[SavedWorkRow, ...] = ()
        self._prepared: object = None
        self.dialog: SavedWorkCombineDialog | None = None

    @property
    def busy(self) -> bool:
        return self.dialog is not None

    def start(self, rows: Sequence[SavedWorkRow]) -> bool:
        rows = tuple(rows)
        if combine_reason(rows, busy=self.busy):
            return False
        from cdmw.workers.mesh_build_combine_workers import mesh_build_combine_prepare_task

        self._rows, self._prepared = rows, None
        dialog = SavedWorkCombineDialog(self._parent)
        dialog.combine_requested.connect(self._export)
        dialog.cancel_requested.connect(self.cancel)
        dialog.show_checking(rows)
        self.dialog = dialog
        self.busy_changed.emit(True)
        dialog.open()
        self._launch(mesh_build_combine_prepare_task(rows), self._prepared_done)
        return True

    def cancel(self) -> None:
        """Cancel at any stage. A running worker is stopped and its output removed."""

        dialog = self.dialog
        if dialog is None:
            return
        if dialog.stage == STAGE_REFUSED:
            self._close(None, dialog.status_label.text(), error=True)
            return
        if self._running and self._stop is not None:
            self._stop.set()
            if dialog.stage == STAGE_WRITING:
                # The writer removes what it wrote; close once it has returned.
                dialog.show_cancelling()
                return
        self._close(None, "Combine into One Mod was cancelled. Nothing was written.")

    # ----- workers -------------------------------------------------------------
    def _launch(self, task: Callable, on_done: Callable[[object, str, bool], None]) -> None:
        from cdmw.domain.cancellation import RunCancelled

        self._generation += 1
        generation, relay = self._generation, self._relay
        stop = threading.Event()
        self._stop, self._running = stop, True

        def log(message: str) -> None:
            try:
                relay.message.emit(generation, str(message or ""))
            except RuntimeError:
                pass

        def run() -> None:
            cancelled = False
            try:
                result, error = task(log, stop), ""
            except RunCancelled as exc:
                result, error, cancelled = None, str(exc), True
            except Exception as exc:  # noqa: BLE001 - shown to the user, never raised on the UI thread
                result, error = None, str(exc) or type(exc).__name__
            cancelled = cancelled or stop.is_set()
            try:
                relay.done.emit(generation, on_done, result, error, cancelled)
            except RuntimeError:
                pass  # The page closed while this ran.

        threading.Thread(target=run, name="mesh-saved-work-combine", daemon=True).start()

    def _worker_message(self, generation: int, message: str) -> None:
        dialog = self.dialog
        if int(generation) == self._generation and dialog is not None and message                 and dialog.stage in (STAGE_CHECKING, STAGE_WRITING):
            dialog.status_label.setText(message)

    def _worker_done(self, generation: int, on_done: object, result: object, error: str, cancelled: bool) -> None:
        if int(generation) != self._generation:
            return
        self._running = False
        if callable(on_done):
            on_done(result, error, bool(cancelled))

    def _prepared_done(self, result: object, error: str, cancelled: bool) -> None:
        dialog = self.dialog
        if dialog is None or cancelled:
            return
        if error:
            self._close(None, f"The selected mods could not be checked: {error}", error=True)
            return
        self._prepared = result
        dialog.show_plan(result)

    def _export(self, title: str, folder: str, create_zip: bool) -> None:
        dialog = self.dialog
        if dialog is None or self._prepared is None or self._running:
            return
        from cdmw.workers.mesh_build_combine_workers import mesh_build_combine_export_task

        dialog.show_writing()
        task = mesh_build_combine_export_task(
            self._prepared, Path(folder), title=title, draft_root=self._draft_root(), rows=self._rows,
            game_root=str(self._game_root() or "").strip() or None, create_zip=create_zip,
            list_entries=self._list_entries,
        )
        self._launch(task, self._exported)

    def _exported(self, result: object, error: str, cancelled: bool) -> None:
        dialog = self.dialog
        if dialog is None:
            return
        if cancelled:
            self._close(None, "Combine into One Mod was cancelled. Nothing was written.")
            return
        if error:
            dialog.show_error(error)
            return
        output = getattr(getattr(result, "result", None), "output_path", "")
        self._close(result, f"Combined mod written: {output}")

    def _close(self, result: object, message: str, *, error: bool = False) -> None:
        dialog, self.dialog = self.dialog, None
        self._generation += 1
        self._prepared = None
        self._running = False
        if dialog is not None:
            dialog.hide()
            dialog.deleteLater()
        self.busy_changed.emit(False)
        self.status_message.emit(message, error)
        self.finished.emit(result)


__all__ = [
    "COMMAND_ID",
    "LABEL",
    "SavedWorkCombineDialog",
    "SavedWorkCombineFlow",
    "combine_reason",
    "default_output_folder",
    "layout_text",
]
