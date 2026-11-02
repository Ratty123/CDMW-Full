"""Archive patch, audio patch, and backup restore actions."""
from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from cdmw.domain.archives.format import is_material_sidecar_extension as _is_material_sidecar_extension
from cdmw.domain.archives.mesh_contracts import ArchiveLooseExportResult
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.archive_workflow_service import (
    apply_sound_bank_edits,
    build_archive_audio_patch_payload,
    export_archive_audio_as_wav,
    export_archive_payloads_to_mod_ready_loose,
    list_bank_embedded_media,
    plan_wwise_media_replacement,
    read_sound_bank_editor_model,
    wwise_media_source_id,
)
from cdmw.models import ArchiveEntry
from cdmw.services.archive_mutation_service import ArchivePatchRequest, ArchivePatchResult
from cdmw.ui.archive_browser.sound_bank_editor import SoundBankEditorDialog


class ArchivePatchActionsMixin:
    def _apply_archive_patch_result(self, patch_result: ArchivePatchResult) -> None:
        lookup_indexes = self._archive_lookup_indexes_snapshot()
        if lookup_indexes is None:
            pending = list(getattr(self, "_archive_patch_results_pending_index", ()) or ())
            pending.append(patch_result)
            self._archive_patch_results_pending_index = pending[-16:]
            self.archive_preview_cache.clear()
            self.shell.set_status_message(
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
            if self.archive_entries and self.shell._current_archive_performance_settings().enable_sidecar_indexing:
                self.archive_sidecar_pending_start = True
                QTimer.singleShot(0, self._start_archive_sidecar_index_worker)
            else:
                self.archive_sidecar_pending_start = False

    def _start_archive_audio_export(self, entry: ArchiveEntry) -> None:
        default_dir = self.shell.settings_file_path.parent / "audio_export"
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
                self.shell.set_status_message("Audio export finished with an unexpected result payload.", error=True)
                return
            QMessageBox.information(self, "Audio Export Complete", f"Exported WAV:\n{result}")
            self.shell.set_status_message(f"Exported {entry.basename} as WAV.")

        self.shell._run_utility_task(
            status_message=f"Exporting {entry.basename} as WAV...",
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
        )

    def _start_archive_audio_patch(self, entry: ArchiveEntry) -> None:
        # The game refuses rewritten archive indexes and mount lists since the DLC
        # update, so replacement audio is written as a loose mod for DMM instead of
        # being patched into the installed archives.
        source_path = self._select_replacement_audio(allow_wem=entry.extension == ".wem")
        if not source_path:
            return
        source_id = wwise_media_source_id(entry)
        if entry.extension == ".wem" and source_id is None:
            QMessageBox.information(
                self,
                "Audio Loose Mod",
                "This sound is chosen by name while the game runs, so no sound bank describes it and only the "
                ".wem is replaced. Audio other than a Wwise .wem is written as uncompressed PCM.",
            )
        self._export_audio_replacement(entry, source_path, source_id=source_id)

    def _start_archive_bank_media_replace(self, entry: ArchiveEntry) -> None:
        def _task(log: Callable[[str], None]) -> object:
            log(f"Reading the sounds {entry.path} embeds...")
            return list_bank_embedded_media(entry)

        def _handle_complete(result: object) -> None:
            media = tuple(result) if isinstance(result, tuple) else ()
            if not media:
                QMessageBox.information(
                    self,
                    "Replace Embedded Sound",
                    "This bank embeds no sounds; its media are loose .wem files. Replace the .wem instead.",
                )
                return
            labels = [f"{item.ordinal}: {item.source_id} ({item.size:,} bytes)" for item in media]
            choice, accepted = QInputDialog.getItem(
                self, "Replace Embedded Sound", "Sound to replace (preview track: source id):", labels, 0, False
            )
            if not accepted or choice not in labels:
                return
            source_path = self._select_replacement_audio(allow_wem=True)
            if source_path:
                self._export_audio_replacement(entry, source_path, source_id=media[labels.index(choice)].source_id)

        self.shell._run_utility_task(
            status_message=f"Reading the sounds in {entry.basename}...",
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
        )

    def _select_replacement_audio(self, *, allow_wem: bool) -> str:
        patterns = "*.wav *.ogg *.mp3" + (" *.wem" if allow_wem else "")
        source_path, _selected = QFileDialog.getOpenFileName(
            self,
            "Select Replacement Audio",
            str(self.shell.settings_file_path.parent),
            f"Audio Files ({patterns})",
        )
        return source_path

    def _export_audio_replacement(
        self,
        entry: ArchiveEntry,
        source_path: str,
        *,
        source_id: int | None,
    ) -> None:
        archive_entries = tuple(getattr(self, "archive_entries", ()) or ())

        def _requests(log, stop_event, notes):
            log(f"Preparing replacement audio for {entry.path}...")
            if source_id is None:
                payload = build_archive_audio_patch_payload(entry, Path(source_path))
                return [ArchivePatchRequest(entry=entry, payload_data=payload)]
            replacement = plan_wwise_media_replacement(
                entry, Path(source_path), source_id, archive_entries, stop_event=stop_event, on_log=log
            )
            notes.extend(replacement.notes)
            return [ArchivePatchRequest(entry=item, payload_data=data) for item, data in replacement.payloads]

        self._write_audio_loose_mod(entry, _requests)

    def _start_archive_sound_bank_edit(self, entry: ArchiveEntry) -> None:
        def _task(log: Callable[[str], None]) -> object:
            log(f"Reading {entry.path}...")
            return read_sound_bank_editor_model(entry)

        def _handle_complete(model: object) -> None:
            if not getattr(model, "rows", None) and not getattr(model, "objects", None):
                notes = " ".join(getattr(model, "notes", ())) or "This bank stores nothing the editor can change."
                QMessageBox.information(self, "Edit Sound Bank", notes)
                return
            dialog = SoundBankEditorDialog(self, entry.basename, model)
            if dialog.exec() != dialog.DialogCode.Accepted:
                return
            plan = dialog.plan()
            archive_entries = tuple(getattr(self, "archive_entries", ()) or ())

            def _requests(log, stop_event, notes):
                data, changes = apply_sound_bank_edits(entry, plan, archive_entries, stop_event=stop_event, on_log=log)
                for change in changes:
                    log(change)
                notes.append(f"{len(changes):,} change(s) written to {entry.basename}. Not yet confirmed in game.")
                return [ArchivePatchRequest(entry=entry, payload_data=data)]

            self._write_audio_loose_mod(entry, _requests)

        self.shell._run_utility_task(
            status_message=f"Reading {entry.basename}...",
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
        )

    def _write_audio_loose_mod(
        self,
        entry: ArchiveEntry,
        build_requests: Callable[[Callable[[str], None], threading.Event, list[str]], list[ArchivePatchRequest]],
    ) -> None:
        loose_export_settings = self._collect_archive_mod_ready_export_target(
            browse_title="Select Audio Mod-Ready Export Parent Root",
            prompt_for_metadata=True,
            initial_include_related_files=False,
            show_include_related_files_option=False,
            dialog_title="Audio Loose Mod Metadata",
            allow_dmm_texture_structure=False,
        )
        if loose_export_settings is None:
            return
        parent_root, package_info, create_no_encrypt_file, _include_related_files, export_options = loose_export_settings
        notes: list[str] = []

        def _task(
            log: Callable[[str], None],
            stop_event: threading.Event,
        ) -> ArchiveLooseExportResult:
            requests = build_requests(log, stop_event, notes)
            raise_if_cancelled(stop_event, "Audio loose mod export cancelled.")
            return export_archive_payloads_to_mod_ready_loose(
                requests,
                parent_root=parent_root,
                package_info=package_info,
                export_options=export_options,
                create_no_encrypt_file=create_no_encrypt_file,
                on_log=log,
            )

        def _handle_complete(result: object) -> None:
            if not isinstance(result, ArchiveLooseExportResult):
                self.shell.set_status_message("Audio loose mod export finished with an unexpected result payload.", error=True)
                return
            note_text = ("\n\n" + "\n\n".join(notes)) if notes else ""
            QMessageBox.information(
                self,
                "Audio Loose Mod Written",
                f"Wrote replacement audio loose mod package:\n{result.package_root}\n\n"
                f"Target entry:\n{entry.path}\n\n"
                f"The installed game archives were not modified. Load the package with DMM.{note_text}",
            )
            self.shell.set_status_message(f"Wrote replacement audio for {entry.basename} as a mod-ready loose package.")

        self.shell._run_utility_task(
            status_message=f"Writing replacement audio for {entry.basename}...",
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
            task_accepts_cancel=True,
        )

    def _restore_archive_patch_backup_from_ui(self) -> None:
        mutation_service = self.shell.app_context.services.require_archive_mutations()
        backups = mutation_service.list_backups()
        if not backups:
            self.shell.set_status_message(
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
            self.shell.set_status_message(f"Restored archive backup from {restored_dir}.")
            QMessageBox.information(
                self,
                "Backup Restored",
                f"Restored archive files from:\n{restored_dir}",
            )
            QTimer.singleShot(150, lambda: self.scan_archives(force_refresh=True))

        self.shell._run_utility_task(
            status_message=f"Restoring archive backup from {backup_dir.name}...",
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
            task_accepts_cancel=True,
        )
