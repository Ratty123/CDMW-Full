from __future__ import annotations

"""Shortcut mapping helpers for the standalone Texture Editor UI."""

from typing import Callable, Dict


def default_texture_editor_shortcuts() -> Dict[str, str]:
    return {
        "open_file": "Ctrl+O",
        "open_archive": "Ctrl+Shift+O",
        "open_compare": "Ctrl+Shift+C",
        "open_project": "Ctrl+Alt+O",
        "save_project": "Ctrl+S",
        "save_png": "Ctrl+Shift+S",
        "send_replace": "Ctrl+Alt+R",
        "send_workflow": "Ctrl+Alt+W",
        "send_item_icons": "Ctrl+Alt+I",
        "undo": "Ctrl+Z",
        "redo": "Ctrl+Y",
        "clear_selection": "Ctrl+D",
        "clear_selection_alt": "Escape",
        "copy_selection_layer": "Ctrl+J",
        "new_layer": "Ctrl+Shift+N",
        "copy_layer": "Ctrl+C",
        "cut_selection": "Ctrl+X",
        "paste_layer": "Ctrl+V",
        "paste_centered": "Ctrl+Shift+V",
        "transform_float_layer": "Ctrl+T",
        "fit_view": "F",
        "actual_size": "1",
        "tool_paint": "B",
        "tool_erase": "E",
        "tool_fill": "G",
        "tool_gradient": "Shift+G",
        "tool_smudge": "S",
        "tool_dodge_burn": "O",
        "tool_move": "M",
        "tool_rect": "R",
        "tool_lasso": "L",
        "tool_clone": "C",
        "tool_heal": "H",
        "tool_patch": "P",
        "brush_smaller": "[",
        "brush_larger": "]",
        "hardness_softer": "Shift+[",
        "hardness_harder": "Shift+]",
        "toggle_quick_mask": "Q",
    }


def texture_editor_shortcut_labels() -> Dict[str, str]:
    return {
        "open_file": "Open file",
        "open_archive": "Show in Archive Browser",
        "open_compare": "Open current source in Compare",
        "open_project": "Open project",
        "save_project": "Save project",
        "save_png": "Save flattened PNG",
        "send_replace": "Send to Texture Replacer",
        "send_workflow": "Send to Texture Workflow",
        "send_item_icons": "Send to Icon Creator",
        "undo": "Undo",
        "redo": "Redo",
        "clear_selection": "Clear selection",
        "clear_selection_alt": "Clear selection",
        "copy_selection_layer": "Copy selection to new layer",
        "new_layer": "New layer",
        "copy_layer": "Copy layer or selection",
        "cut_selection": "Cut selection",
        "paste_layer": "Paste layer or selection",
        "paste_centered": "Paste centered",
        "transform_float_layer": "Float active layer copy",
        "fit_view": "Fit view",
        "actual_size": "Actual size (100%)",
        "tool_paint": "Paint tool",
        "tool_erase": "Erase tool",
        "tool_fill": "Fill tool",
        "tool_gradient": "Gradient tool",
        "tool_smudge": "Smudge tool",
        "tool_dodge_burn": "Dodge/Burn tool",
        "tool_move": "Move tool",
        "tool_rect": "Rect select tool",
        "tool_lasso": "Lasso tool",
        "tool_clone": "Clone tool",
        "tool_heal": "Heal tool",
        "tool_patch": "Patch tool",
        "brush_smaller": "Brush smaller",
        "brush_larger": "Brush larger",
        "hardness_softer": "Hardness softer",
        "hardness_harder": "Hardness harder",
        "toggle_quick_mask": "Toggle quick mask overlay",
    }


def load_texture_editor_shortcuts(
    value_for_key: Callable[[str, str], object],
) -> Dict[str, str]:
    shortcuts = default_texture_editor_shortcuts()
    for key, default in shortcuts.items():
        shortcuts[key] = str(value_for_key(f"texture_editor/shortcuts/{key}", default))
    return shortcuts


def texture_editor_shortcuts_updated_status_text() -> str:
    return "Texture Editor shortcuts updated."


__all__ = [
    "default_texture_editor_shortcuts",
    "load_texture_editor_shortcuts",
    "texture_editor_shortcut_labels",
    "texture_editor_shortcuts_updated_status_text",
]
