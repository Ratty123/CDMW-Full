"""Archive Browser prefab edit JSON actions."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Callable

from PySide6.QtWidgets import QFileDialog, QMessageBox

from cdmw.services.archive_workflow_service import export_archive_payloads_to_mod_ready_loose
from cdmw.domain.archives.mesh_contracts import ArchiveLooseExportResult
from cdmw.domain.archives.prefab import PrefabEditJsonError
from cdmw.services.archive_workflow_service import apply_prefab_edit_json, dumps_prefab_edit_json
from cdmw.models import ArchiveEntry
from cdmw.services.archive_mutation_service import ArchivePatchRequest
from cdmw.services.archive_read_service import read_archive_entry_data


class ArchivePrefabJsonActionsMixin:
    """Export/import the stable CDMW prefab edit JSON format."""

    def _current_archive_prefab_entry(self) -> ArchiveEntry | None:
        if self.archive_preview_showing_loose:
            return None
        selected = self._current_archive_entry()
        return selected if isinstance(selected, ArchiveEntry) and str(selected.extension or "").lower() == ".prefab" else None

    def _default_archive_prefab_edit_json_path(self, entry: ArchiveEntry) -> Path:
        default_dir = self.settings_file_path.parent / "prefab_edit_json"
        stem = Path(PurePosixPath(entry.path.replace("\\", "/")).name).stem or "prefab"
        return default_dir / f"{stem}.prefab-edit.json"

    def _export_current_archive_prefab_edit_json(self) -> None:
        entry = self._current_archive_prefab_entry()
        if entry is None:
            self.set_status_message("Select a .prefab archive entry before exporting Prefab Edit JSON.", error=True)
            return
        selected, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Prefab Edit JSON",
            str(self._default_archive_prefab_edit_json_path(entry)),
            "Prefab Edit JSON (*.prefab-edit.json *.json);;JSON (*.json)",
        )
        if not selected:
            return
        output_path = Path(selected)
        if not output_path.suffix:
            output_path = output_path.with_name(f"{output_path.name}.prefab-edit.json")

        def _task(log: Callable[[str], None]) -> Path:
            log(f"Reading prefab payload: {entry.path}")
            data, _decompressed, _note = read_archive_entry_data(entry)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(dumps_prefab_edit_json(data, entry.path), encoding="utf-8")
            return output_path

        def _handle_complete(result: object) -> None:
            exported = result if isinstance(result, Path) else output_path
            QMessageBox.information(
                self,
                "Prefab Edit JSON Export Complete",
                f"Wrote editable Prefab JSON:\n{exported}\n\nOnly same-length resource and placement edits are importable in V1.",
            )
            self.set_status_message(f"Exported Prefab Edit JSON for {entry.basename}.")

        self._run_utility_task(
            status_message=f"Exporting Prefab Edit JSON for {entry.basename}...",
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
        )

    def _import_current_archive_prefab_edit_json(self) -> None:
        entry = self._current_archive_prefab_entry()
        if entry is None:
            self.set_status_message("Select a .prefab archive entry before importing Prefab Edit JSON.", error=True)
            return
        selected, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Import Prefab Edit JSON",
            str(self._default_archive_prefab_edit_json_path(entry)),
            "Prefab Edit JSON (*.prefab-edit.json *.json);;JSON (*.json)",
        )
        if not selected:
            return
        document_path = Path(selected)
        if QMessageBox.question(
            self,
            "Build Prefab Edit Package",
            (
                f"Build a loose mod package for edited prefab?\n\n{entry.path}\n\n"
                "Original game archives will not be modified."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        export_target = self._collect_archive_mod_ready_export_target(
            browse_title="Choose Prefab Edit Package Export Root",
            prompt_for_metadata=True,
            dialog_title="Build Prefab Edit Package",
            allow_dmm_texture_structure=False,
            initial_package_title="Prefab Edit",
            initial_package_description=f"CDMW same-length prefab edit package for {entry.path}",
        )
        if export_target is None:
            return
        export_root, package_info, create_no_encrypt_file, _include_related, export_options = export_target

        def _task(log: Callable[[str], None]) -> ArchiveLooseExportResult:
            log(f"Reading source prefab: {entry.path}")
            data, _decompressed, _note = read_archive_entry_data(entry)
            log(f"Applying Prefab Edit JSON: {document_path}")
            try:
                patched = apply_prefab_edit_json(data, document_path.read_text(encoding="utf-8"), virtual_path=entry.path)
            except PrefabEditJsonError as exc:
                raise ValueError(str(exc)) from exc
            if patched == data:
                log("Prefab Edit JSON made no byte changes; writing unchanged payload for review.")
            else:
                log(f"Prefab payload changed: {len(data):,} byte(s), size preserved.")
            return export_archive_payloads_to_mod_ready_loose(
                [ArchivePatchRequest(entry, patched)],
                parent_root=export_root,
                package_info=package_info,
                export_options=export_options,
                create_no_encrypt_file=create_no_encrypt_file,
                on_log=log,
            )

        def _handle_complete(result: object) -> None:
            if not isinstance(result, ArchiveLooseExportResult):
                self.set_status_message("Prefab Edit JSON import finished with an unexpected result payload.", error=True)
                return
            QMessageBox.information(
                self,
                "Prefab Edit Package Complete",
                f"Wrote prefab edit loose package into:\n{result.package_root}",
            )
            self.set_status_message(f"Wrote prefab edit loose package: {result.package_root}")

        self._run_utility_task_when_idle(
            status_message=f"Building Prefab Edit package for {entry.basename}...",
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
        )


__all__ = ["ArchivePrefabJsonActionsMixin"]
