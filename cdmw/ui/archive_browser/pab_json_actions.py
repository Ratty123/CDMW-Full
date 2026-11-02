"""Archive Browser skeleton actions for .pab entries: Add Bones and Skeleton Edit JSON."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path, PurePosixPath

from PySide6.QtWidgets import QFileDialog, QMessageBox

from cdmw.domain.archives.mesh_contracts import ArchiveLooseExportResult
from cdmw.models import ArchiveEntry
from cdmw.services.archive_mutation_service import ArchivePatchRequest
from cdmw.services.archive_read_service import read_archive_entry_data
from cdmw.services.archive_workflow_service import (
    export_archive_payloads_to_mod_ready_loose,
)
from cdmw.services.pab_skeleton_edit_service import (
    PabEditOutcome,
    apply_pab_edit_json,
    apply_pab_edits,
    dumps_pab_edit_json,
)


class ArchivePabJsonActionsMixin:
    """Add bones to a skeleton, by dialog or Skeleton Edit JSON, and write them as a loose mod."""

    def _current_archive_pab_entry(self) -> ArchiveEntry | None:
        if self.archive_preview_showing_loose:
            return None
        selected = self._current_archive_entry()
        return selected if isinstance(selected, ArchiveEntry) and str(selected.extension or "").lower() == ".pab" else None

    def _default_archive_pab_edit_json_path(self, entry: ArchiveEntry) -> Path:
        default_dir = self.shell.settings_file_path.parent / "skeleton_edit_json"
        stem = Path(PurePosixPath(entry.path.replace("\\", "/")).name).stem or "skeleton"
        return default_dir / f"{stem}.skeleton-edit.json"

    def _open_current_archive_pab_bone_editor(self) -> None:
        entry = self._current_archive_pab_entry()
        if entry is None:
            self.shell.set_status_message("Select a .pab archive entry before adding bones.", error=True)
            return

        def _task(log: Callable[[str], None]) -> bytes:
            log(f"Reading skeleton: {entry.path}")
            data, _decompressed, _note = read_archive_entry_data(entry)
            return data

        def _handle_complete(result: object) -> None:
            if not isinstance(result, (bytes, bytearray)):
                self.shell.set_status_message("Skeleton Edit JSON import finished with an unexpected result payload.", error=True)
                return
            self._show_pab_bone_editor(entry, bytes(result))

        self.shell._run_utility_task(
            status_message=f"Reading skeleton: {entry.path}",
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
        )

    def _show_pab_bone_editor(self, entry: ArchiveEntry, data: bytes) -> None:
        from cdmw.ui.archive_browser.pab_bone_editor_dialog import PabBoneEditorDialog

        dialog = PabBoneEditorDialog(
            data, entry.path, self, draft_directory=self._default_archive_pab_edit_json_path(entry).parent)
        if dialog.exec() != PabBoneEditorDialog.Accepted:
            return
        edits = dialog.edits()
        if not edits:
            return

        def _task(log: Callable[[str], None]) -> PabEditOutcome:
            log(f"Applying Skeleton Edit JSON to {entry.basename}...")
            return apply_pab_edits(data, edits, path=entry.path)

        self.shell._run_utility_task(
            status_message=f"Applying Skeleton Edit JSON to {entry.basename}...",
            task=_task,
            on_complete=lambda result: (
                self._write_pab_edit_loose_mod(entry, result) if isinstance(result, PabEditOutcome)
                else self.shell.set_status_message(
                    "Skeleton Edit JSON import finished with an unexpected result payload.", error=True)),
            show_archive_progress=True,
        )

    def _export_current_archive_pab_edit_json(self) -> None:
        entry = self._current_archive_pab_entry()
        if entry is None:
            self.shell.set_status_message("Select a .pab archive entry before exporting Skeleton Edit JSON.", error=True)
            return
        selected, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Skeleton Edit JSON",
            str(self._default_archive_pab_edit_json_path(entry)),
            "Skeleton Edit JSON (*.skeleton-edit.json *.json);;JSON (*.json)",
        )
        if not selected:
            return
        output_path = Path(selected)
        if not output_path.suffix:
            output_path = output_path.with_name(f"{output_path.name}.skeleton-edit.json")

        def _task(log: Callable[[str], None]) -> Path:
            log(f"Reading skeleton: {entry.path}")
            data, _decompressed, _note = read_archive_entry_data(entry)
            text = dumps_pab_edit_json(data, entry.path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(text, encoding="utf-8")
            return output_path

        def _handle_complete(result: object) -> None:
            exported = result if isinstance(result, Path) else output_path
            QMessageBox.information(
                self,
                "Skeleton Edit JSON Export Complete",
                f"Wrote Skeleton Edit JSON:\n{exported}\n\n"
                "Add new child bones under add_bones, then use Import Skeleton Edit JSON. "
                "Existing bones cannot be renamed, removed or reordered.",
            )
            self.shell.set_status_message(f"Exported Skeleton Edit JSON for {entry.basename}.")

        self.shell._run_utility_task(
            status_message=f"Exporting Skeleton Edit JSON for {entry.basename}...",
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
        )

    def _import_current_archive_pab_edit_json(self) -> None:
        entry = self._current_archive_pab_entry()
        if entry is None:
            self.shell.set_status_message("Select a .pab archive entry before importing Skeleton Edit JSON.", error=True)
            return
        selected, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Import Skeleton Edit JSON",
            str(self._default_archive_pab_edit_json_path(entry)),
            "Skeleton Edit JSON (*.skeleton-edit.json *.json);;JSON (*.json)",
        )
        if not selected:
            return
        document_path = Path(selected)

        def _task(log: Callable[[str], None]) -> PabEditOutcome:
            log(f"Reading skeleton: {entry.path}")
            data, _decompressed, _note = read_archive_entry_data(entry)
            log(f"Applying Skeleton Edit JSON to {entry.basename}...")
            return apply_pab_edit_json(data, document_path.read_text(encoding="utf-8"), virtual_path=entry.path)

        def _handle_complete(result: object) -> None:
            if not isinstance(result, PabEditOutcome):
                self.shell.set_status_message("Skeleton Edit JSON import finished with an unexpected result payload.", error=True)
                return
            if not result.appended:
                QMessageBox.information(
                    self,
                    "Import Skeleton Edit JSON",
                    "The document adds no bones, so no loose mod was written.",
                )
                self.shell.set_status_message("The document adds no bones, so no loose mod was written.")
                return
            # Choose the output only now that the edit is known to apply.
            self._write_pab_edit_loose_mod(entry, result)

        self.shell._run_utility_task_when_idle(
            status_message=f"Applying Skeleton Edit JSON to {entry.basename}...",
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
        )

    def _write_pab_edit_loose_mod(self, entry: ArchiveEntry, outcome: PabEditOutcome) -> None:
        target = self._collect_archive_mod_ready_export_target(
            browse_title="Select Mod-Ready Export Parent Root",
            prompt_for_metadata=True,
            allow_dmm_texture_structure=False,
        )
        if target is None:
            return
        parent_root, package_info, create_no_encrypt_file, _include_related_files, export_options = target

        def _task(log: Callable[[str], None]) -> ArchiveLooseExportResult:
            log(f"Writing skeleton loose mod for {entry.basename}...")
            return export_archive_payloads_to_mod_ready_loose(
                [ArchivePatchRequest(entry=entry, payload_data=outcome.data)],
                parent_root=parent_root,
                package_info=package_info,
                export_options=export_options,
                create_no_encrypt_file=create_no_encrypt_file,
                on_log=log,
            )

        def _handle_complete(result: object) -> None:
            if not isinstance(result, ArchiveLooseExportResult):
                self.shell.set_status_message("Skeleton Edit JSON import finished with an unexpected result payload.", error=True)
                return
            QMessageBox.information(
                self,
                "Skeleton Edit JSON Import Complete",
                f"Wrote edited skeleton loose mod package:\n{result.package_root}\n\n"
                f"Target entry:\n{entry.path}\n\n"
                f"Bones: {outcome.source_bone_count:,} -> {outcome.bone_count:,}\n"
                f"Added: {', '.join(outcome.appended)}\n\n"
                "A mesh can weight vertices to a new bone only after its bone palette lists it. "
                "New bones have no animation, collision or physics, so they follow their parent. "
                "Added bones are untested in game. The installed game archives were not modified.",
            )
            self.shell.set_status_message(f"Wrote skeleton edits for {entry.basename} as a mod-ready loose package.")

        self.shell._run_utility_task(
            status_message=f"Writing skeleton loose mod for {entry.basename}...",
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
        )


__all__ = ["ArchivePabJsonActionsMixin"]
