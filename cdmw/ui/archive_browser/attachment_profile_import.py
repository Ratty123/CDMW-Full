"""Async local attachment-profile import."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import QAbstractButton, QMessageBox, QWidget

from cdmw.domain.xml_text import decode_xml_text_payload
from cdmw.ui.archive_browser.attachment_task_controller import attachment_task_controller_for_guard
from cdmw.workers.attachment_io_workers import (
    AttachmentPayloadReadRequest,
    AttachmentPayloadReadResult,
    run_attachment_payload_read,
)


def start_attachment_profile_import(
    owner: object,
    dialog: QWidget,
    button: QAbstractButton,
    path: Path,
    *,
    on_loaded: Callable[[str], None],
) -> bool:
    controller = attachment_task_controller_for_guard(
        owner,
        dialog,
        attribute="_placement_attachment_io_controller",
    )

    def complete(result: object) -> None:
        if not isinstance(result, AttachmentPayloadReadResult):
            QMessageBox.warning(dialog, "Import Placement Profile XML", "Profile reader returned an unexpected result.")
            return
        try:
            text = decode_xml_text_payload(result.data).text
        except Exception as exc:
            QMessageBox.warning(dialog, "Import Placement Profile XML", f"Could not decode profile XML:\n{exc}")
            return
        on_loaded(text)

    button.setEnabled(False)
    started = controller.start(
        AttachmentPayloadReadRequest(file_path=path),
        run_attachment_payload_read,
        status_message=f"Reading placement profile {path.name}...",
        on_complete=complete,
        on_error=lambda message: QMessageBox.warning(
            dialog,
            "Import Placement Profile XML",
            f"Could not read profile XML:\n{message}",
        ),
        on_idle=lambda: button.setEnabled(True),
    )
    if not started:
        button.setEnabled(True)
    return started


__all__ = ["start_attachment_profile_import"]
