from __future__ import annotations

"""Canvas, metadata, layer-list, and action refresh coordination for Texture Editor UI."""

from typing import Optional

import numpy as np
from PySide6.QtCore import QThread, Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QListWidgetItem

from cdmw.ui.texture_workflow.editor_action_state import (
    texture_editor_guide_action_state,
    texture_editor_image_action_state,
    texture_editor_layer_action_state,
    texture_editor_main_action_state,
    texture_editor_tool_action_state,
)
from cdmw.ui.texture_workflow.editor_floating_state import (
    texture_editor_floating_canvas_transform_state,
)
from cdmw.ui.texture_workflow.editor_export_state import texture_editor_native_dds_action_text
from cdmw.ui.texture_workflow.editor_images import (
    _rgba_array_to_qimage,
    texture_editor_layer_thumbnail_preview_pixels,
    texture_editor_quick_mask_overlay_image,
)
from cdmw.ui.texture_workflow.editor_layer_state import (
    texture_editor_current_layer_id,
    texture_editor_layer_by_id,
    texture_editor_layer_list_label,
    texture_editor_layer_refresh_selection_id,
)
from cdmw.ui.texture_workflow.editor_session import (
    texture_editor_active_session_compare_flattened,
    texture_editor_document_composite_revision,
)
from cdmw.ui.texture_workflow.editor_source_binding import texture_editor_metadata_display_state
from cdmw.ui.texture_workflow.editor_status_state import texture_editor_canvas_status_state
from cdmw.ui.texture_workflow.editor_ui_constraints import (
    texture_editor_ui_constraint_lookup_start_state,
    texture_editor_ui_constraint_ready_state,
    texture_editor_ui_constraint_warning_state,
)
from cdmw.ui.texture_workflow.editor_view_state import (
    texture_editor_composite_render_state,
    texture_editor_grid_control_state,
    texture_editor_view_controls_state,
    texture_editor_view_mode_key,
)
from cdmw.ui.texture_workflow.editor_workers import TextureEditorUIConstraintWorker


class TextureEditorRefreshUiMixin:
    def _current_layer_id(self) -> Optional[str]:
        item = self.layers_list.currentItem()
        if item is None:
            return None
        return texture_editor_current_layer_id(item.data(Qt.UserRole))

    def _current_composite_rgba(self) -> Optional[np.ndarray]:
        if self.document is None:
            return None
        revision = texture_editor_document_composite_revision(
            self.document,
            has_floating_pixels=self._floating_pixels is not None,
        )
        composite_state = texture_editor_composite_render_state(
            self.document,
            self.layer_pixels,
            self._floating_pixels,
            revision=revision,
            composite_cache=self._composite_cache,
            composite_cache_revision=self._composite_cache_revision,
            dirty_bounds=self._composite_dirty_bounds,
        )
        self._composite_cache = composite_state.cache
        self._composite_cache_revision = composite_state.cache_revision
        self._composite_dirty_bounds = composite_state.dirty_bounds
        return composite_state.rgba

    def _refresh_canvas(self) -> None:
        if self.document is None:
            self.canvas.set_image(None)
            self.canvas.set_quick_mask_overlay(None)
            self.canvas.set_symmetry_mode("off")
            self._refresh_zoom_indicators()
            self._refresh_navigation_overlays()
            return
        canvas_dirty_bounds = self._composite_dirty_bounds
        flattened = self._current_composite_rgba()
        original_flattened = texture_editor_active_session_compare_flattened(
            self._sessions,
            self._active_session_index,
        )
        self.canvas.set_rgba_images(
            flattened,
            original_rgba=original_flattened,
            dirty_bounds=canvas_dirty_bounds,
        )
        self.canvas.set_selection(self.document.selection)
        self.canvas.set_quick_mask_overlay(texture_editor_quick_mask_overlay_image(self.document))
        floating_state = texture_editor_floating_canvas_transform_state(self.document, self._floating_pixels)
        self.canvas.set_floating_transform_state(
            current_bounds=floating_state.current_bounds,
            origin_bounds=floating_state.origin_bounds,
            offset_x=floating_state.offset_x,
            offset_y=floating_state.offset_y,
            scale_x=floating_state.scale_x,
            scale_y=floating_state.scale_y,
            rotation_degrees=floating_state.rotation_degrees,
        )
        self.canvas.set_clone_source_point(self.current_tool_settings.clone_source_point)
        self.canvas.set_symmetry_mode(self.current_tool_settings.symmetry_mode)
        self.canvas.set_view_mode(texture_editor_view_mode_key(self.view_mode_combo.currentData()))
        self.canvas.set_compare_split_percent(self.compare_split_slider.value())
        grid_state = texture_editor_grid_control_state(
            enabled=self.grid_checkbox.isChecked(),
            grid_size=self.grid_size_spin.value(),
            grid_color=self._grid_color,
            grid_color_hex=self._grid_color.name(QColor.HexRgb),
            grid_opacity=self.grid_opacity_spin.value(),
        )
        self.canvas.set_grid_state(
            enabled=grid_state.enabled,
            grid_size=grid_state.grid_size,
            grid_color=grid_state.grid_color,
            grid_opacity=grid_state.grid_opacity,
        )
        self._refresh_zoom_indicators()
        self._refresh_navigation_overlays()

    def _refresh_metadata(self) -> None:
        warning_state = texture_editor_ui_constraint_warning_state(
            self.document.source_binding if self.document is not None else None,
            self._ui_constraint_warning_cache,
        )
        if warning_state.empty_cache_key:
            self._ui_constraint_warning_cache[warning_state.empty_cache_key] = ""
        if warning_state.lookup_target_path:
            self._start_ui_constraint_lookup(warning_state.lookup_target_path)
        display_state = texture_editor_metadata_display_state(
            self.document,
            ui_constraint_warning=warning_state.warning_text,
        )
        self.warning_label.setVisible(display_state.warning_visible)
        self.warning_label.setText(display_state.warning_text)
        self.metadata_browser.setHtml(display_state.html)
        return

    def _start_ui_constraint_lookup(self, target_path: str) -> None:
        start_state = texture_editor_ui_constraint_lookup_start_state(
            target_path,
            self._ui_constraint_warning_cache,
            pending_cache_key=self._pending_ui_constraint_key,
            worker_active=self._ui_constraint_thread is not None,
        )
        if not start_state.should_start:
            return
        worker = TextureEditorUIConstraintWorker(self.get_archive_entries(), target_path)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._ui_constraint_ready_on_ui, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        worker.finished.connect(self._ui_constraint_finished_on_ui, Qt.ConnectionType.QueuedConnection)
        self._ui_constraint_worker = worker
        self._ui_constraint_thread = thread
        self._pending_ui_constraint_key = start_state.cache_key
        thread.start()

    def _handle_ui_constraint_ready(self, target_path: str, warning_text: str) -> None:
        binding = self.document.source_binding if self.document is not None else None
        ready_state = texture_editor_ui_constraint_ready_state(target_path, warning_text, binding)
        if ready_state.cache_key:
            self._ui_constraint_warning_cache[ready_state.cache_key] = ready_state.warning_text
        if self.document is None:
            return
        if ready_state.should_refresh_metadata:
            self._refresh_metadata()

    def _cleanup_ui_constraint_refs(self) -> None:
        self._ui_constraint_thread = None
        self._ui_constraint_worker = None
        self._pending_ui_constraint_key = ""

    def _layer_thumbnail_icon(self, layer_id: str) -> QIcon:
        if self.document is None:
            return QIcon()
        layer = texture_editor_layer_by_id(self.document.layers, layer_id)
        if layer is None:
            return QIcon()
        cache_key = (layer_id, int(layer.revision))
        cached = self._thumbnail_cache.get(cache_key)
        if cached is not None:
            return cached
        pixels = self.layer_pixels.get(layer_id)
        preview = texture_editor_layer_thumbnail_preview_pixels(pixels)
        if preview is None:
            return QIcon()
        qimage = _rgba_array_to_qimage(preview)
        pixmap = QPixmap.fromImage(qimage).scaled(28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        icon = QIcon(pixmap)
        self._thumbnail_cache[cache_key] = icon
        return icon

    def _refresh_layers(self) -> None:
        current_layer_id = self._current_layer_id()
        target_layer_id = texture_editor_layer_refresh_selection_id(self.document, current_layer_id)
        self._refreshing_layers_list = True
        self.layers_list.clear()
        if self.document is None:
            self._refreshing_layers_list = False
            return
        for layer in reversed(self.document.layers):
            item = QListWidgetItem(texture_editor_layer_list_label(layer))
            item.setIcon(self._layer_thumbnail_icon(layer.layer_id))
            item.setData(Qt.UserRole, layer.layer_id)
            self.layers_list.addItem(item)
            if layer.layer_id == target_layer_id:
                self.layers_list.setCurrentItem(item)
        self._refreshing_layers_list = False
        self._handle_layer_selection_changed()

    def _refresh_canvas_status_strip(self) -> None:
        status = texture_editor_canvas_status_state(
            self.document,
            self.current_tool_settings,
            hover_pixel_info=self._hover_pixel_info,
            editing_mask_target=self._editing_mask_target,
            layer_property_dirty=self._layer_property_dirty,
            adjustment_property_dirty=self._adjustment_property_dirty,
            selected_adjustment=self._selected_adjustment(),
            has_floating_pixels=self._floating_pixels is not None,
        )
        if self.document is None:
            self.canvas_status_zoom_label.setText("No zoom")
        else:
            self._refresh_zoom_indicators()
        self.canvas_status_tool_label.setText(status.tool_text)
        self.canvas_status_layer_label.setText(status.layer_text)
        self.canvas_status_selection_label.setText(status.selection_text)
        self.canvas_status_state_label.setText(status.state_text)
        self.canvas_status_document_label.setText(status.document_text)
        self.canvas_status_pixel_label.setText(status.pixel_text)
        self.canvas_status_source_label.setText(status.source_text)

    def _refresh_editor_views(
        self,
        *,
        canvas: bool = True,
        metadata: bool = False,
        layers: bool = False,
        history: bool = False,
        selection: bool = False,
        adjustments: bool = False,
        transform: bool = False,
        status: bool = True,
        tool_visibility: bool = True,
    ) -> None:
        if canvas:
            self._refresh_canvas()
        if metadata:
            self._refresh_metadata()
        if layers:
            self._refresh_layers()
        if history:
            self._refresh_history_list()
        if selection:
            self._refresh_selection_controls()
        if adjustments:
            self._refresh_adjustments()
        if transform:
            self._refresh_transform_controls()
        if status:
            self._refresh_canvas_status_strip()
        if tool_visibility:
            self._refresh_tool_visibility()

    def _schedule_coalesced_ui_refresh(self) -> None:
        self._coalesced_ui_refresh_timer.start()

    def _flush_coalesced_ui_refresh(self) -> None:
        self._refresh_ui()

    def _refresh_ui(self) -> None:
        sidebar_scroll = self._capture_left_sidebar_scroll()
        self._refresh_editor_views(
            canvas=True, metadata=True, layers=True, history=True, selection=True,
            adjustments=True, transform=True, status=True,
            tool_visibility=False,
        )
        self._refresh_channel_controls()
        has_doc = self.document is not None
        busy = self._busy()
        native_dds_action_text = texture_editor_native_dds_action_text(self.document)
        self.export_dds_button.setText(native_dds_action_text)
        self.action_export_dds.setText(native_dds_action_text)
        main_actions = texture_editor_main_action_state(self.document, busy=busy)
        for button in (
            self.open_file_button,
            self.open_archive_button,
            self.open_compare_button,
            self.open_project_button,
            self.save_project_button,
            self.save_png_button,
            self.export_dds_button,
            self.preview_compressed_button,
            self.send_replace_button,
            self.send_workflow_button,
            self.send_item_icons_button,
            self.add_layer_button,
            self.duplicate_layer_button,
            self.remove_layer_button,
            self.merge_layer_button,
            self.layer_up_button,
            self.layer_down_button,
            self.history_clear_button,
            self.image_crop_selection_button,
            self.image_trim_button,
            self.image_resize_button,
            self.canvas_resize_button,
            self.image_flip_h_button,
            self.image_flip_v_button,
            self.image_rotate_left_button,
            self.image_rotate_right_button,
        ):
            button.setEnabled(
                main_actions.open_enabled
                if button in {self.open_file_button, self.open_archive_button, self.open_project_button}
                else main_actions.document_action_enabled
            )
        self.actions_menu_button.setEnabled(main_actions.actions_menu_enabled)
        for button, action in (
            (self.open_file_button, self.action_open_file),
            (self.open_archive_button, self.action_open_archive),
            (self.open_project_button, self.action_open_project),
            (self.save_project_button, self.action_save_project),
            (self.save_png_button, self.action_export_png),
            (self.export_dds_button, self.action_export_dds),
            (self.preview_compressed_button, self.action_preview_compressed),
            (self.send_replace_button, self.action_send_replace),
            (self.send_workflow_button, self.action_send_workflow),
            (self.send_item_icons_button, self.action_send_item_icons),
        ):
            action.setEnabled(button.isEnabled())
        self.native_dds_preset_combo.setEnabled(main_actions.open_enabled)
        self.native_dds_format_combo.setEnabled(main_actions.document_action_enabled)
        self.native_dds_mip_combo.setEnabled(main_actions.document_action_enabled)
        image_actions = texture_editor_image_action_state(
            self.document,
            busy=busy,
            history_index=self.history_index,
            history_count=len(self.history_snapshots),
        )
        self.image_crop_selection_button.setEnabled(image_actions.crop_selection_enabled)
        self.image_trim_button.setEnabled(image_actions.image_transform_enabled)
        self.image_resize_button.setEnabled(image_actions.image_transform_enabled)
        self.canvas_resize_button.setEnabled(image_actions.image_transform_enabled)
        self.image_flip_h_button.setEnabled(image_actions.image_transform_enabled)
        self.image_flip_v_button.setEnabled(image_actions.image_transform_enabled)
        self.image_rotate_left_button.setEnabled(image_actions.image_transform_enabled)
        self.image_rotate_right_button.setEnabled(image_actions.image_transform_enabled)
        self.undo_button.setEnabled(image_actions.undo_enabled)
        self.redo_button.setEnabled(image_actions.redo_enabled)
        self.shortcuts_button.setEnabled(main_actions.shortcuts_enabled)
        layer_actions = texture_editor_layer_action_state(self.document, busy=busy)
        self.layer_name_edit.setEnabled(layer_actions.property_controls_enabled)
        self.layer_visible_checkbox.setEnabled(layer_actions.property_controls_enabled)
        self.layer_locked_checkbox.setEnabled(layer_actions.property_controls_enabled)
        self.layer_alpha_locked_checkbox.setEnabled(layer_actions.property_controls_enabled)
        self.layer_mask_enabled_checkbox.setEnabled(layer_actions.property_controls_enabled)
        self.layer_edit_mask_checkbox.setEnabled(layer_actions.property_controls_enabled)
        self.layer_add_mask_button.setEnabled(layer_actions.property_controls_enabled)
        self.layer_invert_mask_button.setEnabled(layer_actions.property_controls_enabled)
        self.layer_delete_mask_button.setEnabled(layer_actions.property_controls_enabled)
        self.layer_blend_mode_combo.setEnabled(layer_actions.property_controls_enabled)
        self.layer_opacity_slider.setEnabled(layer_actions.property_controls_enabled)
        view_controls = texture_editor_view_controls_state(
            texture_editor_view_mode_key(self.view_mode_combo.currentData()),
            has_document=has_doc,
            busy=busy,
            grid_enabled=self.grid_checkbox.isChecked(),
        )
        self.view_mode_combo.setEnabled(main_actions.document_action_enabled)
        self.compare_split_slider.setEnabled(view_controls.compare_split_enabled)
        self.grid_checkbox.setEnabled(main_actions.document_action_enabled)
        self.grid_size_spin.setEnabled(view_controls.grid_size_enabled)
        self.grid_color_button.setEnabled(view_controls.grid_color_enabled)
        self.grid_opacity_spin.setEnabled(view_controls.grid_opacity_enabled)
        guide_actions = texture_editor_guide_action_state(
            self.document,
            busy=busy,
            vertical_guides_present=bool(self._vertical_guides),
            horizontal_guides_present=bool(self._horizontal_guides),
            vertical_text=self.vertical_guides_edit.text(),
            horizontal_text=self.horizontal_guides_edit.text(),
        )
        self.navigator_widget.setEnabled(guide_actions.controls_enabled)
        self.show_rulers_checkbox.setEnabled(guide_actions.controls_enabled)
        self.show_guides_checkbox.setEnabled(guide_actions.controls_enabled)
        self.vertical_guides_edit.setEnabled(guide_actions.controls_enabled)
        self.horizontal_guides_edit.setEnabled(guide_actions.controls_enabled)
        self.apply_guides_button.setEnabled(guide_actions.controls_enabled)
        self.clear_guides_button.setEnabled(guide_actions.clear_enabled)
        self.canvas.setEnabled(main_actions.canvas_enabled)
        self.document_tab_bar.setEnabled(main_actions.document_tabs_enabled)
        tool_actions = texture_editor_tool_action_state(
            self.document,
            busy=busy,
            clone_source_point=self.current_tool_settings.clone_source_point,
        )
        for button in self.tool_buttons.values():
            button.setEnabled(tool_actions.controls_enabled)
        for widget in (
            self.paint_color_edit,
            self.paint_color_button,
            self.paint_color_sample_button,
            self.secondary_color_edit,
            self.secondary_color_button,
            self.secondary_color_sample_button,
            self.brush_preset_combo,
            self.save_brush_preset_button,
            self.brush_tip_combo,
            self.brush_pattern_combo,
            self.custom_brush_tip_path_edit,
            self.load_custom_brush_tip_button,
            self.clear_custom_brush_tip_button,
            self.symmetry_mode_combo,
            self.brush_size_slider,
            self.size_step_mode_combo,
            self.hardness_slider,
            self.roundness_slider,
            self.angle_slider,
            self.smoothing_slider,
            self.opacity_slider,
            self.flow_slider,
            self.spacing_slider,
            self.fill_tolerance_slider,
            self.fill_contiguous_checkbox,
            self.paint_blend_mode_combo,
            self.strength_slider,
            self.smudge_strength_slider,
            self.dodge_burn_mode_combo,
            self.dodge_burn_exposure_slider,
            self.patch_blend_slider,
            self.gradient_type_combo,
            self.sharpen_mode_combo,
            self.soften_mode_combo,
            self.sample_visible_layers_checkbox,
            self.clone_aligned_checkbox,
            self.clear_clone_source_button,
            self.lasso_snap_checkbox,
            self.lasso_snap_radius_slider,
            self.lasso_snap_sensitivity_slider,
            self.recolor_mode_combo,
            self.recolor_source_edit,
            self.recolor_source_pick_button,
            self.recolor_source_sample_button,
            self.recolor_target_edit,
            self.recolor_target_pick_button,
            self.recolor_target_sample_button,
            self.recolor_tolerance_slider,
            self.recolor_strength_slider,
            self.recolor_preserve_luma_checkbox,
            self.apply_recolor_button,
            self.selection_mode_combo,
            self.selection_invert_checkbox,
            self.selection_feather_slider,
            self.selection_refine_spin,
            self.selection_quick_mask_checkbox,
            self.selection_copy_layer_button,
            self.selection_select_all_button,
            self.selection_clear_button,
            self.selection_grow_button,
            self.selection_shrink_button,
            self.channel_red_checkbox,
            self.channel_green_checkbox,
            self.channel_blue_checkbox,
            self.channel_alpha_checkbox,
            self.channel_all_button,
            self.channel_rgb_button,
            self.channel_alpha_only_button,
            self.channel_extract_combo,
            self.channel_extract_button,
            self.channel_pack_combo,
            self.channel_pack_button,
            self.channel_selection_combo,
            self.channel_selection_from_button,
            self.channel_selection_to_combo,
            self.channel_selection_to_button,
            self.channel_copy_combo,
            self.channel_copy_button,
            self.channel_paste_combo,
            self.channel_paste_button,
            self.channel_swap_a_combo,
            self.channel_swap_b_combo,
            self.channel_swap_button,
        ):
            widget.setEnabled(tool_actions.controls_enabled)
        self._schedule_left_sidebar_scroll_restore(*sidebar_scroll)
        self.clear_clone_source_button.setEnabled(tool_actions.clear_clone_source_enabled)
        self._apply_empty_state_layout(has_doc)
        self.channels_section.setVisible(has_doc)
        self.metadata_section.setVisible(has_doc)
        self.navigator_section.setVisible(has_doc)
        self.image_section.setVisible(has_doc)
        self.transform_float_layer_button.setEnabled(has_doc and not busy and self.document is not None and bool(self.document.active_layer_id))
        self.transform_section.setVisible(has_doc)
        self._refresh_adjustment_action_state(has_doc=has_doc, busy=busy)
        self._refresh_atlas_action_state(has_doc=has_doc, busy=busy)
        self._update_history_action_state()
        self._refresh_tool_visibility()


__all__ = ["TextureEditorRefreshUiMixin"]
