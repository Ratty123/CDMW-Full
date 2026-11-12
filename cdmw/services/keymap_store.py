"""One keymap for every command, Qt's and the Mesh Editor helper's (P12 step 4).

The keymap holds overrides only, by registry command id
(``mesh_editor.tool.move``, ``texture_editor.open_file``, ``shell.settings``): a
missing id keeps its default and an empty list unbinds it. Unknown ids are kept,
so an older or newer build never erases them.

Two older stores are read until this one has been written once:
``mesh_editor/shortcuts/v1`` (the helper's overrides as JSON by its own ids) and
``texture_editor/shortcuts/<id>`` (one string per Texture Editor shortcut). The
Mesh Editor helper still receives its overrides by its own ids, and the Texture
Editor still asks for its keys by its own ids; both are read from here.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping

KEYMAP_KEY = "commands/keymap/v1"
LEGACY_MESH_KEY = "mesh_editor/shortcuts/v1"
LEGACY_TEXTURE_PREFIX = "texture_editor/shortcuts/"
MESH_PREFIX = "mesh_editor."
TEXTURE_PREFIX = "texture_editor."
MAX_OVERRIDES = 1024
MAX_BINDINGS = 2
MAX_BINDING_LENGTH = 32
_COMMAND_ID = re.compile(r"[a-z0-9_]{1,32}\.[a-z0-9_.+-]{1,64}")


def _valid_binding(value: object) -> bool:
    return (isinstance(value, str) and 0 < len(value) <= MAX_BINDING_LENGTH
            and value.isascii() and value.isprintable())


def validated_keymap(value: object) -> dict[str, list[str]]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, list[str]] = {}
    for key, bindings in value.items():
        if len(result) >= MAX_OVERRIDES:
            break
        if not isinstance(key, str) or not _COMMAND_ID.fullmatch(key):
            continue
        if not isinstance(bindings, list) or len(bindings) > MAX_BINDINGS:
            continue
        if all(_valid_binding(binding) for binding in bindings):
            result[key] = list(bindings)
    return result


def _legacy_overrides(settings) -> dict[str, list[str]]:
    """The two older stores, as keymap overrides."""

    from cdmw.services.mesh_editor_shortcuts import validated_mesh_shortcuts
    from cdmw.domain.texture_editor_shortcuts import default_texture_editor_shortcuts

    result: dict[str, list[str]] = {}
    try:
        mesh = json.loads(str(settings.value(LEGACY_MESH_KEY, "{}")))
    except (TypeError, ValueError):
        mesh = {}
    for helper_id, bindings in validated_mesh_shortcuts(mesh).items():
        result[MESH_PREFIX + helper_id] = bindings
    for key, default in default_texture_editor_shortcuts().items():
        stored = settings.value(LEGACY_TEXTURE_PREFIX + key, None)
        if stored is None:
            continue
        text = str(stored).strip()
        if text != default:
            result[TEXTURE_PREFIX + key] = [text] if _valid_binding(text) else []
    return result


def keymap_written(settings) -> bool:
    return settings.value(KEYMAP_KEY, None) is not None


def load_keymap(settings) -> dict[str, list[str]]:
    """Every saved override; from the older stores until the keymap has been written."""

    if not keymap_written(settings):
        return _legacy_overrides(settings)
    try:
        return validated_keymap(json.loads(str(settings.value(KEYMAP_KEY, "{}"))))
    except (TypeError, ValueError):
        return {}


def save_keymap(settings, overrides: Mapping[str, object]) -> dict[str, list[str]]:
    keymap = validated_keymap(dict(overrides))
    settings.setValue(KEYMAP_KEY, json.dumps(keymap, separators=(",", ":"), sort_keys=True))
    return keymap


def set_override(settings, command_id: str, keys: list[str] | None) -> dict[str, list[str]]:
    """Rebind (a list, empty to unbind) or reset (None) one command."""

    keymap = load_keymap(settings)
    if keys is None:
        keymap.pop(command_id, None)
    else:
        keymap[command_id] = list(keys)
    return save_keymap(settings, keymap)


def reset_keymap(settings, prefix: str = "") -> dict[str, list[str]]:
    """Reset every command, or every command whose id starts with ``prefix``."""

    keymap = {key: value for key, value in load_keymap(settings).items() if prefix and not key.startswith(prefix)}
    return save_keymap(settings, keymap)


# ----- the two views the older consumers keep -----------------------------
def mesh_editor_overrides(settings) -> dict[str, list[str]]:
    """The helper's overrides by its own ids, as its theme payload carries them."""

    return {key[len(MESH_PREFIX):]: value for key, value in load_keymap(settings).items()
            if key.startswith(MESH_PREFIX)}


def save_mesh_editor_overrides(settings, overrides: Mapping[str, list[str]]) -> None:
    """The helper's own shortcut editor changed its keys: they replace its part of the keymap."""

    keymap = {key: value for key, value in load_keymap(settings).items() if not key.startswith(MESH_PREFIX)}
    keymap.update({MESH_PREFIX + key: list(value) for key, value in overrides.items()})
    save_keymap(settings, keymap)


def texture_editor_keys(settings) -> dict[str, str]:
    """The Texture Editor's key for each of its shortcut ids (default, or override)."""

    from cdmw.domain.texture_editor_shortcuts import default_texture_editor_shortcuts

    keys = default_texture_editor_shortcuts()
    for command_id, bindings in load_keymap(settings).items():
        if command_id.startswith(TEXTURE_PREFIX) and command_id[len(TEXTURE_PREFIX):] in keys:
            keys[command_id[len(TEXTURE_PREFIX):]] = bindings[0] if bindings else ""
    return keys


def save_texture_editor_keys(settings, keys: Mapping[str, str]) -> None:
    """The Texture Editor's own shortcut dialog saved: keep only what differs from the defaults."""

    from cdmw.domain.texture_editor_shortcuts import default_texture_editor_shortcuts

    defaults = default_texture_editor_shortcuts()
    keymap = {key: value for key, value in load_keymap(settings).items() if not key.startswith(TEXTURE_PREFIX)}
    for key, text in keys.items():
        text = str(text or "").strip()
        if key in defaults and text != defaults[key]:
            keymap[TEXTURE_PREFIX + key] = [text] if text else []
    save_keymap(settings, keymap)
