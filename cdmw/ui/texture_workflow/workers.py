"""Texture workflow scan/build worker orchestration."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Callable, Dict, List, Sequence

from PySide6.QtCore import QThread, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox

from cdmw.constants import UPSCALE_BACKEND_NONE
from cdmw.services.texture_workflow_service import get_registered_texture_classification
from cdmw.services.texture_workflow_service import collect_dds_files
from cdmw.services.texture_workflow_service import build_texture_processing_plan
from cdmw.services.texture_workflow_service import build_texture_policy_preview_payload
from cdmw.services.texture_workflow_service import normalize_config, validate_backend_runtime_requirements
from cdmw.services.texture_workflow_service import get_texture_preset_definition
from cdmw.models import AppConfig, ArchiveEntry, RunSummary
from cdmw.ui.policy_preview_dialog import TexturePolicyPreviewDialog
from cdmw.workers.texture_workers import BuildWorker, DdsToPngWorker, ScanWorker


class TextureWorkflowWorkerMixin:
    """Texture workflow scan/build workers and progress handlers."""

    def start_scan(self) -> None:
        if self._background_task_active():
            return

        self.set_status_message("Scanning DDS files...")
        self.append_log("Starting scan.")
        self.reset_progress()
        self._activate_tool_widget(self.workflow_tab)
        self.content_tabs.setCurrentIndex(0)

        worker = ScanWorker(self.collect_config())
        thread = QThread(self)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.log_message.connect(self.append_log)
        worker.result_ready.connect(self._handle_scan_result)
        worker.error.connect(self._handle_worker_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._cleanup_worker_refs)

        self.scan_worker = worker
        self.worker_thread = thread
        self.set_busy(True, build_mode=False)
        thread.start()

    def preview_texture_policy(self) -> None:
        if self._background_task_active():
            return

        config = self.collect_config()

        def task(on_log: Callable[[str], None]) -> Dict[str, object]:
            on_log("Building per-texture policy preview...")
            normalized = normalize_config(config, validate_backend_runtime=False)
            dds_files = collect_dds_files(
                normalized.original_dds_root,
                normalized.include_filter_patterns,
            )
            if not dds_files:
                raise ValueError("No DDS files were found under the original root with the current filter.")
            processing_plan = build_texture_processing_plan(normalized, dds_files)
            payload = build_texture_policy_preview_payload(
                normalized,
                dds_files,
                processing_plan=processing_plan,
            )
            requires_png_processing = any(entry.requires_png_processing for entry in processing_plan)
            if normalized.upscale_backend != UPSCALE_BACKEND_NONE and requires_png_processing:
                try:
                    validate_backend_runtime_requirements(normalized)
                except Exception as exc:
                    payload["runtime_validation_warning"] = (
                        "Runtime/config validation warning: "
                        + str(exc)
                        + "\nThe semantic policy preview below is still valid, but Start would fail until this is fixed."
                    )
            elif normalized.upscale_backend != UPSCALE_BACKEND_NONE:
                payload["runtime_validation_warning"] = (
                    "Current preset and automatic rules keep every matched DDS out of the PNG/upscale path, "
                    "so backend/runtime validation was intentionally skipped for this preview."
                )
            return payload

        def on_complete(result: object) -> None:
            if not isinstance(result, dict):
                self.set_status_message("Texture policy preview returned an unexpected result.", error=True)
                return
            dialog = TexturePolicyPreviewDialog(theme_key=self.current_theme_key, settings=self.settings, parent=self)
            dialog.set_payload(result)
            self.set_status_message("Texture policy preview is ready.")
            dialog.exec()

        self._run_utility_task(
            status_message="Building texture policy preview...",
            task=task,
            on_complete=on_complete,
        )

    def start_dds_to_png(self) -> None:
        if self._background_task_active():
            return

        config = self.collect_config()
        if not self._prepare_workflow_output_roots_for_start(config, include_output_root=False):
            return
        self._apply_pending_archive_workflow_extract_if_needed()
        self._apply_pending_texture_editor_workflow_export_if_needed()
        self.set_status_message("Preparing DDS to PNG conversion...")
        self.append_log("Starting DDS -> PNG conversion.")
        self._set_last_active_operation(
            "texture_conversion",
            mode="dds_to_png",
            original_dds_root=config.original_dds_root,
            png_root=config.png_root,
        )
        if config.upscale_backend == UPSCALE_BACKEND_NONE:
            self.append_log(
                "Warning: DDS-to-PNG conversion is enabled while the upscaling backend is disabled, so Start will convert DDS files to PNG and stop."
            )
        self.reset_progress()
        self._activate_tool_widget(self.workflow_tab)
        self.content_tabs.setCurrentIndex(0)

        worker = DdsToPngWorker(
            config,
            crash_reports_dir=self.crash_reports_dir,
            session_id=self._session_id,
        )
        thread = QThread(self)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.log_message.connect(self.append_log)
        worker.phase_changed.connect(self._handle_phase_changed)
        worker.phase_progress_changed.connect(self._handle_phase_progress_changed)
        worker.total_found.connect(self._handle_total_found)
        worker.current_file.connect(self._handle_current_file)
        worker.progress.connect(self._handle_progress)
        worker.completed.connect(self._handle_dds_to_png_complete)
        worker.cancelled.connect(self._handle_build_cancelled)
        worker.error.connect(self._handle_worker_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._cleanup_worker_refs)

        self.dds_to_png_worker = worker
        self.worker_thread = thread
        self.set_busy(True, build_mode=True)
        thread.start()

    def start_build(self) -> None:
        if self._background_task_active():
            return

        config = self.collect_config()
        if config.enable_dds_staging and config.upscale_backend == UPSCALE_BACKEND_NONE:
            self.start_dds_to_png()
            return
        if not self._prepare_workflow_output_roots_for_start(config, include_output_root=True):
            return
        self._apply_pending_archive_workflow_extract_if_needed()
        self._apply_pending_texture_editor_workflow_export_if_needed()
        self._last_build_unknown_review_result = None
        if config.upscale_backend != UPSCALE_BACKEND_NONE:
            self._check_unclassified_files_before_build(config)
            return
        self._begin_build_with_config(config)

    def _begin_build_with_config(self, config: AppConfig) -> None:
        if self._background_task_active():
            return

        self.set_status_message("Preparing build...")
        self.append_log("Starting build.")
        self.reset_progress()
        self._activate_tool_widget(self.workflow_tab)
        self.content_tabs.setCurrentIndex(0)

        worker = BuildWorker(
            config,
            crash_reports_dir=self.crash_reports_dir,
            session_id=self._session_id,
        )
        thread = QThread(self)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.log_message.connect(self.append_log)
        worker.phase_changed.connect(self._handle_phase_changed)
        worker.phase_progress_changed.connect(self._handle_phase_progress_changed)
        worker.total_found.connect(self._handle_total_found)
        worker.current_file.connect(self._handle_current_file)
        worker.progress.connect(self._handle_progress)
        worker.completed.connect(self._handle_build_complete)
        worker.cancelled.connect(self._handle_build_cancelled)
        worker.error.connect(self._handle_worker_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._cleanup_worker_refs)

        self.build_worker = worker
        self.worker_thread = thread
        self.set_busy(True, build_mode=True)
        thread.start()

    def _begin_build_when_idle(self, config: AppConfig, *, attempt: int = 0) -> None:
        if not self._background_task_active():
            self._begin_build_with_config(config)
            return
        if self.utility_worker is not None and attempt < 100:
            QTimer.singleShot(
                10,
                lambda config=config, attempt=attempt + 1: self._begin_build_when_idle(
                    config,
                    attempt=attempt,
                ),
            )
            return
        self.set_status_message("Build could not start after the pre-run classification check.", error=True)
        self.append_log(
            "ERROR: Build start was blocked after the pre-run classification check did not fully release its worker state."
        )

    def _open_classification_review_for_paths(self, paths: Sequence[str]) -> None:
        path_list = [str(path).strip() for path in paths if str(path).strip()]
        self._activate_tool_widget(self.research_tab)
        if not path_list:
            self.set_status_message(
                "Build paused so you can review DDS files that still need a saved local classification in Research -> Classification Review."
            )
            return
        self.research_tab.focus_classification_review_for_paths(
            path_list,
            include_classified=True,
            refresh_if_needed=not bool(getattr(self.research_tab, "research_payload", {})),
        )
        self.set_status_message(
            f"Build paused so you can review/save classification for {len(path_list):,} DDS file(s) in Research -> Classification Review."
        )

    def _review_reference_in_text_search(self, source_path: str, highlight_query: str) -> None:
        normalized_path = source_path.strip().replace("\\", "/").strip("/")
        query = highlight_query.strip()
        if not normalized_path or not query:
            self.set_status_message("The selected reference row is missing its source path or highlight query.", error=True)
            return
        entry: Optional[ArchiveEntry] = None
        for candidate in self.archive_entries:
            if not isinstance(candidate, ArchiveEntry):
                continue
            candidate_path = candidate.path.replace("\\", "/").strip("/")
            if candidate_path.casefold() == normalized_path.casefold():
                entry = candidate
                break
        if entry is None:
            self.set_status_message(
                f"Could not find the archive text entry for {normalized_path}. Refresh archives and try again.",
                error=True,
            )
            return
        if not self.text_search_tab.review_archive_entry(entry, highlight_query=query):
            return
        self._activate_tool_widget(self.text_search_tab)

    def _check_unclassified_files_before_build(self, config: AppConfig) -> None:
        def task(on_log: Callable[[str], None]) -> Dict[str, object]:
            normalized = normalize_config(config, validate_backend_runtime=False)
            dds_files = collect_dds_files(
                normalized.original_dds_root,
                normalized.include_filter_patterns,
            )
            total = len(dds_files)
            if total <= 0:
                raise ValueError("No DDS files were found under the original root with the current filter.")
            processing_plan = build_texture_processing_plan(
                normalized,
                dds_files,
            )
            unknown_entries = [
                entry
                for entry in processing_plan
                if entry.decision.texture_type == "unknown"
                and get_registered_texture_classification(entry.relative_path.as_posix()) is None
            ]
            unknown_paths = [entry.relative_path.as_posix() for entry in unknown_entries]
            processed_unknowns = sum(1 for entry in unknown_entries if entry.requires_png_processing)
            preserved_unknowns = len(unknown_entries) - processed_unknowns
            example_names: List[str] = []
            seen_examples: set[str] = set()
            for rel_path in unknown_paths:
                basename = PurePosixPath(rel_path).name
                if basename.casefold() in seen_examples:
                    continue
                seen_examples.add(basename.casefold())
                example_names.append(basename)
                if len(example_names) >= 6:
                    break
            on_log(
                f"Pre-run classification check: {len(unknown_entries):,} matched DDS file(s) are still unclassified."
            )
            return {
                "total_files": total,
                "unknown_total": len(unknown_entries),
                "processed_unknowns": processed_unknowns,
                "preserved_unknowns": preserved_unknowns,
                "unknown_paths": unknown_paths,
                "example_names": example_names,
                "preset_label": get_texture_preset_definition(normalized.upscale_texture_preset).label,
            }

        def on_complete(result: object) -> None:
            payload = result if isinstance(result, dict) else {}
            unknown_total = int(payload.get("unknown_total", 0) or 0)
            if unknown_total <= 0:
                QTimer.singleShot(0, lambda config=config: self._begin_build_when_idle(config))
                return

            processed_unknowns = int(payload.get("processed_unknowns", 0) or 0)
            preserved_unknowns = int(payload.get("preserved_unknowns", 0) or 0)
            example_names = [
                str(item) for item in payload.get("example_names", [])
                if str(item).strip()
            ]
            preset_label = str(payload.get("preset_label", "") or "").strip()

            box = QMessageBox(self)
            box.setWindowTitle("DDS Files Need Saved Classification")
            box.setIcon(QMessageBox.Question)
            box.setText(
                f"{unknown_total:,} matched DDS file(s) still lack a saved local classification approval for this workflow input."
            )
            detail_lines = []
            if preset_label:
                detail_lines.append(f"Current texture preset: {preset_label}.")
            detail_lines.append(
                "Research may still show an inferred family classification from archive context, but Texture Workflow only stops warning once the DDS has a saved local approval."
            )
            if processed_unknowns <= 0:
                detail_lines.append(
                    "Under the current preset and policy rules, these files will likely be left unchanged."
                )
            elif preserved_unknowns <= 0:
                detail_lines.append(
                    "Under the current preset and policy rules, these files will likely still be processed."
                )
            else:
                detail_lines.append(
                    f"Under the current preset and policy rules, about {processed_unknowns:,} would be processed and {preserved_unknowns:,} would likely be left unchanged."
                )
            detail_lines.append(
                "Review them now if you want to approve classifications before the run starts."
            )
            if example_names:
                detail_lines.extend(
                    [
                        "",
                        "Examples:",
                        ", ".join(example_names[:5]),
                    ]
                )
            box.setInformativeText("\n".join(detail_lines))
            review_button = box.addButton("Review Classifications", QMessageBox.ActionRole)
            continue_button = box.addButton("Continue Anyway", QMessageBox.AcceptRole)
            cancel_button = box.addButton(QMessageBox.Cancel)
            box.setDefaultButton(review_button)
            box.exec()

            clicked = box.clickedButton()
            if clicked == review_button:
                unknown_paths = [
                    str(path) for path in payload.get("unknown_paths", [])
                    if str(path).strip()
                ]
                self.append_log(
                    f"Build paused so Research -> Classification Review can focus on {len(unknown_paths):,} unclassified DDS file(s)."
                )
                QTimer.singleShot(0, lambda paths=unknown_paths: self._open_classification_review_for_paths(paths))
                return
            if clicked != continue_button:
                self.set_status_message("Build cancelled before start.")
                return

            self._last_build_unknown_review_result = payload
            self.append_log(
                f"Continuing build with {unknown_total:,} unclassified DDS file(s)."
            )
            QTimer.singleShot(0, lambda config=config: self._begin_build_when_idle(config))

        self._run_utility_task(
            status_message="Checking for unclassified DDS files before build...",
            task=task,
            on_complete=on_complete,
        )

    def stop_build(self) -> None:
        active_worker = self.build_worker or self.dds_to_png_worker or self.utility_worker
        if active_worker is None:
            return
        active_worker.stop()
        self.set_status_message("Stop requested. Waiting for the current task to exit cleanly...")
        self.append_log("Stop requested by user.")
        if self._utility_updates_archive_progress:
            self.append_archive_log("Stop requested by user.")
            self._set_archive_load_progress(
                "Stop requested. Waiting for the current scan to exit cleanly...",
                phase="Stopping",
            )
        self.stop_button.setEnabled(False)

    def open_output_folder(self) -> None:
        raw = self.output_root_edit.text().strip()
        if not raw:
            self.set_status_message("Output root is empty.", error=True)
            return

        path = Path(raw).expanduser()
        if not path.exists():
            try:
                path.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                self.set_status_message(f"Could not create output root: {exc}", error=True)
                return

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    def _handle_scan_result(self, total: int) -> None:
        self.total_files_value.setText(str(total))
        self.progress_bar.setRange(0, max(total, 1))
        self.progress_bar.setValue(0)
        self.current_file_value.setText("Ready to start")
        self._dashboard_last_result_text = f"Texture scan complete: {total:,} DDS file(s) found."
        self.set_status_message(f"Scan complete. Found {total} DDS files.")

    def _handle_total_found(self, total: int) -> None:
        self.total_files_value.setText(str(total))
        self._set_phase_progress(0, total, "0 / {total} DDS files".format(total=total), "DDS files")
        self.set_status_message(f"Found {total} DDS files. Processing...")

    def _handle_phase_changed(self, phase_name: str, detail: str, indeterminate: bool) -> None:
        self.phase_value.setText(phase_name)
        if indeterminate:
            self.phase_progress_value.setText("Working...")
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setFormat("Working...")
        else:
            total = max(int(self.total_files_value.text() or "0"), 1)
            self.progress_bar.setRange(0, total)
            self.progress_bar.setFormat("%v / %m")
        self.set_status_message(detail)

    def _handle_phase_progress_changed(self, current: int, total: int, detail: str) -> None:
        units = "Items"
        lowered = detail.lower()
        if "node" in lowered:
            units = "Nodes"
        elif "png" in lowered:
            units = "PNG outputs"
        elif "dds" in lowered:
            units = "DDS files"
        self._set_phase_progress(current, total, detail, units)

    def _handle_current_file(self, current_file: str) -> None:
        self.current_file_value.setText(current_file)

    def _handle_progress(self, processed: int, total: int, converted: int, skipped: int, failed: int) -> None:
        self._set_phase_progress(processed, total, f"{processed} / {total} DDS files", "DDS files")
        self.converted_value.setText(str(converted))
        self.skipped_value.setText(str(skipped))
        self.failed_value.setText(str(failed))

    def _set_phase_progress(self, current: int, total: int, detail: str, units: str) -> None:
        self.phase_progress_value.setText(detail)
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(min(max(current, 0), total))
            self.progress_bar.setFormat(f"{units}: %v / %m")
        else:
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setFormat(detail or "Working...")

    def _handle_build_complete(self, summary: RunSummary) -> None:
        self._handle_progress(
            summary.converted + summary.skipped + summary.failed,
            summary.total_files,
            summary.converted,
            summary.skipped,
            summary.failed,
        )
        self.current_file_value.setText("Completed")
        if summary.failed:
            self.set_status_message(
                f"Build completed with {summary.failed} failed file(s). Review the log for details.",
                error=True,
            )
        else:
            unknown_total = int(self._last_build_unknown_review_result.get("unknown_total", 0) or 0) if isinstance(self._last_build_unknown_review_result, dict) else 0
            if unknown_total > 0:
                self.set_status_message(
                    f"Build completed. {unknown_total:,} matched DDS file(s) were still unclassified in this run."
                )
            else:
                self.set_status_message("Build completed successfully.")
        self.append_log(
            f"Finished. Converted/planned={summary.converted}, skipped={summary.skipped}, failed={summary.failed}."
        )
        self._dashboard_last_result_text = (
            "Texture build complete: "
            f"{summary.converted:,} converted/planned, {summary.skipped:,} skipped, {summary.failed:,} failed. "
            f"Output: {self.output_root_edit.text().strip() or 'not set'}"
        )
        if isinstance(self._last_build_unknown_review_result, dict):
            unknown_total = int(self._last_build_unknown_review_result.get("unknown_total", 0) or 0)
            processed_unknowns = int(self._last_build_unknown_review_result.get("processed_unknowns", 0) or 0)
            preserved_unknowns = int(self._last_build_unknown_review_result.get("preserved_unknowns", 0) or 0)
            if unknown_total > 0:
                self.append_log(
                    "Note: "
                    f"{unknown_total:,} matched DDS file(s) were still unclassified in this run. "
                    f"Current-policy estimate before start: {processed_unknowns:,} would be processed and {preserved_unknowns:,} would likely be left unchanged. "
                    "Open Research -> Classification Review if you want to review them."
                )
        if summary.log_csv_path:
            self.append_log(f"CSV log saved to {summary.log_csv_path}")
        self._refresh_dashboard()
        self.refresh_compare_list(select_current=True)
        self._activate_tool_widget(self.workflow_tab)
        self.content_tabs.setCurrentIndex(1)
        self._last_build_unknown_review_result = None

    def _handle_dds_to_png_complete(self, summary: RunSummary) -> None:
        self._handle_progress(
            summary.converted + summary.skipped + summary.failed,
            summary.total_files,
            summary.converted,
            summary.skipped,
            summary.failed,
        )
        self.current_file_value.setText("Completed")
        if summary.failed:
            self.set_status_message(
                f"DDS to PNG conversion completed with {summary.failed} failed file(s). Review the log for details.",
                error=True,
            )
        else:
            self.set_status_message("DDS to PNG conversion completed successfully.")
        self.append_log(
            f"Finished DDS -> PNG. Converted/planned={summary.converted}, skipped={summary.skipped}, failed={summary.failed}."
        )
        self._dashboard_last_result_text = (
            "DDS to PNG complete: "
            f"{summary.converted:,} converted/planned, {summary.skipped:,} skipped, {summary.failed:,} failed."
        )
        if summary.log_csv_path:
            self.append_log(f"CSV log saved to {summary.log_csv_path}")
        self._refresh_dashboard()
        self._activate_tool_widget(self.workflow_tab)
        self.content_tabs.setCurrentIndex(0)

    def _handle_build_cancelled(self, message: str) -> None:
        self.set_status_message(message, error=True)
        self.current_file_value.setText("Stopped")
        self.append_log(message)
        self._last_build_unknown_review_result = None


__all__ = ["TextureWorkflowWorkerMixin"]
