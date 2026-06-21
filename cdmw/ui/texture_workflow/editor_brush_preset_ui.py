from __future__ import annotations

"""Brush-preset UI coordination for the standalone Texture Editor tab."""

from typing import Optional

from PySide6.QtWidgets import QFileDialog, QInputDialog, QLabel, QWidget

from cdmw.constants import APP_TITLE
from cdmw.ui.texture_workflow.editor_brush_presets import (
    serialize_texture_editor_custom_brush_presets,
    texture_editor_brush_preset_combo_state,
    texture_editor_brush_preset_control_state,
    texture_editor_brush_preset_values,
    texture_editor_cleared_custom_brush_tip_state,
    texture_editor_loaded_custom_brush_tip_state,
    texture_editor_saved_custom_brush_preset_state,
    texture_editor_should_mark_brush_preset_custom,
)


class TextureEditorBrushPresetUiMixin:
    def _add_tool_setting_row(self, key: str, label_text: str, field_widget: QWidget) -> None:
        label_widget: Optional[QLabel]
        if label_text:
            label_widget = QLabel(label_text)
            self.tool_settings_layout.addRow(label_widget, field_widget)
        else:
            label_widget = None
            self.tool_settings_layout.addRow("", field_widget)
        self._tool_setting_rows[key] = (label_widget, field_widget)

    def _rebuild_brush_preset_combo(self, *, preserve_key: Optional[str] = None) -> None:
        combo_state = texture_editor_brush_preset_combo_state(
            self._custom_brush_presets,
            preserve_key=preserve_key,
            current_key=self.brush_preset_combo.currentData(),
        )
        self.brush_preset_combo.blockSignals(True)
        self.brush_preset_combo.clear()
        for entry in combo_state.entries:
            self.brush_preset_combo.addItem(entry.label, entry.key)
        index = self.brush_preset_combo.findData(combo_state.selected_key)
        self.brush_preset_combo.setCurrentIndex(index if index >= 0 else 0)
        self.brush_preset_combo.blockSignals(False)

    def _apply_brush_preset(self, preset_key: str) -> None:
        values = texture_editor_brush_preset_values(self._custom_brush_presets, preset_key)
        if not values:
            return
        state = texture_editor_brush_preset_control_state(values)
        self._applying_brush_preset = True
        try:
            self.brush_size_slider.setValue(state.size)
            self.hardness_slider.setValue(state.hardness)
            self.opacity_slider.setValue(state.opacity)
            self.flow_slider.setValue(state.flow)
            self.spacing_slider.setValue(state.spacing)
            self.roundness_slider.setValue(state.roundness)
            self.angle_slider.setValue(state.angle_degrees)
            self.smoothing_slider.setValue(state.smoothing)
            tip_index = self.brush_tip_combo.findData(state.tip)
            if tip_index >= 0:
                self.brush_tip_combo.setCurrentIndex(tip_index)
            pattern_index = self.brush_pattern_combo.findData(state.pattern)
            if pattern_index >= 0:
                self.brush_pattern_combo.setCurrentIndex(pattern_index)
            self.custom_brush_tip_path_edit.setText(state.custom_tip_path)
            size_mode_index = self.size_step_mode_combo.findData(state.size_step_mode)
            if size_mode_index >= 0:
                self.size_step_mode_combo.setCurrentIndex(size_mode_index)
        finally:
            self._applying_brush_preset = False

    def save_current_brush_preset(self) -> None:
        name, accepted = QInputDialog.getText(self, APP_TITLE, "Brush preset name")
        if not accepted:
            return
        save_state = texture_editor_saved_custom_brush_preset_state(
            self._custom_brush_presets,
            name,
            size=self.brush_size_slider.value(),
            hardness=self.hardness_slider.value(),
            opacity=self.opacity_slider.value(),
            flow=self.flow_slider.value(),
            spacing=self.spacing_slider.value(),
            tip=self.brush_tip_combo.currentData(),
            pattern=self.brush_pattern_combo.currentData(),
            custom_tip_path=self.custom_brush_tip_path_edit.text(),
            roundness=self.roundness_slider.value(),
            angle=self.angle_slider.value(),
            smoothing=self.smoothing_slider.value(),
            size_step_mode=self.size_step_mode_combo.currentData(),
        )
        if not save_state.changed:
            self._set_status(save_state.status_text, save_state.error)
            return
        self._custom_brush_presets = save_state.custom_presets
        self.settings.setValue(
            "texture_editor/custom_brush_presets",
            serialize_texture_editor_custom_brush_presets(self._custom_brush_presets),
        )
        self._rebuild_brush_preset_combo(preserve_key=save_state.preset_name)
        self._set_status(save_state.status_text, save_state.error)

    def load_custom_brush_tip(self) -> None:
        path_text, _ = QFileDialog.getOpenFileName(
            self,
            "Load brush image stamp",
            self._last_open_dir,
            "Image files (*.png *.jpg *.jpeg *.bmp *.tga *.webp);;All files (*.*)",
        )
        if not path_text:
            return
        load_state = texture_editor_loaded_custom_brush_tip_state(path_text)
        if not load_state.changed:
            return
        self.custom_brush_tip_path_edit.setText(load_state.custom_tip_path)
        tip_index = self.brush_tip_combo.findData(load_state.brush_tip_key)
        if tip_index >= 0:
            self.brush_tip_combo.setCurrentIndex(tip_index)
        self._mark_brush_preset_custom()
        self._handle_tool_settings_changed()
        self._set_status(load_state.status_text, load_state.error)

    def clear_custom_brush_tip(self) -> None:
        clear_state = texture_editor_cleared_custom_brush_tip_state(
            self.custom_brush_tip_path_edit.text(),
            current_tip=self.brush_tip_combo.currentData(),
        )
        if not clear_state.changed:
            return
        self.custom_brush_tip_path_edit.clear()
        tip_index = self.brush_tip_combo.findData(clear_state.brush_tip_key)
        if tip_index >= 0:
            self.brush_tip_combo.setCurrentIndex(tip_index)
        self._mark_brush_preset_custom()
        self._handle_tool_settings_changed()
        self._set_status(clear_state.status_text, clear_state.error)

    def _mark_brush_preset_custom(self) -> None:
        if not texture_editor_should_mark_brush_preset_custom(self.brush_preset_combo.currentData()):
            return
        self.brush_preset_combo.blockSignals(True)
        custom_index = self.brush_preset_combo.findData("custom")
        if custom_index >= 0:
            self.brush_preset_combo.setCurrentIndex(custom_index)
        self.brush_preset_combo.blockSignals(False)


__all__ = ["TextureEditorBrushPresetUiMixin"]
