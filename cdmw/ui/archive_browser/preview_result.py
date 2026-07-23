"""Archive preview result application helpers."""

from __future__ import annotations

import dataclasses
import time
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QTreeWidgetItem

from cdmw.domain.archives.constants import ARCHIVE_MESH_EXTENSIONS
from cdmw.ui.archive_browser.preview_state import (
    archive_model_initial_view_state,
    archive_model_manifest_source_path,
)
from cdmw.ui.shell.lazy_tool_tab import created_tool_widget
from cdmw.models import ArchivePreviewResult
from cdmw.services.mesh_dotnet_preview_package import validate_dotnet_preview_package
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
        self._apply_archive_preview_health(result, selected_entry)
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

        if (not self.archive_preview_showing_loose and preferred_view == "info"
                and str(getattr(result, "quality_tier", "") or "").strip().lower() == "quick"
                and self._archive_isolated_renderer_process_running()):
            return 0.0

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

        dotnet_package_path = str(getattr(result, "dotnet_preview_package_path", "") or "").strip()
        texture_request_id = int(getattr(self, "_archive_texture_request_id", 0) or 0)
        texture_request = bool(
            texture_request_id
            and int(request_id or 0) == texture_request_id
        )
        if texture_request and (preferred_view != "model" or not dotnet_package_path):
            finish_texture_request = getattr(self, "_finish_archive_texture_request", None)
            if callable(finish_texture_request):
                finish_texture_request(
                    texture_request_id,
                    success=False,
                    message="Texture preparation did not produce a resident preview package.",
                )
            return -1.0
        if preferred_view == "model" and not self.archive_preview_showing_loose:
            self.archive_preview_stack.setCurrentWidget(self.archive_d3d11_preview_host)
        if preferred_view == "model" and dotnet_package_path and not self.archive_preview_showing_loose:
            if request_id is not None and request_id != self.archive_preview_request_id:
                return 0.0
            if str(getattr(result, "quality_tier", "") or "").strip().lower() == "fast":
                return 0.0
            model_apply_started_at = time.perf_counter()
            package_dir = Path(dotnet_package_path)
            valid_package, missing_paths = validate_dotnet_preview_package(package_dir)
            if not valid_package:
                message = ".NET/Vortice package validation failed: " + "; ".join(missing_paths[:6])
                self._record_runtime_event(
                    "dotnet_preview_package_invalid",
                    request_id=request_id,
                    package_dir=str(package_dir),
                    missing=list(missing_paths[:12]),
                )
                self._set_archive_preview_base_detail_text(
                    f"{detail_text.rstrip()}\n\n{message}".strip(),
                    include_current_model_debug=False,
                )
                self.set_status_message(message, error=True)
                self.archive_d3d11_preview_status_label.setText(".NET/Vortice package validation failed.")
                if texture_request:
                    finish_texture_request = getattr(self, "_finish_archive_texture_request", None)
                    if callable(finish_texture_request):
                        finish_texture_request(texture_request_id, success=False, message=message)
                    return -1.0
                return 0.0
            same_model = package_dir == getattr(self, "archive_isolated_renderer_active_package", None)
            detail_text = self._detail_text_with_renderer_note(detail_text, None)
            self._set_archive_preview_base_detail_text(detail_text, include_current_model_debug=False)
            self.archive_media_preview.clear_media("No media preview available.")
            self.archive_preview_label.clear_preview("No image preview available.")
            self.archive_preview_stack.setCurrentWidget(self.archive_d3d11_preview_host)
            self.archive_preview_tabs.setCurrentIndex(0)
            self._update_archive_model_action_controls(None)
            self._set_archive_preview_image_controls_enabled(True)
            self._apply_archive_preview_zoom()
            initial_view_state = None
            if not same_model:
                selected_source_path = str(
                    getattr(selected_entry, "path", "") if selected_entry is not None else ""
                ).strip()
                initial_view_state = archive_model_initial_view_state(
                    selected_source_path or archive_model_manifest_source_path(package_dir)
                )
            if not self.archive_d3d11_preview_host.load_package(
                package_dir,
                reset_view=not same_model and not texture_request,
                initial_view_state=initial_view_state,
            ):
                message = ".NET/Vortice Preview rejected the prepared package."
                self.set_status_message(message, error=True)
                if texture_request:
                    finish_texture_request = getattr(self, "_finish_archive_texture_request", None)
                    if callable(finish_texture_request):
                        finish_texture_request(texture_request_id, success=False, message=message)
                    return -1.0
                return 0.0
            effective_settings = getattr(self, "_archive_preview_effective_render_settings", None)
            render_settings = (
                effective_settings(request_id)
                if callable(effective_settings)
                else self._current_model_preview_render_settings()
            )
            if texture_request:
                controller = self.archive_d3d11_preview_host.controller
                self._archive_texture_package_generation = int(controller.package_generation)
                self._archive_texture_package_path = str(package_dir)
                self._archive_texture_render_settings = render_settings
                if (
                    int(controller.applied_package_generation) == int(controller.package_generation)
                    and self._archive_package_key(controller.applied_package_path)
                    == self._archive_package_key(package_dir)
                ):
                    QTimer.singleShot(
                        0,
                        lambda path=str(package_dir), generation=int(controller.package_generation): (
                            self._handle_archive_resident_package_applied(path, generation)
                        ),
                    )
            else:
                self.archive_isolated_renderer_active_package = package_dir
                self.archive_isolated_renderer_package_source = "dotnet-canonical"
                self.archive_d3d11_preview_host.set_render_tuning(render_settings)
                self._archive_textures_visible = False
                sync_texture_action = getattr(self, "_sync_archive_texture_action_state", None)
                if callable(sync_texture_action):
                    sync_texture_action()
            self.archive_d3d11_preview_status_label.setText(".NET/Vortice Preview")
            if not texture_request:
                self.set_status_message("Opening resident .NET/Vortice Preview.")
            self._set_archive_isolated_renderer_debug(
                ".NET/Vortice Preview: resident canonical package requested."
            )
            return max(0.0, float(time.perf_counter() - model_apply_started_at))

        if preferred_view == "model" and result.preview_model is not None and not self.archive_preview_showing_loose:
            if request_id is not None and request_id != self.archive_preview_request_id:
                return 0.0
            if str(getattr(result, "quality_tier", "") or "").strip().lower() == "fast":
                return 0.0
            message = (
                "The model decoder completed, but no canonical .NET/Vortice package was published. "
                "The legacy renderer is not used as a fallback."
            )
            self._set_archive_preview_base_detail_text(
                f"{detail_text.rstrip()}\n\n{message}".strip(),
                include_current_model_debug=False,
            )
            self.set_status_message(message, error=True)
            self._deactivate_archive_model_renderers_for_non_model_preview()
            return 0.0

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

    def _apply_archive_preview_health(self, result: ArchivePreviewResult, selected_entry: object) -> None:
        references = result.model_texture_references if not self.archive_preview_showing_loose else ()
        health_text = self._archive_preview_health_text(result, selected_entry, references)
        self._set_archive_preview_health_message(health_text)

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
        texture_request_id = int(getattr(self, "_archive_texture_request_id", 0) or 0)
        texture_request = bool(
            texture_request_id
            and int(request_id or 0) == texture_request_id
        )
        previous_result = getattr(self, "current_archive_preview_result", None)
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
            if texture_request and model_apply_s < 0.0:
                self.current_archive_preview_result = previous_result
                self._refresh_archive_preview_details_text()
                return
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
            if texture_request:
                self._archive_pending_texture_result = finalized_result
                self.current_archive_preview_result = previous_result
                self._refresh_archive_preview_details_text()
                return
            self._refresh_archive_preview_details_text()
            if (
                not texture_request
                and str(getattr(finalized_result, "preferred_view", "") or "").strip().lower() == "model"
                and str(getattr(finalized_result, "dotnet_preview_package_path", "") or "").strip()
                and self._current_model_preview_render_settings().use_textures_by_default
                and not bool(
                    getattr(self, "_archive_active_package_has_textures", lambda: False)()
                )
                and not bool(getattr(self, "_archive_texture_request_loading", False))
            ):
                request_textures = getattr(self, "_request_archive_preview_textures", None)
                if callable(request_textures):
                    QTimer.singleShot(0, lambda callback=request_textures: callback(automatic=True))
            entry_name = finalized_result.title or getattr(self._current_archive_entry(), "basename", "") or "selected entry"
            self._log_archive_preview_timing_if_needed(entry_name, source, timings, timing_summary)
        except Exception as exc:
            self._write_crash_report(
                "archive_preview_result_error",
                "Archive preview result error",
                str(exc),
                context=self._collect_crash_context(),
            )
            if texture_request:
                self.current_archive_preview_result = previous_result
                finish_texture_request = getattr(self, "_finish_archive_texture_request", None)
                if callable(finish_texture_request):
                    finish_texture_request(texture_request_id, success=False, message=str(exc))
                self._refresh_archive_preview_details_text()
                return
            self.current_archive_preview_result = previous_result
            preserve_resident = getattr(self, "_preserve_archive_resident_scene_error", None)
            if callable(preserve_resident) and preserve_resident(str(exc)):
                self._refresh_archive_preview_details_text()
                return
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
        mesh_editor_tab = created_tool_widget(getattr(self, "mesh_editor_tab", None))
        if mesh_editor_tab is not None:
            mesh_selection = (
                current_entry
                if current_entry is not None and current_entry.extension in ARCHIVE_MESH_EXTENSIONS
                else None
            )
            mesh_editor_tab.set_archive_selection(mesh_selection)
        self._update_archive_model_action_controls(self._archive_model_preview_controls_target())
