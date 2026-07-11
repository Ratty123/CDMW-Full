"""Worker dispatch for loading material-sidecar editor documents."""

from __future__ import annotations

from cdmw.models import ArchiveEntry
from cdmw.services.material_sidecar_document_service import (
    MaterialSidecarEditorDocument,
    load_material_sidecar_editor_document,
)


class ArchiveMaterialSidecarDocumentControllerMixin:
    def _open_material_sidecar_editor(self, entry: ArchiveEntry) -> None:
        request_id = int(getattr(self, "_material_sidecar_document_request_id", 0) or 0) + 1
        self._material_sidecar_document_request_id = request_id
        self._run_utility_task(
            status_message=f"Reading material sidecar {entry.basename}...",
            task=lambda _log, stop_event: load_material_sidecar_editor_document(
                entry,
                stop_event=stop_event,
            ),
            on_complete=lambda result: self._handle_material_sidecar_document_loaded(request_id, result),
            task_accepts_cancel=True,
        )

    def _handle_material_sidecar_document_loaded(self, request_id: int, result: object) -> None:
        if request_id != int(getattr(self, "_material_sidecar_document_request_id", 0) or 0):
            return
        if not isinstance(result, MaterialSidecarEditorDocument):
            self.set_status_message("Material sidecar worker returned invalid data.", error=True)
            return
        self._run_when_background_idle(
            lambda: self._show_material_sidecar_editor(result),
            label="opening the material sidecar editor",
        )


__all__ = ["ArchiveMaterialSidecarDocumentControllerMixin"]
