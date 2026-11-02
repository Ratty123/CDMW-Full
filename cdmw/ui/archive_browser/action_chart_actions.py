"""Archive Browser action that opens the Action Chart Editor on a `.paac` entry."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from cdmw.core.action_chart_binary import ActionChartError
from cdmw.domain.archives.mesh_contracts import ArchiveLooseExportResult
from cdmw.models import ArchiveEntry
from cdmw.services.action_chart_edit_service import (
    change_summary,
    chart_clip_names,
    export_action_chart_mod,
    is_editable_action_chart_path,
    load_editable_chart,
)
from cdmw.services.archive_read_service import read_archive_entry_data
from cdmw.ui.archive_browser.action_chart_editor_dialog import ActionChartEditorDialog, ActionChartEditorResult


class ArchiveActionChartActionsMixin:
    """Read a chart off the UI thread, edit it, and write it as a DMM loose mod."""

    def _current_archive_action_chart_entry(self) -> ArchiveEntry | None:
        if self.archive_preview_showing_loose:
            return None
        selected = self._current_archive_entry()
        return selected if isinstance(selected, ArchiveEntry) and is_editable_action_chart_path(selected.path) else None

    def _open_current_archive_action_chart_editor(self) -> None:
        entry = self._current_archive_action_chart_entry()
        if entry is None:
            self.shell.set_status_message("Select a .paac archive entry before opening the Action Chart Editor.", error=True)
            return
        status_message = f"Preparing Action Chart Editor for {entry.basename}..."
        self.shell.set_status_message(status_message)
        # Copy the list reference on the UI thread; the worker only reads paths from it.
        clip_entries = list(self.archive_entries_by_extension.get(".paa", ()))

        def _prepare(log: Callable[[str], None]) -> tuple[bytes, tuple[str, ...]]:
            log(f"Reading action chart: {entry.path}")
            try:
                data, _decompressed, _note = read_archive_entry_data(entry)
            except Exception as exc:  # noqa: BLE001 - surfaced through the worker error path
                raise RuntimeError(f"Could not read {entry.path}: {exc}") from exc
            # Refuse the shared action tables here, not after the dialog is built.
            load_editable_chart(data, entry.path)
            log(f"Listing {len(clip_entries):,} animation clips for retargets")
            return data, chart_clip_names(item.path for item in clip_entries)

        def _open(result: object) -> None:
            if not isinstance(result, tuple) or len(result) != 2:
                self.shell.set_status_message(f"Could not read {entry.path}: {result!r}", error=True)
                return
            data, clips = result
            self._show_action_chart_editor(entry, data, clips)

        self.shell._run_utility_task_when_idle(
            status_message=status_message,
            task=_prepare,
            on_complete=_open,
            show_archive_progress=True,
        )

    def _show_action_chart_editor(self, entry: ArchiveEntry, data: bytes, clips: tuple[str, ...]) -> None:
        # Large charts hold thousands of animations; the tables fill before the window paints.
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            dialog = ActionChartEditorDialog(
                data,
                virtual_path=entry.path,
                known_clips=clips,
                title=f"Action Chart Editor - {entry.basename}",
                parent=self,
            )
        except ActionChartError as exc:
            self.shell.set_status_message(f"Cannot edit {entry.path}: {exc}", error=True)
            return
        finally:
            QApplication.restoreOverrideCursor()
        dialog.exec()
        payload = dialog.result_payload
        if payload is None or payload.data == data:
            return
        self._export_edited_action_chart(entry, data, payload)

    def _export_edited_action_chart(self, entry: ArchiveEntry, original: bytes, payload: ActionChartEditorResult) -> None:
        stem = Path(PurePosixPath(entry.path.replace("\\", "/")).name).stem or "action_chart"
        export_target = self._collect_archive_mod_ready_export_target(
            browse_title="Choose Action Chart Export Root",
            prompt_for_metadata=True,
            dialog_title="Build Action Chart DMM Mod",
            allow_dmm_texture_structure=False,
            initial_package_title=f"{stem} chart edit",
            initial_package_description=f"CDMW action chart edit for {entry.path}: {change_summary(payload.changes)}",
        )
        if export_target is None:
            return
        export_root, package_info, create_no_encrypt_file, _include_related, export_options = export_target
        edited = payload.data

        def _task(log: Callable[[str], None]) -> ArchiveLooseExportResult:
            return export_action_chart_mod(
                entry,
                original,
                edited,
                parent_root=export_root,
                package_info=package_info,
                export_options=export_options,
                create_no_encrypt_file=create_no_encrypt_file,
                on_log=log,
            )

        def _handle_complete(result: object) -> None:
            if not isinstance(result, ArchiveLooseExportResult):
                self.shell.set_status_message("Action chart export finished with an unexpected result payload.", error=True)
                return
            QMessageBox.information(
                self,
                "Action Chart Mod Complete",
                f"Wrote the action chart DMM mod into:\n{result.package_root}\n\n"
                "Add it in DMM and enable it there. Action chart edits have not been confirmed in game yet.",
            )
            self.shell.set_status_message(f"Wrote action chart DMM mod: {result.package_root}")

        self.shell._run_utility_task_when_idle(
            status_message=f"Building action chart DMM mod for {entry.basename}...",
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
        )


__all__ = ["ArchiveActionChartActionsMixin"]
