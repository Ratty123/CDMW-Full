"""Archive Browser actions for the HKX Physics Editor.

Reading the HKX, building edits and writing output run in the shell's
utility worker; the dialog only holds the edits. Results that arrive after
the dialog closed are dropped.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from cdmw.core.archive_hkx_tagfile_model import HkxTagfileRefused
from cdmw.domain.archives.mesh_contracts import ArchiveLooseExportResult
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.models import ArchiveEntry
from cdmw.services.active_ui_translation import translate_active_ui_text
from cdmw.services.archive_mutation_service import ArchivePatchRequest
from cdmw.services.archive_preview_service import ensure_archive_preview_source
from cdmw.services.archive_workflow_service import (
    export_archive_payloads_to_mod_ready_loose,
)
from cdmw.services.atomic_file_service import atomic_write_bytes
from cdmw.services.cancellable_file_service import read_file_bytes_cancellable
from cdmw.services.hkx_physics_editor_service import (
    HkxPhysicsEdits,
    build_hkx_physics_edit,
    check_hkx_collision_replacement,
    load_hkx_physics_session,
)
from cdmw.ui.archive_browser.hkx_physics_editor_dialog import HkxPhysicsEditorDialog

_REPLACEMENT_LIST_LIMIT = 500
_ENTRY_ROLE = int(Qt.ItemDataRole.UserRole)


class _Refused:
    """A refused edit is an expected outcome, not a worker crash."""

    def __init__(self, message: str) -> None:
        self.message = message


def _entry_family_prefix(path: str) -> str:
    parts = path.replace("\\", "/").casefold().split("/")
    return "/".join(parts[:3])


def hkx_replacement_candidates(
    entries: Sequence[ArchiveEntry], entry: ArchiveEntry, stop_event: Optional[threading.Event] = None
) -> List[Tuple[str, ArchiveEntry]]:
    """Other .hkx entries in the same top three folders, as (casefolded path, entry), sorted.

    Runs in the utility worker: a full archive scan holds over a million entries.
    """

    prefix = _entry_family_prefix(str(entry.path))
    own = str(entry.path).replace("\\", "/").casefold()
    candidates = []
    for index, candidate in enumerate(entries):
        if stop_event is not None and index % 50_000 == 0:
            raise_if_cancelled(stop_event, "Collision file search cancelled.")
        path = str(candidate.path).replace("\\", "/").casefold()
        if path.endswith(".hkx") and path != own and _entry_family_prefix(path) == prefix:
            candidates.append((path, candidate))
    candidates.sort(key=lambda pair: pair[0])
    return candidates


class ArchiveHkxPhysicsEditorMixin:
    """Opens the HKX Physics Editor and runs its reads and saves off the UI thread."""

    def _open_current_hkx_physics_editor(self) -> None:
        entry = self._current_archive_hkx_entry()
        if entry is None:
            self.shell.set_status_message("Select a Crimson Desert .hkx archive entry to edit its physics.", error=True)
            return
        self._open_hkx_physics_editor_for_entry(entry)

    def _read_hkx_entry_bytes(self, entry: ArchiveEntry, stop_event: threading.Event) -> bytes:
        source_path, _note = ensure_archive_preview_source(entry)
        return read_file_bytes_cancellable(source_path, stop_event=stop_event)

    def _open_hkx_physics_editor_for_entry(self, entry: ArchiveEntry) -> None:
        def _task(log: Callable[[str], None], stop_event: threading.Event) -> object:
            log(f"Reading {entry.path} for the HKX Physics Editor...")
            data = self._read_hkx_entry_bytes(entry, stop_event)
            raise_if_cancelled(stop_event, "HKX Physics Editor cancelled.")
            return load_hkx_physics_session(data, str(entry.path).replace("\\", "/"))

        def _handle_complete(session: object) -> None:
            dialog = HkxPhysicsEditorDialog(
                self,
                session,
                on_save_mod=lambda owner, edits: self._save_hkx_physics_mod(owner, entry, edits),
                on_save_file=lambda owner, edits: self._save_hkx_physics_file(owner, entry, edits),
                on_pick_replacement=lambda owner: self._pick_hkx_collision_replacement(owner, entry),
            )
            self._hkx_physics_editor_dialog = dialog
            dialog.show()
            self.shell.set_status_message(f"Opened the HKX Physics Editor for {entry.basename}.")

        self.shell._run_utility_task(
            status_message=f"Opening the HKX Physics Editor for {entry.basename}...",
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
            task_accepts_cancel=True,
        )

    # Collision replacement --------------------------------------------------------------

    def _pick_hkx_collision_replacement(self, dialog: HkxPhysicsEditorDialog, entry: ArchiveEntry) -> None:
        # Only the list reference is taken here; filtering the full scan runs in the worker.
        entries = tuple(getattr(self, "archive_entries", ()) or ())

        def _task(log: Callable[[str], None], stop_event: threading.Event) -> object:
            return hkx_replacement_candidates(entries, entry, stop_event)

        def _handle_complete(candidates: object) -> None:
            if dialog.closed:
                return
            if not candidates:
                QMessageBox.information(dialog, "Use Another File's Collision", "No other collision files of this kind are in the scanned archives.")
                return
            chosen = self._choose_hkx_replacement_entry(dialog, candidates)
            if chosen is not None and not dialog.closed:
                self._check_hkx_collision_replacement(dialog, chosen)

        self.shell._run_utility_task(
            status_message=f"Finding collision files like {entry.basename}...",
            task=_task,
            on_complete=_handle_complete,
            task_accepts_cancel=True,
        )

    def _check_hkx_collision_replacement(self, dialog: HkxPhysicsEditorDialog, chosen: ArchiveEntry) -> None:

        def _task(log: Callable[[str], None], stop_event: threading.Event) -> object:
            log(f"Checking {chosen.path} as replacement collision...")
            data = self._read_hkx_entry_bytes(chosen, stop_event)
            ok, reason = check_hkx_collision_replacement(dialog.session, data)
            return (ok, reason, data)

        def _handle_complete(result: object) -> None:
            if dialog.closed:
                return
            ok, reason, data = result
            if not ok:
                QMessageBox.warning(dialog, "Use Another File's Collision", translate_active_ui_text(f"This file cannot be used: {reason}"))
                return
            dialog.set_replacement(str(chosen.path).replace("\\", "/"), data)

        self.shell._run_utility_task_when_idle(
            status_message=f"Checking {chosen.basename} as replacement collision...",
            task=_task,
            on_complete=_handle_complete,
            task_accepts_cancel=True,
        )

    def _choose_hkx_replacement_entry(
        self, parent: QDialog, candidates: Sequence[Tuple[str, ArchiveEntry]]
    ) -> Optional[ArchiveEntry]:
        picker = QDialog(parent)
        picker.setWindowTitle("Choose Collision File")
        picker.resize(760, 520)
        layout = QVBoxLayout(picker)
        hint = QLabel("Type part of an item or folder name, then pick the file whose collision you want.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        search = QLineEdit()
        search.setPlaceholderText("Filter by path, for example sword_0109")
        layout.addWidget(search)
        listing = QListWidget()
        layout.addWidget(listing, 1)
        count_label = QLabel()
        count_label.setObjectName("HintLabel")
        layout.addWidget(count_label)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        use_button = QPushButton("Use Selected")
        cancel_button = QPushButton("Cancel")
        buttons.addWidget(use_button)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)

        def refill(text: str) -> None:
            needle = text.strip().casefold()
            matches = [candidate for key, candidate in candidates if needle in key]
            listing.clear()
            for candidate in matches[:_REPLACEMENT_LIST_LIMIT]:
                item = QListWidgetItem(str(candidate.path).replace("\\", "/"))
                item.setData(_ENTRY_ROLE, candidate)
                listing.addItem(item)
            shown = min(len(matches), _REPLACEMENT_LIST_LIMIT)
            count_label.setText(translate_active_ui_text(f"Showing {shown} of {len(matches)} matching files."))
            use_button.setEnabled(listing.count() > 0)
            if listing.count():
                listing.setCurrentRow(0)

        search.textChanged.connect(refill)
        use_button.clicked.connect(picker.accept)
        cancel_button.clicked.connect(picker.reject)
        listing.itemDoubleClicked.connect(lambda _item: picker.accept())
        refill("")
        if picker.exec() != QDialog.DialogCode.Accepted or listing.currentItem() is None:
            return None
        return listing.currentItem().data(_ENTRY_ROLE)

    # Saving -----------------------------------------------------------------------------

    def _report_hkx_physics_refusal(self, dialog: HkxPhysicsEditorDialog, message: str) -> None:
        self.shell.set_status_message(f"HKX Physics Editor: nothing was saved ({message})", error=True)
        if dialog.closed:
            return
        QMessageBox.warning(
            dialog,
            "HKX Physics Editor",
            translate_active_ui_text(f"Nothing was saved. CDMW refused the change: {message}"),
        )

    def _save_hkx_physics_file(self, dialog: HkxPhysicsEditorDialog, entry: ArchiveEntry, edits: HkxPhysicsEdits) -> None:
        target, _filter = QFileDialog.getSaveFileName(dialog, "Save Edited HKX File", entry.basename, "HKX files (*.hkx)")
        if not target:
            return
        target_path = Path(target)

        def _task(log: Callable[[str], None], stop_event: threading.Event) -> object:
            data = self._read_hkx_entry_bytes(entry, stop_event)
            try:
                result = build_hkx_physics_edit(data, edits, str(entry.path))
            except HkxTagfileRefused as exc:
                return _Refused(str(exc))
            raise_if_cancelled(stop_event, "HKX save cancelled.")
            atomic_write_bytes(target_path, result.data)
            log(f"Wrote edited HKX file {target_path}.")
            return result

        def _handle_complete(result: object) -> None:
            if isinstance(result, _Refused):
                self._report_hkx_physics_refusal(dialog, result.message)
                return
            self.shell.set_status_message(f"Saved the edited HKX file for {entry.basename}.")
            if not dialog.closed:
                QMessageBox.information(dialog, "HKX File Saved", dialog.show_saved(result, str(target_path)))

        self.shell._run_utility_task(
            status_message=f"Saving the edited HKX file for {entry.basename}...",
            task=_task,
            on_complete=_handle_complete,
            task_accepts_cancel=True,
        )

    def _save_hkx_physics_mod(self, dialog: HkxPhysicsEditorDialog, entry: ArchiveEntry, edits: HkxPhysicsEdits) -> None:
        settings = self._collect_archive_mod_ready_export_target(
            browse_title="Select HKX Mod Export Folder",
            prompt_for_metadata=True,
            dialog_title="HKX Physics Mod",
            allow_dmm_texture_structure=False,
            initial_package_title=f"{Path(entry.basename).stem} physics",
            parent=dialog,
        )
        if settings is None:
            return
        parent_root, package_info, create_no_encrypt_file, _include_related, export_options = settings

        def _task(log: Callable[[str], None], stop_event: threading.Event) -> object:
            data = self._read_hkx_entry_bytes(entry, stop_event)
            try:
                result = build_hkx_physics_edit(data, edits, str(entry.path))
            except HkxTagfileRefused as exc:
                return _Refused(str(exc))
            raise_if_cancelled(stop_event, "HKX mod export cancelled.")
            export = export_archive_payloads_to_mod_ready_loose(
                [ArchivePatchRequest(entry=entry, payload_data=result.data)],
                parent_root=parent_root,
                package_info=package_info,
                export_options=export_options,
                create_no_encrypt_file=create_no_encrypt_file,
                on_log=log,
            )
            return result, export

        def _handle_complete(payload: object) -> None:
            if isinstance(payload, _Refused):
                self._report_hkx_physics_refusal(dialog, payload.message)
                return
            result, export = payload
            root = export.package_root if isinstance(export, ArchiveLooseExportResult) else parent_root
            self.shell.set_status_message(f"Wrote an HKX physics mod for {entry.basename}.")
            if not dialog.closed:
                QMessageBox.information(dialog, "HKX Physics Mod Saved", dialog.show_saved(result, str(root)))

        self.shell._run_utility_task(
            status_message=f"Writing an HKX physics mod for {entry.basename}...",
            task=_task,
            on_complete=_handle_complete,
            task_accepts_cancel=True,
        )


__all__ = ["ArchiveHkxPhysicsEditorMixin"]
