from __future__ import annotations

from pathlib import Path
from typing import Sequence

from PySide6.QtCore import QThread, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QMessageBox

from cdmw.constants import APP_TITLE
from cdmw.core.mod_package import mod_package_export_options_for_profiles, mod_package_profile_uses_manager_metadata
from cdmw.models import ModPackageInfo, ReplaceAssistantBuildOptions, ReplaceAssistantBuildSummary, ReplaceAssistantReviewItem
from cdmw.ui.replace_assistant.review_dialog import ReplaceAssistantReviewDialog
from cdmw.ui.replace_assistant.workers import ReplaceAssistantBuildWorker


class ReplaceAssistantBuildMixin:
    def _current_build_options(self) -> ReplaceAssistantBuildOptions:
        texconv_text = self.get_texconv_path().strip()
        texconv_path = Path(texconv_text).expanduser()
        ncnn_exe_text = self.ncnn_exe_path_edit.text().strip()
        ncnn_exe_path = Path(ncnn_exe_text).expanduser() if ncnn_exe_text else None
        ncnn_model_dir_text = self.ncnn_model_dir_edit.text().strip()
        ncnn_model_dir = Path(ncnn_model_dir_text).expanduser() if ncnn_model_dir_text else None
        selected_profiles = tuple(
            profile
            for profile, checkbox in self.package_profile_checkboxes.items()
            if checkbox.isChecked()
        ) or (str(self.package_manager_combo.currentData() or "dmm"),)
        uses_manager_metadata = any(mod_package_profile_uses_manager_metadata(profile) for profile in selected_profiles)
        export_options = mod_package_export_options_for_profiles(
            selected_profiles,
            create_zip=self.package_zip_checkbox.isChecked(),
            conflict_mode=str(self.package_conflict_mode_combo.currentData() or "") if uses_manager_metadata else "",
            target_language=self.package_target_language_edit.text().strip() if uses_manager_metadata else "",
        )
        return ReplaceAssistantBuildOptions(
            package_output_root=Path(self.package_output_root_edit.text().strip()).expanduser(),
            overwrite_existing_package_files=self.overwrite_package_checkbox.isChecked(),
            create_no_encrypt_file=self.create_no_encrypt_checkbox.isChecked(),
            build_mode=self._combo_value(self.build_mode_combo),
            size_mode=self._combo_value(self.size_mode_combo),
            texconv_path=texconv_path,
            ncnn_exe_path=ncnn_exe_path,
            ncnn_model_dir=ncnn_model_dir,
            ncnn_model_name=self._combo_value(self.ncnn_model_combo),
            ncnn_scale=self.ncnn_scale_spin.value(),
            ncnn_tile_size=self.ncnn_tile_size_spin.value(),
            ncnn_extra_args=self.ncnn_extra_args_edit.text().strip(),
            retry_smaller_tile_on_failure=self.retry_smaller_tile_checkbox.isChecked(),
            upscale_post_correction_mode=self._combo_value(self.upscale_post_correction_combo),
            upscale_texture_preset=self._combo_value(self.upscale_texture_preset_combo),
            enable_automatic_texture_rules=self.enable_automatic_texture_rules_checkbox.isChecked(),
            enable_unsafe_technical_override=self.enable_unsafe_technical_override_checkbox.isChecked(),
            package_info=ModPackageInfo(
                title=self.package_title_edit.text().strip() or "Crimson Desert Mod Workbench Mod",
                version=self.package_version_edit.text().strip() or "1.0",
                author=self.package_author_edit.text().strip(),
                description=self.package_description_edit.text().strip(),
                nexus_url=self.package_nexus_edit.text().strip(),
            ),
            export_options=export_options,
        )

    def start_build(self) -> None:
        if self.is_busy():
            return
        if not self.items:
            QMessageBox.information(self, APP_TITLE, "Add edited PNG or DDS files before building a mod package.")
            return
        if any(item.status == "unresolved" for item in self.items):
            QMessageBox.warning(
                self,
                APP_TITLE,
                "Some items are still unresolved. Choose the original DDS for each of them before building.",
            )
            return
        options = self._current_build_options()
        self.last_built_output_root = None
        self.progress_bar.setRange(0, len(self.items))
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Working...")
        self.status_label.setText("Building replace package...")
        self.append_log("Starting Texture Replacer build.")
        worker = ReplaceAssistantBuildWorker(
            self.items,
            options,
            archive_entries=self.archive_entries or self.get_archive_entries(),
            original_dds_root=Path(self.get_original_root().strip()).expanduser() if self.get_original_root().strip() else None,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.log_message.connect(self.append_log)
        worker.current_file.connect(lambda text: self.status_label.setText(text))
        worker.progress.connect(self._handle_build_progress)
        worker.completed.connect(self._handle_build_complete)
        worker.cancelled.connect(self._handle_build_cancelled)
        worker.error.connect(self._handle_build_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._cleanup_build_refs)
        self.build_worker = worker
        self.build_thread = thread
        self._update_controls()
        thread.start()

    def stop_build(self) -> None:
        if self.build_worker is not None:
            self.build_worker.stop()

    def _handle_build_progress(self, current: int, total: int, detail: str) -> None:
        self.status_label.setText(detail)
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(min(max(current, 0), total))
            self.progress_bar.setFormat(f"{min(max(current, 0), total)} / {total}")
        else:
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setFormat("Working...")

    def _handle_build_complete(self, payload: object) -> None:
        summary = payload if isinstance(payload, ReplaceAssistantBuildSummary) else None
        if summary is None:
            return
        self.append_log(
            f"Build complete: built={summary.built_items:,}, unresolved={summary.unresolved_items:,}, failed={summary.failed_items:,}."
        )
        if summary.output_root is not None:
            self.last_built_output_root = summary.output_root
            self.status_label.setText(f"Replace package written to: {summary.output_root}")
            self.status_message_requested.emit(f"Replace package written to: {summary.output_root}", False)
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(1)
            self.progress_bar.setFormat("Ready")
            if summary.review_items:
                self.pending_review_items = tuple(summary.review_items)
                self.append_log(
                    f"Prepared {len(summary.review_items):,} built item(s) for review. "
                    "Opening the review window after cleanup."
                )
        else:
            self.last_built_output_root = None
            self.status_label.setText("Replace package was not written because some items failed or were unresolved.")
            self.status_message_requested.emit(
                "Replace package was not written because some items failed or were unresolved.",
                True,
            )
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("Failed")

    def _handle_build_cancelled(self, message: str) -> None:
        self.append_log(message)
        self.status_label.setText(message)
        self.status_message_requested.emit(message, True)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Stopped")

    def _handle_build_error(self, message: str) -> None:
        self.append_log(f"ERROR: {message}")
        self.status_label.setText(message)
        self.status_message_requested.emit(message, True)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Error")

    def _cleanup_build_refs(self) -> None:
        self.build_thread = None
        self.build_worker = None
        self._update_controls()
        if self.pending_review_items:
            pending_review_items = self.pending_review_items
            self.pending_review_items = None
            QTimer.singleShot(0, lambda items=pending_review_items: self._open_review_dialog(items))

    def _browse_package_output_root(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Choose replace package parent root",
            self.package_output_root_edit.text().strip() or self.base_dir.as_posix(),
        )
        if folder:
            self.package_output_root_edit.setText(folder)

    def _browse_ncnn_exe(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Real-ESRGAN NCNN executable",
            self.ncnn_exe_path_edit.text().strip() or self.base_dir.as_posix(),
            "Executables (*.exe);;All files (*.*)",
        )
        if file_path:
            self.ncnn_exe_path_edit.setText(file_path)
            self._refresh_ncnn_models()

    def _browse_ncnn_model_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Choose NCNN model folder",
            self.ncnn_model_dir_edit.text().strip() or self.base_dir.as_posix(),
        )
        if folder:
            self.ncnn_model_dir_edit.setText(folder)
            self._refresh_ncnn_models()

    def refresh_ncnn_models(self) -> None:
        self._refresh_ncnn_models()

    def open_output_folder(self) -> None:
        output_root = self.last_built_output_root
        if output_root is None:
            output_root_text = self.package_output_root_edit.text().strip()
            if not output_root_text:
                return
            output_root = Path(output_root_text).expanduser()
        output_root.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(output_root)))

    def _open_review_dialog(self, review_items: Sequence[ReplaceAssistantReviewItem]) -> None:
        if self.review_dialog is not None:
            self.review_dialog.close()
        texconv_text = self.get_texconv_path().strip()
        texconv_path = Path(texconv_text).expanduser() if texconv_text else None
        dialog = ReplaceAssistantReviewDialog(texconv_path, review_items, self)
        self.review_dialog = dialog
        dialog.finished.connect(self._clear_review_dialog_ref)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _clear_review_dialog_ref(self) -> None:
        self.review_dialog = None
