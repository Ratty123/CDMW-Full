"""Archive preview result application helpers."""

from __future__ import annotations

import dataclasses
import time
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtWidgets import QTreeWidgetItem

from cdmw.core.archive_modding import ARCHIVE_MESH_EXTENSIONS
from cdmw.models import ArchivePreviewResult
from cdmw.rendering.native_d3d11_host import find_native_d3d11_host
from cdmw.ui.model_preview_native import ARCHIVE_MODEL_RENDERER_D3D11
from cdmw.workers.archive_preview_workers import _merge_timing_maps


class ArchivePreviewResultMixin:
    """Apply archive preview results to the active preview widgets."""
    def _show_archive_preview_result(
        self,
        result: ArchivePreviewResult,
        *,
        use_loose: bool,
        request_id: Optional[int] = None,
    ) -> float:
        if request_id is not None and request_id != self.archive_preview_request_id:
            return 0.0
        selected_entry = self._current_archive_entry()
        self.archive_preview_showing_loose = use_loose and bool(result.loose_file_path)
        self.archive_preview_requested_loose = bool(self.archive_preview_showing_loose)
        if self.archive_preview_showing_loose:
            title = result.loose_preview_title or result.title or "Archive Preview"
            metadata_summary = result.loose_preview_metadata_summary or result.metadata_summary or "Preview ready."
            detail_text = result.loose_preview_detail_text or result.detail_text or metadata_summary
            warning_badge = "Loose File Preview"
            warning_text = (
                f"Using external loose-file preview from {result.loose_file_path}."
                if result.loose_file_path
                else ""
            )
            preview_image_path = result.loose_preview_image_path
            preview_image = result.loose_preview_image
            preview_media_path = result.loose_preview_media_path
            preview_media_kind = result.loose_preview_media_kind
            if preview_image is not None or preview_image_path:
                preferred_view = "image"
            elif preview_media_path:
                preferred_view = "media"
            else:
                preferred_view = "info"
        else:
            title = result.title or "Archive Preview"
            metadata_summary = result.metadata_summary or "Preview ready."
            current_entry = selected_entry
            family_badge = self._archive_family_badge(getattr(current_entry, "path", "") if current_entry is not None else "")
            if family_badge and family_badge != "Unknown" and f"Family: {family_badge}" not in metadata_summary:
                metadata_summary = f"{metadata_summary} | Family: {family_badge}"
            detail_text = result.detail_text or metadata_summary
            warning_badge = result.warning_badge
            warning_text = result.warning_text
            preview_image_path = result.preview_image_path
            preview_image = result.preview_image
            preview_media_path = result.preview_media_path
            preview_media_kind = result.preview_media_kind
            preferred_view = result.preferred_view

        self.archive_preview_title_label.setText(title)
        self.archive_preview_meta_label.setText(metadata_summary)
        role_label = self._archive_entry_role_label(selected_entry)
        self.archive_preview_role_badge.setText(role_label)
        self.archive_preview_role_badge.setVisible(bool(selected_entry))
        health_text = self._archive_preview_health_text(
            result,
            selected_entry,
            result.model_texture_references if not self.archive_preview_showing_loose else (),
        )
        self._set_archive_preview_health_message(health_text)
        self._set_archive_preview_base_detail_text(detail_text, include_current_model_debug=False)
        self._update_archive_preview_warning_controls(
            badge_text=warning_badge,
            warning_text=warning_text,
            can_toggle_loose=bool(result.loose_file_path),
        )
        if not self.archive_preview_showing_loose:
            self._schedule_archive_texture_reference_update(
                result.model_texture_references,
                result.asset_family_graph,
                request_id=request_id,
            )
        else:
            self._clear_archive_texture_reference_views()

        if preferred_view == "image" and (preview_image is not None or preview_image_path):
            self._deactivate_archive_model_renderers_for_non_model_preview()
            if preview_image is not None:
                self.archive_preview_label.set_preview_image(preview_image, title or "Preview image")
            else:
                self.archive_preview_label.set_preview_image_path(preview_image_path, title or "Preview image")
            self.archive_media_preview.clear_media("No media preview available.")
            self.archive_preview_stack.setCurrentWidget(self.archive_preview_scroll)
            self.archive_preview_tabs.setCurrentIndex(0)
            self._update_archive_model_action_controls(None)
            self._set_archive_preview_image_controls_enabled(True)
            self._apply_archive_preview_zoom()
            return 0.0

        native_package_path = str(getattr(result, "native_preview_package_path", "") or "").strip()
        if preferred_view == "model" and native_package_path and not self.archive_preview_showing_loose:
            if request_id is not None and request_id != self.archive_preview_request_id:
                return 0.0
            if str(getattr(result, "quality_tier", "") or "").strip().lower() == "fast":
                return 0.0
            model_apply_started_at = time.perf_counter()
            renderer_backend = self._archive_model_renderer_backend()
            host_binary = find_native_d3d11_host() if renderer_backend == ARCHIVE_MODEL_RENDERER_D3D11 else None
            if host_binary is not None:
                package_dir = Path(native_package_path)
                valid_package, missing_paths = self._validate_d3d11_preview_package_paths(package_dir)
                if not valid_package:
                    message = "Native D3D11 package validation failed: " + "; ".join(missing_paths[:6])
                    self._record_runtime_event(
                        "d3d11_native_package_invalid_paths",
                        request_id=request_id,
                        package_dir=str(package_dir),
                        missing=list(missing_paths[:12]),
                    )
                    detail_text = f"{detail_text.rstrip()}\n\n{message}\nRebuild the preview package by reselecting the entry or switching renderer mode.".strip()
                    self._set_archive_preview_base_detail_text(detail_text, include_current_model_debug=False)
                    self.archive_preview_info_edit.setPlainText(detail_text)
                    self.archive_preview_stack.setCurrentWidget(self.archive_preview_info_edit)
                    self.archive_preview_tabs.setCurrentIndex(0)
                    self._stop_archive_preview_loading_indicator(success=False)
                    self.set_status_message(message, error=True)
                    self.archive_d3d11_preview_status_label.setText("Preview package validation failed.")
                    self._set_archive_isolated_renderer_debug(
                        "Native D3D11 Preview: package validation failed before launch.\n" + message
                    )
                    return 0.0
                if self._archive_isolated_renderer_process_running():
                    self._set_archive_d3d11_pending_package(package_dir, package_dir / "host_status.json", "native-core")
                else:
                    previous = getattr(self, "archive_isolated_renderer_active_package", None)
                    if previous is not None:
                        self.archive_isolated_renderer_retired_packages.append(previous)
                    self.archive_isolated_renderer_active_package = package_dir
                    self.archive_isolated_renderer_package_source = "native-core"
                detail_text = self._detail_text_with_renderer_note(detail_text, None)
                self._set_archive_preview_base_detail_text(detail_text, include_current_model_debug=False)
                self.archive_media_preview.clear_media("No media preview available.")
                self.archive_preview_label.clear_preview("No image preview available.")
                self.archive_preview_stack.setCurrentWidget(self.archive_d3d11_preview_host)
                self.archive_preview_tabs.setCurrentIndex(0)
                self._update_archive_model_action_controls(None)
                self._set_archive_preview_image_controls_enabled(True)
                self._apply_archive_preview_zoom()
                diagnostics = dict(getattr(result, "native_preview_diagnostics", {}) or {})
                cache_state = str(diagnostics.get("native_preview_package_cache", "") or "").strip().lower()
                if cache_state == "hit":
                    self.set_status_message("Launching cached native D3D11 preview package.")
                else:
                    self.set_status_message("Launching native D3D11 preview package generated by cdmw-preview-core.")
                self._set_archive_isolated_renderer_debug(
                    "Native Preview Core: launching native D3D11 package without Python mesh preparation."
                )
                self._start_archive_isolated_renderer_process(package_dir)
                return max(0.0, float(time.perf_counter() - model_apply_started_at))
            message = (
                "Native Preview Core generated a package, but the native D3D11 host is unavailable. "
                "Build native/cdmw_d3d11_preview or set CDMW_D3D11_PREVIEW_BIN."
            )
            detail_text = f"{detail_text.rstrip()}\n\n{message}".strip()
            self._set_archive_preview_base_detail_text(detail_text, include_current_model_debug=False)
            self.set_status_message(message, error=True)
            self._set_archive_isolated_renderer_debug(message)
            return 0.0

        if preferred_view == "model" and result.preview_model is not None and not self.archive_preview_showing_loose:
            if request_id is not None and request_id != self.archive_preview_request_id:
                return 0.0
            if str(getattr(result, "quality_tier", "") or "").strip().lower() == "fast":
                return 0.0
            model_apply_started_at = time.perf_counter()
            renderer_backend = self._archive_model_renderer_backend()
            if renderer_backend == ARCHIVE_MODEL_RENDERER_D3D11:
                host_binary = find_native_d3d11_host()
                if host_binary is not None:
                    detail_text = self._detail_text_with_renderer_note(detail_text, None)
                    self._set_archive_preview_base_detail_text(detail_text, include_current_model_debug=False)
                    self.archive_media_preview.clear_media("No media preview available.")
                    self.archive_preview_label.clear_preview("No image preview available.")
                    self.archive_preview_stack.setCurrentWidget(self.archive_d3d11_preview_host)
                    self.archive_preview_tabs.setCurrentIndex(0)
                    self._update_archive_model_action_controls(result.preview_model)
                    self._set_archive_preview_image_controls_enabled(True)
                    self._apply_archive_preview_zoom()
                    self._launch_archive_isolated_preview_result(result)
                    return max(0.0, float(time.perf_counter() - model_apply_started_at))
                self._set_archive_isolated_renderer_debug(
                    "Native D3D11 Preview: host binary is unavailable. "
                    "Build native/cdmw_d3d11_preview or set CDMW_D3D11_PREVIEW_BIN."
                )
                self.set_status_message("Native D3D11 preview host is unavailable.", error=True)
                return 0.0

            model_preview_widget = self._selected_archive_model_preview_widget()
            detail_text = self._detail_text_with_renderer_note(detail_text, model_preview_widget)
            self._set_archive_preview_base_detail_text(detail_text, include_current_model_debug=False)
            model_preview_widget.set_prepared_model(
                result.preview_model,
                getattr(result, "prepared_preview_model", None),
            )
            if str(getattr(selected_entry, "extension", "") or "").lower() in {".hkx", ".hkt"}:
                try:
                    model_preview_widget.set_render_settings(
                        dataclasses.replace(
                            model_preview_widget.render_settings(),
                            show_physics_overlay=True,
                            show_physics_simulation_preview=False,
                        )
                    )
                except Exception:
                    pass
                if hasattr(model_preview_widget, "set_physics_overlay_bones_visible"):
                    try:
                        model_preview_widget.set_physics_overlay_bones_visible(False)
                    except Exception:
                        pass
            self._sync_archive_isolated_renderer_if_running(result)
            model_apply_s = max(0.0, float(time.perf_counter() - model_apply_started_at))
            self.archive_media_preview.clear_media("No media preview available.")
            self.archive_preview_label.clear_preview("No image preview available.")
            self.archive_preview_stack.setCurrentWidget(model_preview_widget)
            self._refresh_archive_preview_details_text()
            self.archive_preview_tabs.setCurrentIndex(0)
            self._update_archive_model_action_controls(result.preview_model)
            self._set_archive_preview_image_controls_enabled(True)
            self._apply_archive_preview_zoom()
            return model_apply_s

        if preferred_view == "media" and preview_media_path:
            self._deactivate_archive_model_renderers_for_non_model_preview()
            self.archive_preview_label.clear_preview("No image preview available.")
            self.archive_media_preview.set_media(
                preview_media_path,
                media_kind=preview_media_kind,
                detail_text=detail_text,
            )
            self.archive_preview_stack.setCurrentWidget(self.archive_media_preview)
            self.archive_preview_tabs.setCurrentIndex(0)
            self._update_archive_model_action_controls(None)
            self._set_archive_preview_image_controls_enabled(False)
            return 0.0

        if preferred_view == "text":
            self._deactivate_archive_model_renderers_for_non_model_preview()
            preview_text = result.preview_text or "No text preview available."
            self.archive_preview_text_edit.set_language_for_extension(
                self._archive_preview_text_language_extension(preview_text)
            )
            self.archive_preview_text_edit.setPlainText(preview_text)
            self.archive_preview_stack.setCurrentWidget(self.archive_preview_text_edit)
            self.archive_preview_tabs.setCurrentIndex(0)
            self.archive_preview_label.clear_preview("No image preview available.")
            self.archive_media_preview.clear_media("No media preview available.")
            self._update_archive_model_action_controls(None)
            self._set_archive_preview_image_controls_enabled(False)
            return 0.0

        self._deactivate_archive_model_renderers_for_non_model_preview()
        self.archive_preview_info_edit.setPlainText(detail_text or metadata_summary or "No preview available.")
        self.archive_preview_stack.setCurrentWidget(self.archive_preview_info_edit)
        self.archive_preview_tabs.setCurrentIndex(0)
        self.archive_preview_label.clear_preview("No image preview available.")
        self.archive_media_preview.clear_media("No media preview available.")
        self._update_archive_model_action_controls(None)
        self._set_archive_preview_image_controls_enabled(False)
        return 0.0

    def _toggle_archive_loose_preview(self) -> None:
        result = self.current_archive_preview_result
        if result is None or not str(getattr(result, "loose_file_path", "") or "").strip():
            return
        self.archive_preview_requested_loose = not bool(self.archive_preview_showing_loose)
        self._show_archive_preview_result(result, use_loose=self.archive_preview_requested_loose)

    def _apply_archive_preview_result(
        self,
        result: ArchivePreviewResult,
        *,
        request_id: Optional[int] = None,
        source: str = "worker",
        base_timings: Optional[Dict[str, float]] = None,
        request_started_at: Optional[float] = None,
    ) -> None:
        try:
            if request_id is not None and request_id != self.archive_preview_request_id:
                return
            ui_apply_started_at = time.perf_counter()
            self.current_archive_preview_result = result
            model_apply_s = self._show_archive_preview_result(
                result,
                use_loose=self.archive_preview_requested_loose,
                request_id=request_id,
            )
            ui_apply_s = max(0.0, float(time.perf_counter() - ui_apply_started_at))
            result_timings = getattr(result, "timings", None) if source != "preview_cache" else {}
            timings = _merge_timing_maps(
                result_timings,
                base_timings,
                {
                    "ui_apply_s": ui_apply_s,
                    "model_apply_s": model_apply_s,
                },
            )
            if request_started_at is not None:
                timings["total_s"] = max(0.0, float(time.perf_counter() - request_started_at))
            timing_summary = self._archive_preview_timing_summary(source, timings)
            finalized_result = dataclasses.replace(
                result,
                timings=timings,
                timing_summary=timing_summary,
            )
            self.current_archive_preview_result = finalized_result
            self._refresh_archive_preview_details_text()
            entry_name = finalized_result.title or getattr(self._current_archive_entry(), "basename", "") or "selected entry"
            self._log_archive_preview_timing_if_needed(entry_name, source, timings, timing_summary)
        except Exception as exc:
            self._write_crash_report(
                "archive_preview_result_error",
                "Archive preview result error",
                str(exc),
                context=self._collect_crash_context(),
            )
            self._clear_archive_preview(f"Preview failed: {exc}")
            self.set_status_message(f"Archive preview failed: {exc}", error=True)

    def _set_archive_preview_image_controls_enabled(self, enabled: bool) -> None:
        self.archive_preview_zoom_out_button.setEnabled(enabled)
        self.archive_preview_zoom_fit_button.setEnabled(enabled)
        self.archive_preview_zoom_100_button.setEnabled(enabled)
        self.archive_preview_zoom_in_button.setEnabled(enabled)
        if not enabled:
            self.archive_preview_zoom_value.setText("-")
        else:
            self._update_archive_preview_zoom_label()

    def _handle_archive_current_item_change(
        self,
        current: Optional[QTreeWidgetItem],
        previous: Optional[QTreeWidgetItem],
    ) -> None:
        del previous
        try:
            if bool(getattr(self, "archive_context_menu_selection_suppressed", False)):
                self._schedule_archive_selection_state_update()
                return
            if self._startup_benchmark_enabled():
                self._clear_archive_preview("Select an archive file to preview it here.")
                self._schedule_archive_selection_state_update()
                return
            if current is None:
                self._clear_archive_preview("Select an archive file to preview it here.")
                self._schedule_archive_selection_state_update()
                return
            if self._archive_tree_item_kind(current) == "folder":
                self._show_archive_folder_preview(current)
            else:
                entry = self._current_archive_entry()
                if entry is not None:
                    self._render_archive_preview(entry)
                else:
                    self._show_archive_folder_preview(current)
            self._schedule_archive_selection_state_update()
        except Exception as exc:
            self._write_crash_report(
                "archive_selection_error",
                "Archive Browser selection error",
                str(exc),
                context=self._collect_crash_context(),
            )
            self._clear_archive_preview(f"Preview failed: {exc}")
            self.set_status_message(f"Archive preview failed: {exc}", error=True)

    def _schedule_archive_selection_state_update(self) -> None:
        self.archive_selection_state_timer.start()

    def _set_archive_isolated_renderer_debug(self, text: str) -> None:
        self.archive_isolated_renderer_debug_text = str(text or "").strip()
        self._refresh_archive_preview_details_text()

    def _update_archive_selection_state(self) -> None:
        selected_count, selected_has_dds = self._selected_archive_entry_summary()
        has_filtered_entries = bool(self.archive_filtered_entries)
        has_filtered_dds = self.archive_filtered_dds_count > 0
        workflow_extract_enabled = selected_has_dds if selected_count > 0 else has_filtered_dds
        self.archive_extract_selected_button.setEnabled(self.worker_thread is None and selected_count > 0)
        self.archive_extract_filtered_button.setEnabled(self.worker_thread is None and has_filtered_entries)
        self.archive_extract_to_workflow_button.setEnabled(self.worker_thread is None and workflow_extract_enabled)
        current_entry = self._current_archive_entry()
        self.archive_open_in_editor_button.setEnabled(self.worker_thread is None and current_entry is not None)
        self.archive_resolve_in_research_button.setEnabled(
            self.worker_thread is None
            and current_entry is not None
            and current_entry.extension == ".dds"
        )
        if hasattr(self, "mesh_editor_tab"):
            mesh_selection = (
                current_entry
                if current_entry is not None and current_entry.extension in ARCHIVE_MESH_EXTENSIONS
                else None
            )
            self.mesh_editor_tab.set_archive_selection(mesh_selection)
        self._update_archive_model_action_controls(self._archive_model_preview_controls_target())
