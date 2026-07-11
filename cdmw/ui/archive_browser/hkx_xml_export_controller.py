"""Background-task dispatch for edited HKX XML exports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QMessageBox, QWidget

from cdmw.services.diagnostics_service import is_expected_cancellation_message
from cdmw.services.hkx_xml_export_service import (
    HkxXmlExportRequest,
    HkxXmlExportResult,
    export_hkx_xml,
)


def start_hkx_editor_xml_export(
    owner: Any,
    output_path: Path,
    document_text: str,
    *,
    message_parent: QWidget,
) -> None:
    request_id = int(getattr(owner, "_hkx_editor_xml_export_request_id", 0) or 0) + 1
    owner._hkx_editor_xml_export_request_id = request_id
    request = HkxXmlExportRequest(request_id, output_path, document_text)

    def is_current() -> bool:
        return (
            not bool(getattr(owner, "_shutting_down", False))
            and request_id == int(getattr(owner, "_hkx_editor_xml_export_request_id", 0) or 0)
        )

    def complete(result: object) -> None:
        if not is_current():
            return
        if not isinstance(result, HkxXmlExportResult) or result.request_id != request_id:
            owner.set_status_message("Edited HKX XML export returned invalid data.", error=True)
            return
        owner.set_status_message(f"Exported edited HKX XML to {result.output_path}.")

    def error(message: str) -> None:
        if not is_current() or is_expected_cancellation_message(message):
            return
        QMessageBox.warning(
            message_parent,
            "Export Edited HKX XML",
            f"Could not export edited HKX XML:\n{message}",
        )
        owner.set_status_message(f"Edited HKX XML export failed: {message}", error=True)

    owner._run_utility_task_when_idle(
        status_message=f"Exporting edited HKX XML to {output_path.name}...",
        task=lambda _log, stop_event: export_hkx_xml(request, stop_event=stop_event),
        on_complete=complete,
        on_error=error,
        task_accepts_cancel=True,
    )


__all__ = ["start_hkx_editor_xml_export"]
