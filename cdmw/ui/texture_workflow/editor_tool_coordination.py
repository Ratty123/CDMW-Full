from __future__ import annotations

"""Tool-setting widget coordination for the standalone Texture Editor tab."""

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QLineEdit

from cdmw.ui.texture_workflow.editor_status_state import texture_editor_tool_status_text
from cdmw.ui.texture_workflow.editor_status_state import texture_editor_sampled_color_status
from cdmw.ui.texture_workflow.editor_tool_state import (
    TextureEditorToolControlSnapshot,
    nudged_texture_editor_brush_hardness,
    nudged_texture_editor_brush_size,
    texture_editor_active_tool_state,
    texture_editor_brush_visual_state,
    texture_editor_recolor_control_state,
    texture_editor_recolor_settings_loaded_status_text,
    texture_editor_tool_settings_from_controls,
    texture_editor_tool_setting_visibility,
)


class TextureEditorToolCoordinationMixin:
    def _pick_color_into(self, line_edit: QLineEdit) -> None:
        color = QColorDialog.getColor(QColor(line_edit.text() or "#C85A30"), self, "Choose color")
        if color.isValid():
            line_edit.setText(color.name().upper())

    def _handle_canvas_color_sampled(self, payload: str) -> None:
        try:
            target, color_hex = payload.split("|", 1)
        except ValueError:
            return
        if target == "paint":
            self.paint_color_edit.setText(color_hex)
        elif target == "secondary":
            self.secondary_color_edit.setText(color_hex)
        elif target == "recolor_source":
            self.recolor_source_edit.setText(color_hex)
        elif target == "recolor_target":
            self.recolor_target_edit.setText(color_hex)
        self._set_status(texture_editor_sampled_color_status(color_hex), False)

    def _nudge_brush_size(self, direction: int) -> None:
        new_value = nudged_texture_editor_brush_size(
            float(self.brush_size_slider.value()),
            direction,
            minimum=self.brush_size_slider.minimum(),
            maximum=self.brush_size_slider.maximum(),
            size_step_mode=str(self.size_step_mode_combo.currentData() or "normal"),
        )
        self.brush_size_slider.setValue(new_value)

    def _nudge_brush_hardness(self, direction: int) -> None:
        new_value = nudged_texture_editor_brush_hardness(
            int(self.hardness_slider.value()),
            direction,
            minimum=self.hardness_slider.minimum(),
            maximum=self.hardness_slider.maximum(),
        )
        self.hardness_slider.setValue(new_value)

    def _handle_tool_settings_changed(self) -> None:
        sender = self.sender()
        if sender is self.brush_preset_combo:
            preset_key = str(self.brush_preset_combo.currentData() or "custom")
            if preset_key != "custom":
                self._apply_brush_preset(preset_key)
        elif (
            not self._applying_brush_preset
            and self._settings_ready
            and sender in {
                self.brush_size_slider,
                self.size_step_mode_combo,
                self.hardness_slider,
                self.roundness_slider,
                self.angle_slider,
                self.smoothing_slider,
                self.opacity_slider,
                self.flow_slider,
                self.spacing_slider,
                self.brush_tip_combo,
                self.brush_pattern_combo,
            }
        ):
            self._mark_brush_preset_custom()
        self.current_tool_settings = texture_editor_tool_settings_from_controls(
            self.current_tool_settings,
            TextureEditorToolControlSnapshot(
                color_hex=self.paint_color_edit.text(),
                secondary_color_hex=self.secondary_color_edit.text(),
                brush_preset=self.brush_preset_combo.currentData(),
                brush_tip=self.brush_tip_combo.currentData(),
                brush_pattern=self.brush_pattern_combo.currentData(),
                custom_brush_tip_path=self.custom_brush_tip_path_edit.text(),
                symmetry_mode=self.symmetry_mode_combo.currentData(),
                size=self.brush_size_slider.value(),
                size_step_mode=self.size_step_mode_combo.currentData(),
                hardness=self.hardness_slider.value(),
                roundness=self.roundness_slider.value(),
                angle_degrees=self.angle_slider.value(),
                smoothing=self.smoothing_slider.value(),
                opacity=self.opacity_slider.value(),
                flow=self.flow_slider.value(),
                spacing=self.spacing_slider.value(),
                strength=self.strength_slider.value(),
                smudge_strength=self.smudge_strength_slider.value(),
                dodge_burn_mode=self.dodge_burn_mode_combo.currentData(),
                dodge_burn_exposure=self.dodge_burn_exposure_slider.value(),
                patch_blend=self.patch_blend_slider.value(),
                gradient_type=self.gradient_type_combo.currentData(),
                paint_blend_mode=self.paint_blend_mode_combo.currentData(),
                fill_tolerance=self.fill_tolerance_slider.value(),
                fill_contiguous=self.fill_contiguous_checkbox.isChecked(),
                sharpen_mode=self.sharpen_mode_combo.currentData(),
                soften_mode=self.soften_mode_combo.currentData(),
                sample_visible_layers=self.sample_visible_layers_checkbox.isChecked(),
                clone_aligned=self.clone_aligned_checkbox.isChecked(),
                selection_combine_mode=self.selection_mode_combo.currentData(),
                lasso_snap_to_edges=self.lasso_snap_checkbox.isChecked(),
                lasso_snap_radius=self.lasso_snap_radius_slider.value(),
                lasso_edge_sensitivity=self.lasso_snap_sensitivity_slider.value(),
                recolor_mode=self.recolor_mode_combo.currentData(),
                recolor_source_hex=self.recolor_source_edit.text(),
                recolor_target_hex=self.recolor_target_edit.text(),
                recolor_tolerance=self.recolor_tolerance_slider.value(),
                recolor_strength=self.recolor_strength_slider.value(),
                recolor_preserve_luminance=self.recolor_preserve_luma_checkbox.isChecked(),
            ),
        )
        brush_visual = texture_editor_brush_visual_state(self.current_tool_settings)
        self.canvas.set_brush_size(brush_visual.size)
        self.canvas.set_brush_visual_state(
            hardness=brush_visual.hardness,
            tip=brush_visual.tip,
            roundness=brush_visual.roundness,
            angle_degrees=brush_visual.angle_degrees,
            pattern=brush_visual.pattern,
        )
        self.canvas.set_symmetry_mode(brush_visual.symmetry_mode)
        self._save_settings()
        self._refresh_tool_visibility()

    def _set_active_tool(self, tool_key: str) -> None:
        tool_state = texture_editor_active_tool_state(self.current_tool_settings, tool_key)
        self.current_tool_settings = tool_state.settings
        for key, button in self.tool_buttons.items():
            button.setChecked(key == tool_key)
        self.canvas.set_tool(tool_key)
        self.canvas.set_clone_source_point(tool_state.clone_source_point)
        self._refresh_tool_visibility()
        self._set_status(texture_editor_tool_status_text(tool_key), False)

    def set_recolor_tool_settings(
        self,
        *,
        mode: str = "tint",
        source_color: str = "#808080",
        target_color: str = "#C85A30",
        tolerance: int = 48,
        strength: int = 100,
        preserve_luminance: bool = True,
    ) -> None:
        state = texture_editor_recolor_control_state(
            mode=mode,
            source_color=source_color,
            target_color=target_color,
            tolerance=tolerance,
            strength=strength,
            preserve_luminance=preserve_luminance,
        )
        index = self.recolor_mode_combo.findData(state.mode)
        if index >= 0:
            self.recolor_mode_combo.setCurrentIndex(index)
        self.recolor_source_edit.setText(state.source_color)
        self.recolor_target_edit.setText(state.target_color)
        self.recolor_tolerance_slider.setValue(state.tolerance)
        self.recolor_strength_slider.setValue(state.strength)
        self.recolor_preserve_luma_checkbox.setChecked(state.preserve_luminance)
        self._handle_tool_settings_changed()
        self._set_active_tool("recolor")
        self._set_status(texture_editor_recolor_settings_loaded_status_text(), False)

    def _refresh_tool_visibility(self) -> None:
        tool = self.current_tool_settings.tool
        has_active_selection = bool(
            self.document is not None
            and (self.document.selection.mode != "none" or self.document.quick_mask_enabled)
        )
        visibility = texture_editor_tool_setting_visibility(
            tool,
            brush_tip=str(self.brush_tip_combo.currentData() or "round"),
            lasso_snap_enabled=self.lasso_snap_checkbox.isChecked(),
            has_active_selection=has_active_selection,
        )
        for key, (label_widget, field_widget) in self._tool_setting_rows.items():
            visible = visibility.rows.get(key, True)
            if label_widget is not None:
                label_widget.setVisible(visible)
            field_widget.setVisible(visible)
        self.selection_section.setVisible(visibility.selection_section_visible)


__all__ = ["TextureEditorToolCoordinationMixin"]
