from __future__ import annotations

"""Shortcut mapping helpers for the standalone Texture Editor UI."""

from typing import Callable, Dict

from cdmw.domain.texture_editor_shortcuts import (  # noqa: F401 - re-exported
    default_texture_editor_shortcuts,
    texture_editor_shortcut_labels,
)


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
