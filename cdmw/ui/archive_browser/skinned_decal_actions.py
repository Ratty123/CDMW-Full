"""Archive action wiring; file parsing and saving use the utility worker."""
from pathlib import Path, PurePosixPath

from PySide6.QtWidgets import QDialog, QFileDialog

from cdmw.services.skinned_decal_service import DecalEditSource, DecalSaveRequest, load_decal_source, save_decal_copy
from cdmw.ui.archive_browser.skinned_decal_dialog import SkinnedDecalDialog
from cdmw.ui.archive_browser.workflow_dependencies import (
    ArchiveWorkflowDependenciesUnavailable, archive_workflow_dependency_context,
)


class SkinnedDecalActionsMixin:
    def _edit_archive_skinned_decal(self, entry):
        try:
            entry = archive_workflow_dependency_context(self, entry).selected_entry
        except ArchiveWorkflowDependenciesUnavailable as exc:
            self.shell.set_status_message(str(exc), error=True)
            return
        request_id = int(getattr(self, "_skinned_decal_request_id", 0)) + 1
        self._skinned_decal_request_id = request_id
        self.shell._run_utility_task(
            status_message="Reading skinned decal sequence...",
            task=lambda _log, stop_event: load_decal_source(entry, stop_event=stop_event),
            on_complete=lambda result: self._show_skinned_decal_editor(request_id, result),
            task_accepts_cancel=True,
        )

    def _show_skinned_decal_editor(self, request_id, result):
        if request_id != getattr(self, "_skinned_decal_request_id", None) or not isinstance(result, DecalEditSource):
            return
        dialog = SkinnedDecalDialog(result.document, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if request_id != getattr(self, "_skinned_decal_request_id", None):
            return
        default = self.shell.settings_file_path.parent / "structured_edits" / PurePosixPath(result.entry.path.replace("\\", "/")).name
        selected, _ = QFileDialog.getSaveFileName(self, "Save Decal Sequence Copy", str(default), "PASEQ (*.paseq)")
        if not selected or request_id != getattr(self, "_skinned_decal_request_id", None):
            return
        request = DecalSaveRequest(result.document, Path(selected), dialog.changes())
        self._skinned_decal_request_id = request_id + 1
        self.shell._run_utility_task_when_idle(
            status_message="Saving decal sequence copy...",
            task=lambda _log, stop_event: save_decal_copy(request, stop_event=stop_event),
            on_complete=lambda path: self._skinned_decal_saved(request_id + 1, path),
            task_accepts_cancel=True,
        )

    def _skinned_decal_saved(self, request_id, path):
        if request_id == getattr(self, "_skinned_decal_request_id", None):
            self.shell.set_status_message(f"Saved decal sequence copy: {path}")
