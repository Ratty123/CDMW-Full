from __future__ import annotations

"""Settings load/save coordination for the standalone Texture Editor tab."""

from typing import Sequence

from PySide6.QtGui import QColor

from cdmw.ui.texture_workflow.editor_view_state import texture_editor_grid_color_hex, texture_editor_view_mode_key


class TextureEditorSettingsPersistenceMixin:
    def _saved_texture_editor_splitter_sizes(self) -> list[int]:
        raw_sizes = self.settings.value("texture_editor/main_splitter_sizes", "")
        if isinstance(raw_sizes, str):
            pieces: Sequence[object] = [piece.strip() for piece in raw_sizes.split(",")]
        elif isinstance(raw_sizes, Sequence):
            pieces = raw_sizes
        else:
            return []
        parsed: list[int] = []
        for piece in pieces:
            if len(parsed) >= 3:
                break
            try:
                value = int(piece)
            except (TypeError, ValueError):
                return []
            if value < 0:
                return []
            parsed.append(value)
        if len(parsed) != 3 or parsed[0] <= 0 or parsed[1] <= 0:
            return []
        return parsed

    def _save_texture_editor_splitter_sizes(self) -> None:
        if not self._settings_ready or self._texture_editor_splitter_restoring:
            return
        sizes = [max(0, int(size)) for size in self.main_splitter.sizes()]
        if len(sizes) != 3 or sizes[0] <= 0 or sizes[1] <= 0:
            return
        self.settings.setValue("texture_editor/main_splitter_sizes", ",".join(str(size) for size in sizes))

    def _load_settings(self) -> None:
        self.paint_color_edit.setText(str(self.settings.value("texture_editor/paint_color", "#C85A30")))
        self.secondary_color_edit.setText(str(self.settings.value("texture_editor/secondary_color", "#FFFFFF")))
        brush_preset = str(self.settings.value("texture_editor/brush_preset", "custom"))
        self._rebuild_brush_preset_combo(preserve_key=brush_preset)
        brush_tip = str(self.settings.value("texture_editor/brush_tip", "round"))
        brush_tip_index = self.brush_tip_combo.findData(brush_tip)
        if brush_tip_index >= 0:
            self.brush_tip_combo.setCurrentIndex(brush_tip_index)
        brush_pattern = str(self.settings.value("texture_editor/brush_pattern", "solid"))
        brush_pattern_index = self.brush_pattern_combo.findData(brush_pattern)
        if brush_pattern_index >= 0:
            self.brush_pattern_combo.setCurrentIndex(brush_pattern_index)
        self.custom_brush_tip_path_edit.setText(str(self.settings.value("texture_editor/custom_brush_tip_path", "")))
        symmetry_mode = str(self.settings.value("texture_editor/symmetry_mode", "off"))
        symmetry_mode_index = self.symmetry_mode_combo.findData(symmetry_mode)
        if symmetry_mode_index >= 0:
            self.symmetry_mode_combo.setCurrentIndex(symmetry_mode_index)
        self.brush_size_slider.setValue(int(self.settings.value("texture_editor/brush_size", 32)))
        size_step_mode = str(self.settings.value("texture_editor/size_step_mode", "normal"))
        size_step_index = self.size_step_mode_combo.findData(size_step_mode)
        if size_step_index >= 0:
            self.size_step_mode_combo.setCurrentIndex(size_step_index)
        self.hardness_slider.setValue(int(self.settings.value("texture_editor/hardness", 80)))
        self.roundness_slider.setValue(int(self.settings.value("texture_editor/roundness", 100)))
        self.angle_slider.setValue(int(self.settings.value("texture_editor/angle_degrees", 0)))
        self.smoothing_slider.setValue(int(self.settings.value("texture_editor/smoothing", 0)))
        self.opacity_slider.setValue(int(self.settings.value("texture_editor/opacity", 100)))
        self.flow_slider.setValue(int(self.settings.value("texture_editor/flow", 100)))
        self.spacing_slider.setValue(int(self.settings.value("texture_editor/spacing", 20)))
        self.strength_slider.setValue(int(self.settings.value("texture_editor/strength", 25)))
        self.smudge_strength_slider.setValue(int(self.settings.value("texture_editor/smudge_strength", 45)))
        dodge_burn_mode = str(self.settings.value("texture_editor/dodge_burn_mode", "dodge_midtones"))
        dodge_burn_mode_index = self.dodge_burn_mode_combo.findData(dodge_burn_mode)
        if dodge_burn_mode_index >= 0:
            self.dodge_burn_mode_combo.setCurrentIndex(dodge_burn_mode_index)
        self.dodge_burn_exposure_slider.setValue(int(self.settings.value("texture_editor/dodge_burn_exposure", 20)))
        self.patch_blend_slider.setValue(int(self.settings.value("texture_editor/patch_blend", 70)))
        gradient_type = str(self.settings.value("texture_editor/gradient_type", "linear"))
        gradient_index = self.gradient_type_combo.findData(gradient_type)
        if gradient_index >= 0:
            self.gradient_type_combo.setCurrentIndex(gradient_index)
        paint_blend_mode = str(self.settings.value("texture_editor/paint_blend_mode", "normal"))
        paint_blend_index = self.paint_blend_mode_combo.findData(paint_blend_mode)
        if paint_blend_index >= 0:
            self.paint_blend_mode_combo.setCurrentIndex(paint_blend_index)
        selection_mode = str(self.settings.value("texture_editor/selection_combine_mode", "replace"))
        selection_mode_index = self.selection_mode_combo.findData(selection_mode)
        if selection_mode_index >= 0:
            self.selection_mode_combo.setCurrentIndex(selection_mode_index)
        sharpen_mode = str(self.settings.value("texture_editor/sharpen_mode", "unsharp_mask"))
        soften_mode = str(self.settings.value("texture_editor/soften_mode", "gaussian"))
        sharpen_index = self.sharpen_mode_combo.findData(sharpen_mode)
        if sharpen_index >= 0:
            self.sharpen_mode_combo.setCurrentIndex(sharpen_index)
        soften_index = self.soften_mode_combo.findData(soften_mode)
        if soften_index >= 0:
            self.soften_mode_combo.setCurrentIndex(soften_index)
        self.sample_visible_layers_checkbox.setChecked(bool(self.settings.value("texture_editor/sample_visible_layers", True)))
        self.clone_aligned_checkbox.setChecked(bool(self.settings.value("texture_editor/clone_aligned", True)))
        self.fill_tolerance_slider.setValue(int(self.settings.value("texture_editor/fill_tolerance", 24)))
        self.fill_contiguous_checkbox.setChecked(bool(self.settings.value("texture_editor/fill_contiguous", True)))
        self.lasso_snap_checkbox.setChecked(bool(self.settings.value("texture_editor/lasso_snap_to_edges", False)))
        self.lasso_snap_radius_slider.setValue(int(self.settings.value("texture_editor/lasso_snap_radius", 10)))
        self.lasso_snap_sensitivity_slider.setValue(int(self.settings.value("texture_editor/lasso_edge_sensitivity", 55)))
        self.selection_refine_spin.setValue(int(self.settings.value("texture_editor/selection_refine_amount", 4)))
        self.recolor_source_edit.setText(str(self.settings.value("texture_editor/recolor_source", "#808080")))
        self.recolor_target_edit.setText(str(self.settings.value("texture_editor/recolor_target", "#C85A30")))
        self.recolor_tolerance_slider.setValue(int(self.settings.value("texture_editor/recolor_tolerance", 48)))
        self.recolor_strength_slider.setValue(int(self.settings.value("texture_editor/recolor_strength", 100)))
        self.recolor_preserve_luma_checkbox.setChecked(bool(self.settings.value("texture_editor/recolor_preserve_luma", True)))
        view_mode = str(self.settings.value("texture_editor/view_mode", "edited"))
        view_mode_index = self.view_mode_combo.findData(view_mode)
        if view_mode_index >= 0:
            self.view_mode_combo.setCurrentIndex(view_mode_index)
        self.compare_split_slider.setValue(int(self.settings.value("texture_editor/compare_split", 50)))
        self.grid_checkbox.setChecked(bool(self.settings.value("texture_editor/grid_enabled", False)))
        self.grid_size_spin.setValue(int(self.settings.value("texture_editor/grid_size", 64)))
        self._set_grid_color(
            QColor(str(self.settings.value("texture_editor/grid_color", "#74C1FF"))),
            save=False,
            apply=False,
        )
        self.grid_opacity_spin.setValue(int(self.settings.value("texture_editor/grid_opacity", 42)))
        self._last_open_dir = str(self.settings.value("texture_editor/last_open_dir", str(self.base_dir)))
        self._last_save_dir = str(self.settings.value("texture_editor/last_save_dir", str(self.base_dir)))
        mode = str(self.settings.value("texture_editor/recolor_mode", "tint"))
        index = self.recolor_mode_combo.findData(mode)
        if index >= 0:
            self.recolor_mode_combo.setCurrentIndex(index)
        self._handle_tool_settings_changed()

    def _save_settings(self) -> None:
        if not self._settings_ready:
            return
        self.settings.setValue("texture_editor/paint_color", self.paint_color_edit.text())
        self.settings.setValue("texture_editor/secondary_color", self.secondary_color_edit.text())
        self.settings.setValue("texture_editor/brush_preset", self.brush_preset_combo.currentData())
        self.settings.setValue("texture_editor/brush_tip", self.brush_tip_combo.currentData())
        self.settings.setValue("texture_editor/brush_pattern", self.brush_pattern_combo.currentData())
        self.settings.setValue("texture_editor/custom_brush_tip_path", self.custom_brush_tip_path_edit.text())
        self.settings.setValue("texture_editor/symmetry_mode", self.symmetry_mode_combo.currentData())
        self.settings.setValue("texture_editor/brush_size", self.brush_size_slider.value())
        self.settings.setValue("texture_editor/size_step_mode", self.size_step_mode_combo.currentData())
        self.settings.setValue("texture_editor/hardness", self.hardness_slider.value())
        self.settings.setValue("texture_editor/roundness", self.roundness_slider.value())
        self.settings.setValue("texture_editor/angle_degrees", self.angle_slider.value())
        self.settings.setValue("texture_editor/smoothing", self.smoothing_slider.value())
        self.settings.setValue("texture_editor/opacity", self.opacity_slider.value())
        self.settings.setValue("texture_editor/flow", self.flow_slider.value())
        self.settings.setValue("texture_editor/spacing", self.spacing_slider.value())
        self.settings.setValue("texture_editor/strength", self.strength_slider.value())
        self.settings.setValue("texture_editor/smudge_strength", self.smudge_strength_slider.value())
        self.settings.setValue("texture_editor/dodge_burn_mode", self.dodge_burn_mode_combo.currentData())
        self.settings.setValue("texture_editor/dodge_burn_exposure", self.dodge_burn_exposure_slider.value())
        self.settings.setValue("texture_editor/patch_blend", self.patch_blend_slider.value())
        self.settings.setValue("texture_editor/gradient_type", self.gradient_type_combo.currentData())
        self.settings.setValue("texture_editor/paint_blend_mode", self.paint_blend_mode_combo.currentData())
        self.settings.setValue("texture_editor/selection_combine_mode", self.selection_mode_combo.currentData())
        self.settings.setValue("texture_editor/sharpen_mode", self.sharpen_mode_combo.currentData())
        self.settings.setValue("texture_editor/soften_mode", self.soften_mode_combo.currentData())
        self.settings.setValue("texture_editor/sample_visible_layers", self.sample_visible_layers_checkbox.isChecked())
        self.settings.setValue("texture_editor/clone_aligned", self.clone_aligned_checkbox.isChecked())
        self.settings.setValue("texture_editor/fill_tolerance", self.fill_tolerance_slider.value())
        self.settings.setValue("texture_editor/fill_contiguous", self.fill_contiguous_checkbox.isChecked())
        self.settings.setValue("texture_editor/lasso_snap_to_edges", self.lasso_snap_checkbox.isChecked())
        self.settings.setValue("texture_editor/lasso_snap_radius", self.lasso_snap_radius_slider.value())
        self.settings.setValue("texture_editor/lasso_edge_sensitivity", self.lasso_snap_sensitivity_slider.value())
        self.settings.setValue("texture_editor/selection_refine_amount", self.selection_refine_spin.value())
        self.settings.setValue("texture_editor/recolor_mode", self.recolor_mode_combo.currentData())
        self.settings.setValue("texture_editor/recolor_source", self.recolor_source_edit.text())
        self.settings.setValue("texture_editor/recolor_target", self.recolor_target_edit.text())
        self.settings.setValue("texture_editor/recolor_tolerance", self.recolor_tolerance_slider.value())
        self.settings.setValue("texture_editor/recolor_strength", self.recolor_strength_slider.value())
        self.settings.setValue("texture_editor/recolor_preserve_luma", self.recolor_preserve_luma_checkbox.isChecked())
        self.settings.setValue("texture_editor/view_mode", texture_editor_view_mode_key(self.view_mode_combo.currentData()))
        self.settings.setValue("texture_editor/compare_split", self.compare_split_slider.value())
        self.settings.setValue("texture_editor/grid_enabled", self.grid_checkbox.isChecked())
        self.settings.setValue("texture_editor/grid_size", self.grid_size_spin.value())
        self.settings.setValue(
            "texture_editor/grid_color",
            texture_editor_grid_color_hex(self._grid_color.name(QColor.HexRgb)),
        )
        self.settings.setValue("texture_editor/grid_opacity", self.grid_opacity_spin.value())
        self.settings.setValue("texture_editor/last_open_dir", self._last_open_dir)
        self.settings.setValue("texture_editor/last_save_dir", self._last_save_dir)
        self._save_texture_editor_splitter_sizes()

    def flush_settings_save(self) -> None:
        self._store_active_session()
        self._save_settings()


__all__ = ["TextureEditorSettingsPersistenceMixin"]
