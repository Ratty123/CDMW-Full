"""Bounded Rust Mesh Editor keyboard shortcut overrides stored in the app cfg.

The Rust editor owns the defaults and what each binding means. The host keeps
only the overrides between sessions: a missing ID keeps its default and an empty
list unbinds it. Unknown IDs are kept so an older helper never erases them.
"""

from __future__ import annotations

import json
import re

MESH_SHORTCUTS_KEY = "mesh_editor/shortcuts/v1"
MAX_SHORTCUT_OVERRIDES = 256
MAX_SHORTCUT_BINDINGS = 2
MAX_SHORTCUT_BINDING_LENGTH = 32
_SHORTCUT_ID = re.compile(r"[a-z0-9_.+-]{1,64}")


def _valid_binding(value: object) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= MAX_SHORTCUT_BINDING_LENGTH
        and value.isascii()
        and value.isprintable()
    )


def validated_mesh_shortcuts(value: object) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, list[str]] = {}
    for key, bindings in value.items():
        if len(result) >= MAX_SHORTCUT_OVERRIDES:
            break
        if not isinstance(key, str) or not _SHORTCUT_ID.fullmatch(key):
            continue
        if not isinstance(bindings, list) or len(bindings) > MAX_SHORTCUT_BINDINGS:
            continue
        if all(_valid_binding(binding) for binding in bindings):
            result[key] = list(bindings)
    return result


def load_mesh_shortcuts(settings) -> dict[str, list[str]]:
    try:
        value = json.loads(str(settings.value(MESH_SHORTCUTS_KEY, "{}")))
    except (TypeError, ValueError):
        return {}
    return validated_mesh_shortcuts(value)


def save_mesh_shortcuts(settings, value: object) -> bool:
    # Unlike the panel layout, shortcuts are kept regardless of the layout memory option.
    if not isinstance(value, dict):
        return False
    shortcuts = validated_mesh_shortcuts(value)
    settings.setValue(MESH_SHORTCUTS_KEY, json.dumps(shortcuts, separators=(",", ":"), sort_keys=True))
    return True
