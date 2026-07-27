"""Archive Browser action that opens the Prefab Inspector."""

from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import QMessageBox

from cdmw.domain.archives.mesh_contracts import ArchiveLooseExportResult
from cdmw.models import ArchiveEntry
from cdmw.services.archive_mutation_service import ArchivePatchRequest
from cdmw.services.archive_read_service import read_archive_entry_data
from cdmw.services.archive_workflow_service import export_archive_payloads_to_mod_ready_loose
from cdmw.ui.archive_browser.prefab_inspector_dialog import PrefabInspectorDialog


class ArchivePrefabInspectorActionsMixin:
    """Open a decoded view of a prefab and write retargeted copies out."""

    def _open_current_archive_prefab_inspector(self) -> None:
        entry = self._current_archive_prefab_entry()
        if entry is None:
            self.set_status_message("Select a .prefab archive entry before opening the inspector.", error=True)
            return
        try:
            data, _decompressed, _note = read_archive_entry_data(entry)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            self.set_status_message(f"Could not read {entry.path}: {exc}", error=True)
            return

        dialog = PrefabInspectorDialog(data, title=f"Prefab Inspector - {entry.basename}", parent=self)
        dialog.exec()
        payload = dialog.result_payload
        if payload is None or payload.data == data:
            return
        if QMessageBox.question(
            self,
            "Export Edited Prefab",
            f"{payload.summary}\n\nWrite the edited prefab into a loose mod package?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        ) != QMessageBox.Yes:
            return
        self._export_inspected_prefab(entry, payload.data, payload.summary)

    def _export_inspected_prefab(self, entry: ArchiveEntry, patched: bytes, summary: str) -> None:
        export_target = self._collect_archive_mod_ready_export_target(
            browse_title="Choose Prefab Export Root",
            prompt_for_metadata=True,
            dialog_title="Build Prefab Package",
            allow_dmm_texture_structure=False,
            initial_package_title="Prefab Edit",
            initial_package_description=f"CDMW prefab path edit for {entry.path}",
        )
        if export_target is None:
            return
        export_root, package_info, create_no_encrypt_file, _include_related, export_options = export_target

        def _task(log: Callable[[str], None]) -> ArchiveLooseExportResult:
            log(f"Source prefab: {entry.path}")
            log(summary)
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
                self.set_status_message("Prefab export finished with an unexpected result payload.", error=True)
                return
            QMessageBox.information(
                self,
                "Prefab Package Complete",
                f"Wrote prefab loose package into:\n{result.package_root}",
            )
            self.set_status_message(f"Wrote prefab loose package: {result.package_root}")

        self._run_utility_task_when_idle(
            status_message=f"Building prefab package for {entry.basename}...",
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
        )


__all__ = ["ArchivePrefabInspectorActionsMixin"]
