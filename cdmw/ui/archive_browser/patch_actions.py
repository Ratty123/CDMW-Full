"""Archive patch, audio patch, and backup restore actions."""
from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFileDialog, QMessageBox

from cdmw.domain.archives.format import is_material_sidecar_extension as _is_material_sidecar_extension
from cdmw.services.archive_workflow_service import (
    build_archive_audio_patch_payload,
    export_archive_audio_as_wav,
)
from cdmw.models import ArchiveEntry
from cdmw.services.archive_mutation_service import ArchivePatchRequest, ArchivePatchResult


class ArchivePatchActionsMixin:
    def _apply_archive_patch_result(self, patch_result: ArchivePatchResult) -> None:
        lookup_indexes = self._archive_lookup_indexes_snapshot()
        if lookup_indexes is None:
            pending = list(getattr(self, "_archive_patch_results_pending_index", ()) or ())
            pending.append(patch_result)
            self._archive_patch_results_pending_index = pending[-16:]
            self.archive_preview_cache.clear()
            self.set_status_message(
                "Archive patch completed; resident cache update is waiting for path indexing."
            )
            return
        path_index, _basename_index = lookup_indexes
        for normalized_path, updated_entry in patch_result.changed_entries.items():
            for existing_entry in path_index.get(normalized_path, []):
                if existing_entry.pamt_path.resolve() != updated_entry.pamt_path.resolve():
                    continue
                existing_entry.paz_file = updated_entry.paz_file
                existing_entry.offset = updated_entry.offset
                existing_entry.comp_size = updated_entry.comp_size
                existing_entry.orig_size = updated_entry.orig_size
                existing_entry.flags = updated_entry.flags
                existing_entry.paz_index = updated_entry.paz_index
        self.archive_preview_cache.clear()
        changed_paths = tuple(str(path or "").replace("\\", "/").strip().lower() for path in patch_result.changed_entries)
        if any(
            _is_material_sidecar_extension(
                PurePosixPath(path).suffix,
                PurePosixPath(path).name,
            )
            or path.endswith(".dds")
            for path in changed_paths
        ):
            self.archive_sidecar_generation += 1
            self._clear_archive_asset_family_cache()
            self.archive_sidecar_entries_by_texture_path = {}
            self.archive_sidecar_entries_by_texture_basename = {}
            if self.archive_entries and self._current_archive_performance_settings().enable_sidecar_indexing:
                self.archive_sidecar_pending_start = True
                QTimer.singleShot(0, self._start_archive_sidecar_index_worker)
            else:
                self.archive_sidecar_pending_start = False

    def _start_archive_audio_export(self, entry: ArchiveEntry) -> None:
        default_dir = self.settings_file_path.parent / "audio_export"
        default_target = default_dir / f"{Path(entry.basename).stem}.wav"
        output_path, _selected = QFileDialog.getSaveFileName(
            self,
            "Export Audio As WAV",
            str(default_target),
            "WAV (*.wav)",
        )
        if not output_path:
            return

        def _task(log: Callable[[str], None]) -> Path:
            log(f"Exporting {entry.path} as WAV...")
            return export_archive_audio_as_wav(entry, Path(output_path))

        def _handle_complete(result: object) -> None:
            if not isinstance(result, Path):
                self.set_status_message("Audio export finished with an unexpected result payload.", error=True)
                return
            QMessageBox.information(self, "Audio Export Complete", f"Exported WAV:\n{result}")
            self.set_status_message(f"Exported {entry.basename} as WAV.")

        self._run_utility_task(
            status_message=f"Exporting {entry.basename} as WAV...",
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
        )

    def _start_archive_audio_patch(self, entry: ArchiveEntry) -> None:
        source_path, _selected = QFileDialog.getOpenFileName(
            self,
            "Select Replacement Audio",
            str(self.settings_file_path.parent),
            "Audio Files (*.wav *.ogg *.mp3)",
        )
        if not source_path:
            return

        warning_text = "A backup of the touched archive files will be created before anything is written."
        if entry.extension == ".wem":
            warning_text += (
                "\n\nWEM patching is best-effort: this rebuilds a simple replacement stream from the selected "
                "audio, not a full Wwise-authoring rebuild. Some original Wwise codec/container variants may "
                "not behave the same in-game."
            )
        confirmation = QMessageBox.question(
            self,
            "Patch Audio To Game",
            (
                f"Patch {entry.path} using {Path(source_path).name}?\n\n"
                f"{warning_text}"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirmation != QMessageBox.Yes:
            return

        mutation_service = self.app_context.services.require_archive_mutations()

        def _task(
            log: Callable[[str], None],
            stop_event: threading.Event,
        ) -> ArchivePatchResult:
            log(f"Preparing replacement audio for {entry.path}...")
            replacement_payload = build_archive_audio_patch_payload(entry, Path(source_path))
            plan = mutation_service.prepare_patch(
                ArchivePatchRequest(entry=entry, payload_data=replacement_payload),
                confirmed=True,
                description=f"Patch audio entry {entry.path}",
            )
            return mutation_service.apply_patch(plan, on_log=log, stop_event=stop_event)

        def _handle_complete(result: object) -> None:
            if not isinstance(result, ArchivePatchResult):
                self.set_status_message("Audio patch finished with an unexpected result payload.", error=True)
                return
            self._apply_archive_patch_result(result)
            current_entry = self._current_archive_entry()
            if current_entry is not None and current_entry.path == entry.path:
                self._render_archive_preview(current_entry)
            QMessageBox.information(
                self,
                "Audio Patch Complete",
                f"Patched {entry.path}\n\nBackup: {result.backup_dir}",
            )
            self.set_status_message(f"Patched audio entry {entry.basename}.")

        self._run_utility_task(
            status_message=f"Patching audio for {entry.basename}...",
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
            task_accepts_cancel=True,
        )

    def _restore_archive_patch_backup_from_ui(self) -> None:
        mutation_service = self.app_context.services.require_archive_mutations()
        backups = mutation_service.list_backups()
        if not backups:
            self.set_status_message(
                f"No archive patch backups were found under {mutation_service.backup_root}.",
                error=True,
            )
            return

        selected_dir = QFileDialog.getExistingDirectory(
            self,
            "Select Archive Patch Backup",
            str(backups[0]),
        )
        if not selected_dir:
            return

        backup_dir = Path(selected_dir)
        manifest_path = backup_dir / "backup_manifest.json"
        if not manifest_path.is_file():
            QMessageBox.warning(
                self,
                "Restore Backup",
                f"{backup_dir} does not contain a backup_manifest.json file.",
            )
            return

        confirmation = QMessageBox.question(
            self,
            "Restore Archive Patch Backup",
            (
                f"Restore files from:\n{backup_dir}\n\n"
                "This will overwrite the current archive files with the selected backup copy."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirmation != QMessageBox.Yes:
            return

        def _task(
            log: Callable[[str], None],
            stop_event: threading.Event,
        ) -> Path:
            log(f"Restoring archive patch backup from {backup_dir}...")
            return mutation_service.restore_backup(
                backup_dir,
                confirmed=True,
                on_log=log,
                stop_event=stop_event,
            )

        def _handle_complete(result: object) -> None:
            restored_dir = result if isinstance(result, Path) else backup_dir
            self.set_status_message(f"Restored archive backup from {restored_dir}.")
            QMessageBox.information(
                self,
                "Backup Restored",
                f"Restored archive files from:\n{restored_dir}",
            )
            QTimer.singleShot(150, lambda: self.scan_archives(force_refresh=True))

        self._run_utility_task(
            status_message=f"Restoring archive backup from {backup_dir.name}...",
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
            task_accepts_cancel=True,
        )
