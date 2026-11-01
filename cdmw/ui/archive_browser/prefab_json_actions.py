"""Archive Browser prefab edit JSON actions."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Callable

from PySide6.QtWidgets import QFileDialog, QMessageBox

from cdmw.domain.archives.prefab import PrefabEditJsonError
from cdmw.services.archive_workflow_service import apply_prefab_edit_json, dumps_prefab_edit_json
from cdmw.models import ArchiveEntry
from cdmw.services.archive_read_service import read_archive_entry_data


class ArchivePrefabJsonActionsMixin:
    """Export/import the stable CDMW prefab edit JSON format."""

    def _current_archive_prefab_entry(self) -> ArchiveEntry | None:
        if self.archive_preview_showing_loose:
            return None
        selected = self._current_archive_entry()
        return selected if isinstance(selected, ArchiveEntry) and str(selected.extension or "").lower() == ".prefab" else None

    def _default_archive_prefab_edit_json_path(self, entry: ArchiveEntry) -> Path:
        default_dir = self.shell.settings_file_path.parent / "prefab_edit_json"
        stem = Path(PurePosixPath(entry.path.replace("\\", "/")).name).stem or "prefab"
        return default_dir / f"{stem}.prefab-edit.json"

    def _export_current_archive_prefab_edit_json(self) -> None:
        entry = self._current_archive_prefab_entry()
        if entry is None:
            self.shell.set_status_message("Select a .prefab archive entry before exporting Prefab Edit JSON.", error=True)
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
            self.shell.set_status_message(f"Exported Prefab Edit JSON for {entry.basename}.")

        self.shell._run_utility_task(
            status_message=f"Exporting Prefab Edit JSON for {entry.basename}...",
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
        )

    def _import_current_archive_prefab_edit_json(self) -> None:
        entry = self._current_archive_prefab_entry()
        if entry is None:
            self.shell.set_status_message("Select a .prefab archive entry before importing Prefab Edit JSON.", error=True)
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

        def _task(log: Callable[[str], None]) -> tuple[bytes, bytes]:
            log(f"Reading source prefab: {entry.path}")
            data, _decompressed, _note = read_archive_entry_data(entry)
            log(f"Applying Prefab Edit JSON: {document_path}")
            try:
                patched = apply_prefab_edit_json(data, document_path.read_text(encoding="utf-8"), virtual_path=entry.path)
            except PrefabEditJsonError as exc:
                raise ValueError(str(exc)) from exc
            return data, patched

        def _handle_complete(result: object) -> None:
            if not isinstance(result, tuple) or len(result) != 2:
                self.shell.set_status_message("Prefab Edit JSON import finished with an unexpected result payload.", error=True)
                return
            data, patched = result
            if patched == data:
                # An item package refuses a prefab identical to the game's, so
                # the unchanged payload can only go out as a loose folder.
                self.shell.set_status_message("Prefab Edit JSON made no byte changes; writing unchanged payload for review.")
                self._export_inspected_prefab(entry, patched, f"Prefab Edit JSON: {document_path.name}")
                return
            # Choose the output only now that the edit is known to apply.
            self._offer_prefab_export(entry, data, patched, f"Applied Prefab Edit JSON {document_path.name} to {entry.path}.")

        self.shell._run_utility_task_when_idle(
            status_message=f"Building Prefab Edit package for {entry.basename}...",
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
        )


__all__ = ["ArchivePrefabJsonActionsMixin"]
