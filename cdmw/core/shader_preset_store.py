"""The user's own shader presets, kept on this computer.

A preset is a name and the numbers of one shader family's fields. They are
a convenience for the Shader experiments panel: nothing in a draft or a mod
refers to them, so the file can be deleted without breaking saved work.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from cdmw.core.shader_texture_store import store_root as _texture_store_root
from cdmw.domain.mesh.shader_controls import MESH_FAMILIES, ShaderControls
from cdmw.services.atomic_file_service import atomic_write_text

MAX_PRESETS_PER_SHADER = 48
MAX_PRESET_NAME = 48
_ENVIRONMENT_FILE = "CDMW_SHADER_PRESET_FILE"


def store_file() -> Path:
    override = os.environ.get(_ENVIRONMENT_FILE, "").strip()
    return Path(override) if override else _texture_store_root().parent / "shader_presets.json"


def _clean(shader: object, name: object) -> tuple[str, str]:
    if not isinstance(shader, str) or shader not in {family.shader for family in MESH_FAMILIES}:
        raise ValueError("Presets can be saved only for a shader this panel edits.")
    text = " ".join(str(name or "").split()) if isinstance(name, str) else ""
    if not text or len(text) > MAX_PRESET_NAME:
        raise ValueError("Give the preset a name of up to 48 characters.")
    return shader, text


def user_presets() -> dict[str, list[dict[str, object]]]:
    """Saved presets by shader, in the order saved. A missing or damaged file is no presets."""

    try:
        stored = json.loads(store_file().read_text(encoding="utf-8"))["presets"]
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    presets: dict[str, list[dict[str, object]]] = {}
    for shader, rows in stored.items() if isinstance(stored, dict) else ():
        for row in rows if isinstance(rows, list) else ():
            try:
                shader, name = _clean(shader, row["name"])
                values = ShaderControls.from_dict({"shader": shader, "values": row["values"]}).to_dict()["values"]
            except (ValueError, KeyError, TypeError):
                continue  # One hand-edited row does not take the others with it.
            presets.setdefault(shader, []).append({"name": name, "values": values})
    return presets


def _write(presets: dict[str, list[dict[str, object]]]) -> None:
    path = store_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps({"version": 1, "presets": presets}, ensure_ascii=False, indent=2) + "\n")


def save_user_preset(shader: object, name: object, values: object) -> None:
    """Add a preset, or replace the one of the same name (compared without case)."""

    shader, name = _clean(shader, name)
    if not isinstance(values, dict) or not values:
        raise ValueError("There are no values to save as a preset.")
    values = ShaderControls.from_dict({"shader": shader, "values": values}).to_dict()["values"]
    presets = user_presets()
    rows = [row for row in presets.get(shader, []) if str(row["name"]).casefold() != name.casefold()]
    if len(rows) >= MAX_PRESETS_PER_SHADER:
        raise ValueError("This shader already has 48 saved presets. Delete one first.")
    presets[shader] = [*rows, {"name": name, "values": values}]
    _write(presets)


def delete_user_preset(shader: object, name: object) -> None:
    shader, name = _clean(shader, name)
    presets = user_presets()
    rows = [row for row in presets.get(shader, []) if str(row["name"]).casefold() != name.casefold()]
    if len(rows) == len(presets.get(shader, [])):
        raise ValueError("That preset is no longer saved.")
    presets[shader] = rows
    _write({key: value for key, value in presets.items() if value})


__all__ = ["delete_user_preset", "save_user_preset", "store_file", "user_presets"]
