"""Archive preview reset and folder-summary display helpers."""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QTreeWidgetItem

from cdmw.core.archive import format_byte_size
from cdmw.ui.model_preview_native import ARCHIVE_MODEL_RENDERER_D3D11


def archive_model_preview_refresh_tooltip() -> str:
    return "Refresh Archive Preview now. Works even while Mesh Replacement Builder is open."


class ArchivePreviewStateMixin:
    """Archive preview state reset and non-file preview summaries."""

    def _clear_archive_preview(self, message: str) -> None:
        self.archive_preview_request_id += 1
        if hasattr(self, "_shutdown_archive_isolated_renderer_host") and not getattr(self, "_shutting_down", False):
            self._shutdown_archive_isolated_renderer_host()
        self.archive_preview_cache_keys.clear()
        self.archive_preview_request_started_at.clear()
        self.archive_preview_request_phase_timings.clear()
        self.archive_preview_request_sources.clear()
        self.pending_archive_preview_request = None
        self.scheduled_archive_preview_request = None
        self.archive_preview_debounce_timer.stop()
        self._stop_archive_native_preview_prefetch()
        if self.archive_preview_worker is not None:
            self.archive_preview_worker.stop()
        self._stop_archive_preview_loading_indicator(success=None)
        self.current_archive_preview_result = None
        self.archive_preview_requested_loose = False
        self.archive_preview_showing_loose = False
        self._archive_preview_base_detail_text = str(message or "")
        self.archive_preview_title_label.setText("Select an archive file")
        self.archive_preview_meta_label.setText(message)
        self.archive_preview_role_badge.clear()
        self.archive_preview_role_badge.setVisible(False)
        self._set_archive_preview_health_message("", visible=False)
        self._clear_archive_texture_reference_views()
        self.archive_preview_warning_badge.clear()
        self.archive_preview_warning_badge.setVisible(False)
        self.archive_preview_warning_label.clear()
        self.archive_preview_warning_label.setVisible(False)
        self.archive_preview_loose_toggle_button.setVisible(False)
        self.archive_preview_loose_toggle_button.setEnabled(False)
        self.archive_preview_label.clear_preview(message)
        self.archive_media_preview.clear_media(message)
        self._update_archive_model_action_controls(None)
        self.archive_preview_text_edit.clear()
        self.archive_preview_info_edit.setPlainText(message)
        self._refresh_archive_preview_details_text()
        self.archive_preview_stack.setCurrentWidget(self.archive_preview_info_edit)
        self.archive_preview_tabs.setCurrentIndex(0)
        self._set_archive_preview_image_controls_enabled(False)

    def _show_archive_folder_preview(self, item: Optional[QTreeWidgetItem]) -> None:
        self.archive_preview_request_id += 1
        self.archive_preview_cache_keys.clear()
        self.archive_preview_request_started_at.clear()
        self.archive_preview_request_phase_timings.clear()
        self.archive_preview_request_sources.clear()
        self.pending_archive_preview_request = None
        self.scheduled_archive_preview_request = None
        self.archive_preview_debounce_timer.stop()
        if self.archive_preview_worker is not None:
            self.archive_preview_worker.stop()
        self._deactivate_archive_model_renderers_for_non_model_preview()
        self._stop_archive_preview_loading_indicator(success=None)
        self.current_archive_preview_result = None
        self.archive_preview_requested_loose = False
        self.archive_preview_showing_loose = False
        item_kind = self._archive_tree_item_kind(item)
        item_value = self._archive_tree_item_value(item) if item is not None else ()
        folder_path = item.toolTip(0) if item is not None else ""
        if item_kind == "category":
            category = str(item_value or "")
            folder_entry_count = len(self._archive_category_entry_indexes().get(category, ()))
            total_original = 0
            total_stored = 0
            preview_subject = f"Category: {category or 'Unknown'}"
            preview_meta = f"Category | {folder_entry_count:,} entries"
            preview_role = "Category"
        else:
            folder_key = item_value if isinstance(item_value, tuple) else ()
            folder_entry_count, total_original, total_stored = self.archive_tree_folder_preview_stats.get(
                folder_key,
                (0, 0, 0),
            )
            preview_subject = f"Folder: {folder_path or '(root)'}"
            preview_meta = f"Folder | {folder_entry_count:,} entries"
            preview_role = "Folder"
        preview_text = "\n".join(
            [
                preview_subject,
                f"Entries: {folder_entry_count:,}",
                (
                    f"Total original size: {format_byte_size(total_original)}"
                    if item_kind != "category"
                    else "Rows load on demand through the virtual archive model."
                ),
                (
                    f"Total stored size: {format_byte_size(total_stored)}"
                    if item_kind != "category"
                    else "Use filters to narrow very large categories before expanding."
                ),
                "",
                "Select a file to preview its contents.",
            ]
        )
        self.archive_preview_title_label.setText(item.text(0) if item is not None else "Select an archive file")
        self.archive_preview_meta_label.setText(preview_meta)
        self.archive_preview_role_badge.setText(preview_role)
        self.archive_preview_role_badge.setVisible(True)
        self._set_archive_preview_health_message(
            f"{preview_role} summary | Select a file for asset relationships.",
            visible=True,
        )
        self.archive_preview_warning_badge.clear()
        self.archive_preview_warning_badge.setVisible(False)
        self.archive_preview_warning_label.clear()
        self.archive_preview_warning_label.setVisible(False)
        self.archive_preview_loose_toggle_button.setVisible(False)
        self.archive_preview_loose_toggle_button.setEnabled(False)
        self._populate_archive_texture_reference_list(())
        self.archive_preview_info_edit.setPlainText(preview_text)
        self._set_archive_preview_base_detail_text(preview_text, include_current_model_debug=False)
        self.archive_preview_stack.setCurrentWidget(self.archive_preview_info_edit)
        self.archive_preview_tabs.setCurrentIndex(0)
        self.archive_preview_label.clear_preview("Select a file to preview it here.")
        self.archive_media_preview.clear_media("Select a file to preview it here.")
        if self._archive_model_renderer_backend() == ARCHIVE_MODEL_RENDERER_D3D11:
            self._clear_archive_isolated_renderer_surface_for_request()
        self._update_archive_model_action_controls(None)
        self._set_archive_preview_image_controls_enabled(False)

    def _update_archive_preview_warning_controls(
        self,
        *,
        badge_text: str,
        warning_text: str,
        can_toggle_loose: bool,
    ) -> None:
        self.archive_preview_warning_badge.setText(badge_text)
        self.archive_preview_warning_badge.setVisible(bool(badge_text))
        self.archive_preview_warning_label.setText(warning_text)
        self.archive_preview_warning_label.setVisible(bool(warning_text))
        self.archive_preview_loose_toggle_button.setText(
            "Archive File" if self.archive_preview_showing_loose else "Loose File"
        )
        self.archive_preview_loose_toggle_button.setVisible(bool(can_toggle_loose))
        self.archive_preview_loose_toggle_button.setEnabled(bool(can_toggle_loose and not self._shutting_down))

    def _archive_model_preview_supports_textures(self, preview_model: Optional[object]) -> bool:
        if preview_model is None:
            return False
        meshes = getattr(preview_model, "meshes", None)
        if not meshes:
            return False
        for mesh in meshes:
            positions = list(getattr(mesh, "positions", []) or [])
            texture_coordinates = list(getattr(mesh, "texture_coordinates", []) or [])
            has_texture_reference = bool(
                str(getattr(mesh, "preview_texture_path", "") or "").strip()
                or getattr(mesh, "preview_texture_image", None) is not None
            )
            if positions and len(texture_coordinates) == len(positions) and has_texture_reference:
                return True
        return False
