from __future__ import annotations

from PySide6.QtCore import QSize, QTimer
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QApplication

from cdmw.ui.texture_workflow.editor_images import _create_tool_icon
from cdmw.ui.widgets import build_responsive_splitter_sizes, clamp_splitter_sizes, responsive_sidebar_bounds


class TextureEditorUiShellMixin:
    """Owns Texture Editor tab UI shell sizing, font sync, and signal wiring."""

    def _texture_editor_tool_sidebar_bounds(self) -> tuple[int, int, int]:
        minimum, preferred, maximum = responsive_sidebar_bounds(self, role="tool")
        return (max(220, minimum), max(286, preferred), max(374, maximum))

    def _texture_editor_splitter_total_width(self, has_doc: bool) -> int:
        editor_tool_min, _editor_tool_pref, _editor_tool_max = self._texture_editor_tool_sidebar_bounds()
        if not has_doc:
            return max(self.width() - 32, editor_tool_min + 520)
        editor_inspector_min, _editor_inspector_pref, _editor_inspector_max = responsive_sidebar_bounds(self, role="narrow")
        return max(self.width() - 32, editor_tool_min + 520 + editor_inspector_min)

    def _set_texture_editor_splitter_sizes(self, sizes: list[int]) -> None:
        self._texture_editor_splitter_restoring = True
        try:
            self.main_splitter.setSizes(sizes)
        finally:
            self._texture_editor_splitter_restoring = False

    def _texture_editor_default_splitter_sizes(self, *, has_doc: bool) -> list[int]:
        editor_tool_min, _editor_tool_pref, _editor_tool_max = self._texture_editor_tool_sidebar_bounds()
        total_width = self._texture_editor_splitter_total_width(has_doc)
        if not has_doc:
            return [editor_tool_min, max(520, total_width - editor_tool_min), 0]
        editor_inspector_min, _editor_inspector_pref, _editor_inspector_max = responsive_sidebar_bounds(self, role="narrow")
        return build_responsive_splitter_sizes(total_width, [12, 70, 18], [editor_tool_min, 520, editor_inspector_min])

    def _texture_editor_document_splitter_sizes(self) -> list[int]:
        editor_tool_min, _editor_tool_pref, _editor_tool_max = self._texture_editor_tool_sidebar_bounds()
        editor_inspector_min, _editor_inspector_pref, _editor_inspector_max = responsive_sidebar_bounds(self, role="narrow")
        total_width = self._texture_editor_splitter_total_width(True)
        current_sizes = list(self.main_splitter.sizes())
        if len(current_sizes) < 3 or sum(max(0, int(size)) for size in current_sizes) <= 0:
            current_sizes = self._saved_texture_editor_splitter_sizes()
        if len(current_sizes) < 3:
            return self._texture_editor_default_splitter_sizes(has_doc=True)
        left_width = max(editor_tool_min, int(current_sizes[0]))
        right_width = max(editor_inspector_min, int(current_sizes[2]) if int(current_sizes[2]) > 0 else editor_inspector_min)
        center_width = max(520, total_width - left_width - right_width)
        return clamp_splitter_sizes(
            total_width,
            [left_width, center_width, right_width],
            [editor_tool_min, 520, editor_inspector_min],
            fallback_weights=[12, 70, 18],
        )

    def _apply_saved_texture_editor_splitter_sizes(self, *, has_doc: bool) -> bool:
        saved_sizes = self._saved_texture_editor_splitter_sizes()
        if len(saved_sizes) < 3:
            return False
        editor_tool_min, _editor_tool_pref, _editor_tool_max = self._texture_editor_tool_sidebar_bounds()
        if not has_doc:
            total_width = self._texture_editor_splitter_total_width(False)
            left_width = max(editor_tool_min, int(saved_sizes[0]))
            self._set_texture_editor_splitter_sizes([left_width, max(520, total_width - left_width), 0])
            return True
        editor_inspector_min, _editor_inspector_pref, _editor_inspector_max = responsive_sidebar_bounds(self, role="narrow")
        right_width = int(saved_sizes[2]) if int(saved_sizes[2]) > 0 else editor_inspector_min
        restored = clamp_splitter_sizes(
            self._texture_editor_splitter_total_width(True),
            [max(editor_tool_min, int(saved_sizes[0])), max(1, int(saved_sizes[1])), max(editor_inspector_min, right_width)],
            [editor_tool_min, 520, editor_inspector_min],
            fallback_weights=[12, 70, 18],
        )
        self._set_texture_editor_splitter_sizes(restored)
        return True

    def _apply_responsive_splitter_defaults(self) -> None:
        has_doc = self.document is not None
        if self._apply_saved_texture_editor_splitter_sizes(has_doc=has_doc):
            return
        self._set_texture_editor_splitter_sizes(self._texture_editor_default_splitter_sizes(has_doc=has_doc))

    def _apply_document_tab_bar_style(self, font: QFont) -> None:
        metrics = QFontMetrics(font)
        pad_y = max(3, metrics.height() // 5)
        pad_x = max(8, metrics.averageCharWidth())
        min_width = max(88, metrics.horizontalAdvance("Document") + 22)
        max_width = max(min_width + 40, metrics.horizontalAdvance("VeryLongDocumentName.png") + 20)
        self.document_tab_bar.setStyleSheet(
            f"""
            QTabBar::tab {{
                background-color: rgba(255, 255, 255, 0.018);
                border: 1px solid rgba(128, 146, 179, 0.10);
                border-bottom: none;
                padding: {pad_y}px {pad_x}px;
                min-width: {min_width}px;
                max-width: {max_width}px;
                margin-right: 2px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                color: #C9D6EA;
            }}
            QTabBar::tab:selected {{
                background-color: rgba(255, 255, 255, 0.05);
                border-color: rgba(116, 193, 255, 0.22);
                color: #F2F6FF;
            }}
            """
        )

    def _apply_font_sensitive_metrics(self, font: QFont) -> None:
        metrics = QFontMetrics(font)
        standard_button_height = max(24, metrics.height() + 8)
        compact_button_height = max(22, metrics.height() + 6)
        tool_button_height = max(22, metrics.height() + 6)
        tool_icon_size = max(14, min(18, metrics.height() + 2))

        self._apply_document_tab_bar_style(font)
        self.actions_menu_button.setMinimumHeight(standard_button_height)
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
            self.shortcuts_button,
        ):
            button.setMinimumHeight(standard_button_height)
        for button in (
            self.undo_button,
            self.redo_button,
            self.history_restore_button,
            self.history_clear_button,
        ):
            button.setMinimumHeight(compact_button_height)
        self._refresh_tool_button_icons()
        for button in self.tool_buttons.values():
            button.setMinimumHeight(tool_button_height)
            button.setIconSize(QSize(tool_icon_size, tool_icon_size))

    def _refresh_tool_button_icons(self) -> None:
        palette = QApplication.palette()
        for tool_key, button in self.tool_buttons.items():
            button.setIcon(_create_tool_icon(tool_key, palette))

    def sync_ui_font(self, font: QFont) -> None:
        applied_font = QFont(font)
        self.setFont(applied_font)
        for widget in (
            self.document_tab_bar,
            self.left_scroll,
            self.tool_panel,
            self.canvas_panel,
            self.right_panel,
            self.right_scroll,
            self.actions_menu_button,
        ):
            widget.setFont(applied_font)
        self.actions_menu.setFont(applied_font)
        self.metadata_browser.document().setDefaultFont(applied_font)
        self._apply_font_sensitive_metrics(applied_font)
        self._refresh_metadata()

    def sync_ui_font_from_application(self) -> None:
        app = QApplication.instance()
        if app is None:
            return
        self.sync_ui_font(app.font())

    def _apply_empty_state_layout(self, has_doc: bool) -> None:
        self.canvas_toolbar.setVisible(has_doc)
        self.canvas_status_strip.setVisible(has_doc)
        right_sidebar_was_visible = self.right_scroll.isVisible()
        right_handle = self.main_splitter.handle(2)
        self.right_panel.setVisible(has_doc)
        self.right_scroll.setVisible(has_doc)
        if has_doc:
            editor_inspector_min, _editor_inspector_pref, editor_inspector_max = responsive_sidebar_bounds(self, role="narrow")
            self.right_scroll.setMinimumWidth(editor_inspector_min)
            self.right_scroll.setMaximumWidth(editor_inspector_max)
            right_handle.setVisible(True)
            right_handle.setEnabled(True)
        else:
            self.right_scroll.setMinimumWidth(0)
            self.right_scroll.setMaximumWidth(0)
            right_handle.setVisible(False)
            right_handle.setEnabled(False)
            editor_tool_min, _editor_tool_pref, _editor_tool_max = self._texture_editor_tool_sidebar_bounds()
            total_width = self._texture_editor_splitter_total_width(False)
            current_sizes = list(self.main_splitter.sizes())
            left_width = max(editor_tool_min, int(current_sizes[0]) if current_sizes else editor_tool_min)
            self._set_texture_editor_splitter_sizes([left_width, max(520, total_width - left_width), 0])
        if has_doc and not right_sidebar_was_visible:
            QTimer.singleShot(0, lambda: self._set_texture_editor_splitter_sizes(self._texture_editor_document_splitter_sizes()))

    def _handle_main_splitter_moved(self, *_args: object) -> None:
        if self._texture_editor_splitter_restoring:
            return
        self._save_texture_editor_splitter_sizes()

    def _connect_signals(self) -> None:
        self.main_splitter.splitterMoved.connect(self._handle_main_splitter_moved)
        self.document_tab_bar.currentChanged.connect(self._handle_document_tab_changed)
        self.document_tab_bar.tabCloseRequested.connect(self._close_document_tab)
        self.open_file_button.clicked.connect(self.open_file_dialog)
        self.open_archive_button.clicked.connect(self.request_browse_archive)
        self.open_compare_button.clicked.connect(self.request_open_compare)
        self.open_project_button.clicked.connect(self.open_project_dialog)
        self.save_project_button.clicked.connect(self.save_project_dialog)
        self.save_png_button.clicked.connect(self.save_flattened_png_dialog)
        self.export_dds_button.clicked.connect(self.export_dds_dialog)
        self.preview_compressed_button.clicked.connect(self.preview_compressed_dds)
        self.send_replace_button.clicked.connect(self.send_to_replace_assistant)
        self.send_workflow_button.clicked.connect(self.send_to_texture_workflow)
        self.send_item_icons_button.clicked.connect(self.send_to_item_icons)
        self.action_open_file.triggered.connect(self.open_file_dialog)
        self.action_open_archive.triggered.connect(self.request_browse_archive)
        self.action_open_project.triggered.connect(self.open_project_dialog)
        self.action_save_project.triggered.connect(self.save_project_dialog)
        self.action_export_png.triggered.connect(self.save_flattened_png_dialog)
        self.action_export_dds.triggered.connect(self.export_dds_dialog)
        self.action_preview_compressed.triggered.connect(self.preview_compressed_dds)
        self.action_send_replace.triggered.connect(self.send_to_replace_assistant)
        self.action_send_workflow.triggered.connect(self.send_to_texture_workflow)
        self.action_send_item_icons.triggered.connect(self.send_to_item_icons)
        self.native_dds_preset_combo.currentIndexChanged.connect(self._handle_native_dds_preset_changed)
        self.undo_button.clicked.connect(self.undo)
        self.redo_button.clicked.connect(self.redo)
        self.shortcuts_button.clicked.connect(self.open_shortcuts_dialog)
        self.zoom_out_button.clicked.connect(lambda: self._adjust_zoom(-1))
        self.zoom_fit_button.clicked.connect(lambda: self._set_fit_mode(True))
        self.zoom_100_button.clicked.connect(lambda: self._set_zoom(1.0))
        self.zoom_in_button.clicked.connect(lambda: self._adjust_zoom(1))
        self.view_mode_combo.currentIndexChanged.connect(self._handle_view_mode_changed)
        self.compare_split_slider.valueChanged.connect(self._handle_compare_split_changed)
        self.grid_checkbox.toggled.connect(self._handle_grid_state_changed)
        self.grid_size_spin.valueChanged.connect(self._handle_grid_state_changed)
        self.grid_color_button.clicked.connect(self._pick_grid_color)
        self.grid_opacity_spin.valueChanged.connect(self._handle_grid_state_changed)
        for tool_key, button in self.tool_buttons.items():
            button.clicked.connect(lambda checked=False, key=tool_key: self._set_active_tool(key))
        self.canvas.stroke_committed.connect(self._handle_canvas_stroke)
        self.canvas.selection_committed.connect(self._handle_canvas_selection)
        self.canvas.clone_source_picked.connect(self._handle_clone_source_picked)
        self.canvas.color_sampled.connect(self._handle_canvas_color_sampled)
        self.canvas.hover_info_changed.connect(self._handle_canvas_hover_changed)
        self.canvas.wheel_zoom_requested.connect(self._handle_canvas_wheel_zoom)
        self.canvas.floating_transform_requested.connect(self._handle_canvas_floating_transform)
        self.canvas_scroll.horizontalScrollBar().valueChanged.connect(self._handle_canvas_viewport_changed)
        self.canvas_scroll.verticalScrollBar().valueChanged.connect(self._handle_canvas_viewport_changed)
        self.navigator_widget.center_requested.connect(self._handle_navigator_center_requested)
        self.show_rulers_checkbox.toggled.connect(self._handle_navigation_overlay_changed)
        self.show_guides_checkbox.toggled.connect(self._handle_navigation_overlay_changed)
        self.apply_guides_button.clicked.connect(self._handle_navigation_overlay_changed)
        self.clear_guides_button.clicked.connect(self.clear_guides)
        self.vertical_guides_edit.textChanged.connect(lambda *_args: self._schedule_coalesced_ui_refresh())
        self.horizontal_guides_edit.textChanged.connect(lambda *_args: self._schedule_coalesced_ui_refresh())
        self.vertical_guides_edit.editingFinished.connect(self._handle_navigation_overlay_changed)
        self.horizontal_guides_edit.editingFinished.connect(self._handle_navigation_overlay_changed)
        self.paint_color_button.clicked.connect(lambda: self._pick_color_into(self.paint_color_edit))
        self.paint_color_sample_button.clicked.connect(lambda: self.canvas.set_color_sample_target("paint"))
        self.secondary_color_button.clicked.connect(lambda: self._pick_color_into(self.secondary_color_edit))
        self.secondary_color_sample_button.clicked.connect(lambda: self.canvas.set_color_sample_target("secondary"))
        self.recolor_source_pick_button.clicked.connect(lambda: self._pick_color_into(self.recolor_source_edit))
        self.recolor_target_pick_button.clicked.connect(lambda: self._pick_color_into(self.recolor_target_edit))
        self.recolor_source_sample_button.clicked.connect(lambda: self.canvas.set_color_sample_target("recolor_source"))
        self.recolor_target_sample_button.clicked.connect(lambda: self.canvas.set_color_sample_target("recolor_target"))
        self.apply_recolor_button.clicked.connect(self.apply_recolor_to_active_layer)
        self.save_brush_preset_button.clicked.connect(self.save_current_brush_preset)
        self.layers_list.currentItemChanged.connect(lambda *_args: self._handle_layer_selection_changed())
        self.layers_list.model().rowsMoved.connect(self._handle_layers_reordered_by_drag)
        self.add_layer_button.clicked.connect(self.add_layer)
        self.duplicate_layer_button.clicked.connect(self.duplicate_layer)
        self.remove_layer_button.clicked.connect(self.remove_layer)
        self.merge_layer_button.clicked.connect(self.merge_layer_down)
        self.layer_up_button.clicked.connect(lambda: self.reorder_layer(-1))
        self.layer_down_button.clicked.connect(lambda: self.reorder_layer(1))
        self.layer_name_edit.editingFinished.connect(self.rename_selected_layer)
        self.layer_visible_checkbox.toggled.connect(self.toggle_selected_layer_visibility)
        self.layer_opacity_slider.valueChanged.connect(self.preview_selected_layer_properties)
        self.layer_opacity_slider.sliderReleased.connect(self.commit_selected_layer_opacity)
        self.layer_add_mask_button.clicked.connect(self.add_mask_to_selected_layer)
        self.layer_invert_mask_button.clicked.connect(self.invert_selected_layer_mask)
        self.layer_delete_mask_button.clicked.connect(self.delete_selected_layer_mask)
        self.layer_mask_enabled_checkbox.toggled.connect(self.toggle_selected_layer_mask_enabled)
        self.layer_edit_mask_checkbox.toggled.connect(self.toggle_edit_mask_target)
        self.history_list.currentRowChanged.connect(self._handle_history_row_changed)
        self.history_list.itemDoubleClicked.connect(lambda *_args: self.restore_selected_history())
        self.history_restore_button.clicked.connect(self.restore_selected_history)
        self.history_clear_button.clicked.connect(self.clear_history)
        self.selection_copy_layer_button.clicked.connect(self.copy_selection_to_new_layer)
        self.selection_clear_button.clicked.connect(self.clear_selection)
        self.selection_select_all_button.clicked.connect(self.select_all_image)
        self.selection_grow_button.clicked.connect(lambda: self.adjust_selection_size(self.selection_refine_spin.value()))
        self.selection_shrink_button.clicked.connect(lambda: self.adjust_selection_size(-self.selection_refine_spin.value()))
        self.selection_to_mask_button.clicked.connect(self.apply_selection_to_selected_layer_mask)
        self.selection_from_mask_button.clicked.connect(self.load_selected_layer_mask_as_selection)
        self.selection_refine_spin.valueChanged.connect(self._refresh_selection_button_labels)
        self.selection_invert_checkbox.toggled.connect(self.toggle_selection_invert)
        self.selection_quick_mask_checkbox.toggled.connect(self.toggle_quick_mask)
        self.load_custom_brush_tip_button.clicked.connect(self.load_custom_brush_tip)
        self.clear_custom_brush_tip_button.clicked.connect(self.clear_custom_brush_tip)
        self.selection_feather_slider.valueChanged.connect(self.preview_selection_settings)
        self.selection_feather_slider.sliderReleased.connect(self.commit_selection_settings)
        self.channel_red_checkbox.toggled.connect(self._handle_channel_lock_changed)
        self.channel_green_checkbox.toggled.connect(self._handle_channel_lock_changed)
        self.channel_blue_checkbox.toggled.connect(self._handle_channel_lock_changed)
        self.channel_alpha_checkbox.toggled.connect(self._handle_channel_lock_changed)
        self.channel_all_button.clicked.connect(lambda: self._set_channel_lock_state(True, True, True, True))
        self.channel_rgb_button.clicked.connect(lambda: self._set_channel_lock_state(True, True, True, False))
        self.channel_alpha_only_button.clicked.connect(lambda: self._set_channel_lock_state(False, False, False, True))
        self.channel_extract_button.clicked.connect(self.extract_active_channel_to_new_layer)
        self.channel_pack_button.clicked.connect(self.write_active_layer_luma_to_selected_channel)
        self.channel_selection_from_button.clicked.connect(self.load_selected_channel_as_selection)
        self.channel_selection_to_button.clicked.connect(self.write_selection_to_selected_channel)
        self.channel_copy_button.clicked.connect(self.copy_selected_channel)
        self.channel_paste_button.clicked.connect(self.paste_channel_clipboard)
        self.channel_swap_button.clicked.connect(self.swap_selected_channels)
        self.transform_float_layer_button.clicked.connect(self.float_active_layer_copy)
        self.transform_apply_button.clicked.connect(self.apply_floating_transform)
        self.transform_flip_h_button.clicked.connect(lambda: self.flip_floating_selection(True, False))
        self.transform_flip_v_button.clicked.connect(lambda: self.flip_floating_selection(False, True))
        self.transform_rotate_left_button.clicked.connect(lambda: self.rotate_floating_selection(-90))
        self.transform_rotate_right_button.clicked.connect(lambda: self.rotate_floating_selection(90))
        self.transform_commit_button.clicked.connect(self.commit_floating_selection)
        self.transform_cancel_button.clicked.connect(self.cancel_floating_selection)
        self.image_crop_selection_button.clicked.connect(self.crop_document_to_selection)
        self.image_trim_button.clicked.connect(self.trim_document_transparent)
        self.image_resize_button.clicked.connect(self.resize_document_image)
        self.canvas_resize_button.clicked.connect(self.resize_document_canvas)
        self.image_flip_h_button.clicked.connect(lambda: self.flip_document(True, False))
        self.image_flip_v_button.clicked.connect(lambda: self.flip_document(False, True))
        self.image_rotate_left_button.clicked.connect(lambda: self.rotate_document_90(False))
        self.image_rotate_right_button.clicked.connect(lambda: self.rotate_document_90(True))
        self.layer_blend_mode_combo.currentIndexChanged.connect(self.preview_selected_layer_properties)
        self.layer_locked_checkbox.toggled.connect(self.commit_selected_layer_flags)
        self.layer_alpha_locked_checkbox.toggled.connect(self.commit_selected_layer_flags)
        self.adjustment_add_button.clicked.connect(self.add_adjustment_layer)
        self.adjustment_duplicate_button.clicked.connect(self.duplicate_selected_adjustment)
        self.adjustment_remove_button.clicked.connect(self.remove_selected_adjustment)
        self.adjustment_reset_button.clicked.connect(self.reset_selected_adjustment)
        self.adjustment_up_button.clicked.connect(lambda: self.move_selected_adjustment(-1))
        self.adjustment_down_button.clicked.connect(lambda: self.move_selected_adjustment(1))
        self.adjustment_solo_button.clicked.connect(self.solo_selected_adjustment)
        self.adjustment_use_active_mask_button.clicked.connect(self.use_active_layer_as_adjustment_mask)
        self.adjustment_clear_mask_button.clicked.connect(self.clear_selected_adjustment_mask)
        self.adjustments_list.currentItemChanged.connect(lambda *_args: self._handle_adjustment_selection_changed())
        self.adjustment_enabled_checkbox.toggled.connect(self.commit_selected_adjustment_enabled)
        self.adjustment_mode_combo.currentIndexChanged.connect(self._schedule_adjustment_preview)
        self.adjustment_opacity_slider.valueChanged.connect(self._schedule_adjustment_preview)
        self.adjustment_opacity_slider.sliderReleased.connect(self.commit_selected_adjustment_properties)
        self.adjustment_param_a_slider.valueChanged.connect(self._schedule_adjustment_preview)
        self.adjustment_param_a_slider.sliderReleased.connect(self.commit_selected_adjustment_properties)
        self.adjustment_param_b_slider.valueChanged.connect(self._schedule_adjustment_preview)
        self.adjustment_param_b_slider.sliderReleased.connect(self.commit_selected_adjustment_properties)
        self.adjustment_param_c_slider.valueChanged.connect(self._schedule_adjustment_preview)
        self.adjustment_param_c_slider.sliderReleased.connect(self.commit_selected_adjustment_properties)
        self.atlas_export_selection_button.clicked.connect(self.export_selection_region)
        self.atlas_export_grid_button.clicked.connect(self.export_grid_slices)
        for widget in (
            self.paint_color_edit,
            self.secondary_color_edit,
            self.brush_preset_combo,
            self.brush_tip_combo,
            self.brush_pattern_combo,
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
            self.selection_mode_combo,
            self.lasso_snap_checkbox,
            self.lasso_snap_radius_slider,
            self.lasso_snap_sensitivity_slider,
            self.recolor_mode_combo,
            self.recolor_source_edit,
            self.recolor_target_edit,
            self.recolor_tolerance_slider,
            self.recolor_strength_slider,
            self.recolor_preserve_luma_checkbox,
        ):
            if hasattr(widget, "textChanged"):
                widget.textChanged.connect(self._handle_tool_settings_changed)  # type: ignore[attr-defined]
            elif hasattr(widget, "valueChanged"):
                widget.valueChanged.connect(self._handle_tool_settings_changed)  # type: ignore[attr-defined]
            elif hasattr(widget, "currentIndexChanged"):
                widget.currentIndexChanged.connect(self._handle_tool_settings_changed)  # type: ignore[attr-defined]
            elif hasattr(widget, "toggled"):
                widget.toggled.connect(self._handle_tool_settings_changed)  # type: ignore[attr-defined]
        self.clear_clone_source_button.clicked.connect(self.clear_clone_source_point)


__all__ = ["TextureEditorUiShellMixin"]
