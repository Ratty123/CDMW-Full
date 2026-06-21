from __future__ import annotations

"""Shortcut registration and editing UI for the standalone Texture Editor tab."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QDialog

from cdmw.ui.texture_workflow.editor_dialogs import ShortcutEditorDialog
from cdmw.ui.texture_workflow.editor_shortcuts import (
    default_texture_editor_shortcuts,
    load_texture_editor_shortcuts,
    texture_editor_shortcut_labels,
    texture_editor_shortcuts_updated_status_text,
)


class TextureEditorShortcutsUiMixin:
    def _register_shortcut(self, sequence_text: str, callback) -> None:
        text = (sequence_text or "").strip()
        if not text:
            return
        shortcut = QShortcut(QKeySequence(text), self)
        shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        shortcut.activated.connect(callback)
        self._shortcut_objects.append(shortcut)

    def _rebuild_shortcuts(self) -> None:
        for shortcut in self._shortcut_objects:
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self._shortcut_objects = []
        shortcut_map = load_texture_editor_shortcuts(self.settings.value)
        bindings = {
            "open_file": self.open_file_dialog,
            "open_archive": self.request_browse_archive,
            "open_compare": self.request_open_compare,
            "open_project": self.open_project_dialog,
            "save_project": self.save_project_dialog,
            "save_png": self.save_flattened_png_dialog,
            "send_replace": self.send_to_replace_assistant,
            "send_workflow": self.send_to_texture_workflow,
            "send_item_icons": self.send_to_item_icons,
            "undo": self.undo,
            "redo": self.redo,
            "clear_selection": self.clear_selection,
            "clear_selection_alt": self.clear_selection,
            "copy_selection_layer": self.copy_selection_to_new_layer,
            "new_layer": self.add_layer,
            "copy_layer": self.copy_content,
            "cut_selection": self.cut_selection_to_floating,
            "paste_layer": self.paste_content,
            "paste_centered": self.paste_content_centered,
            "transform_float_layer": self.float_active_layer_copy,
            "fit_view": lambda: self._set_fit_mode(True),
            "actual_size": lambda: self._set_zoom(1.0),
            "tool_paint": lambda: self._set_active_tool("paint"),
            "tool_erase": lambda: self._set_active_tool("erase"),
            "tool_fill": lambda: self._set_active_tool("fill"),
            "tool_gradient": lambda: self._set_active_tool("gradient"),
            "tool_smudge": lambda: self._set_active_tool("smudge"),
            "tool_dodge_burn": lambda: self._set_active_tool("dodge_burn"),
            "tool_move": lambda: self._set_active_tool("move"),
            "tool_rect": lambda: self._set_active_tool("select_rect"),
            "tool_lasso": lambda: self._set_active_tool("lasso"),
            "tool_clone": lambda: self._set_active_tool("clone"),
            "tool_heal": lambda: self._set_active_tool("heal"),
            "tool_patch": lambda: self._set_active_tool("patch"),
            "brush_smaller": lambda: self._nudge_brush_size(-1),
            "brush_larger": lambda: self._nudge_brush_size(1),
            "hardness_softer": lambda: self._nudge_brush_hardness(-1),
            "hardness_harder": lambda: self._nudge_brush_hardness(1),
            "toggle_quick_mask": self.toggle_quick_mask_shortcut,
        }
        for key, callback in bindings.items():
            self._register_shortcut(shortcut_map.get(key, ""), callback)

    def open_shortcuts_dialog(self) -> None:
        dialog = ShortcutEditorDialog(
            shortcuts=load_texture_editor_shortcuts(self.settings.value),
            labels=texture_editor_shortcut_labels(),
            defaults=default_texture_editor_shortcuts(),
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        for key, sequence_text in dialog.shortcut_map().items():
            self.settings.setValue(f"texture_editor/shortcuts/{key}", sequence_text)
        self._rebuild_shortcuts()
        self._set_status(texture_editor_shortcuts_updated_status_text(), False)


__all__ = ["TextureEditorShortcutsUiMixin"]
