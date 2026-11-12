"""One list of view modes for every 3D viewport (P4 V3).

Browse Archives' preview and the Mesh Editor used to offer different lists:
Browse had material diagnostics (Game Outdoor, Normals, UV Checker, ...), the
editor had geometry modes (Faces, Wire, Vertices, X-Ray, ...). Both draw with
the same renderer, so every viewport now offers the union, and one stored key,
``preview/view_mode``, holds the choice for all of them.

The ids are stable: the settings file, the shared Preview settings and the
helper's protocol use them. Values from the old ``preview/d3d11_view_mode`` key
are migrated by ``shared_view_mode``. Icon captures never use the chosen mode;
they always draw textured.
"""

from __future__ import annotations

#: (id, label), in menu order.
SHARED_VIEW_MODES: tuple[tuple[str, str], ...] = (
    ("textured", "Solid (Textured)"),
    ("game_outdoor", "Game Outdoor Approx"),
    ("base_color", "Base Color"),
    ("normal_map", "Normals"),
    ("uv_checker", "UV Checker"),
    ("base_alpha", "Alpha"),
    ("part_colors", "Part colors"),
    ("island_colors", "Island colors"),
    ("material_response", "Material Response"),
    ("layer_mask", "Layer Mask"),
    ("faces", "Faces (No Textures)"),
    ("faces_wire", "Faces + Wire"),
    ("wire", "Wire"),
    ("vertices", "Vertices"),
    ("wire_vertices", "Wire + Vertices"),
    ("xray", "X-Ray"),
)
SHARED_VIEW_MODE_IDS: tuple[str, ...] = tuple(mode for mode, _label in SHARED_VIEW_MODES)
SHARED_VIEW_MODE_LABELS: dict[str, str] = dict(SHARED_VIEW_MODES)
DEFAULT_VIEW_MODE = "textured"

#: Values the old ``preview/d3d11_view_mode`` key held that were renamed.
LEGACY_VIEW_MODES: dict[str, str] = {
    "lit": "textured",
    "base_direct": "base_color",
    "part_id": "part_colors",
    "normal": "normal_map",
}

#: The shared key, and the key it replaces.
VIEW_MODE_KEY = "preview/view_mode"
LEGACY_VIEW_MODE_KEY = "preview/d3d11_view_mode"


def shared_view_mode(value: object) -> str:
    """A valid shared id for ``value``; old ids are migrated, unknown ones give the default."""

    text = str(value or "").strip().lower().replace("-", "_")
    text = LEGACY_VIEW_MODES.get(text, text)
    return text if text in SHARED_VIEW_MODE_IDS else DEFAULT_VIEW_MODE


def read_view_mode(settings: object) -> str:
    """The stored view mode: the shared key, else the old key's value migrated."""

    value = settings.value(VIEW_MODE_KEY, None)  # type: ignore[attr-defined]
    if value in (None, ""):
        value = settings.value(LEGACY_VIEW_MODE_KEY, DEFAULT_VIEW_MODE)  # type: ignore[attr-defined]
    return shared_view_mode(value)


def write_view_mode(settings: object, value: object) -> str:
    """Store the shared view mode and drop the key it replaces."""

    mode = shared_view_mode(value)
    settings.setValue(VIEW_MODE_KEY, mode)  # type: ignore[attr-defined]
    settings.remove(LEGACY_VIEW_MODE_KEY)  # type: ignore[attr-defined]
    return mode


__all__ = [
    "DEFAULT_VIEW_MODE", "LEGACY_VIEW_MODES", "LEGACY_VIEW_MODE_KEY", "SHARED_VIEW_MODES",
    "SHARED_VIEW_MODE_IDS", "SHARED_VIEW_MODE_LABELS", "VIEW_MODE_KEY", "read_view_mode",
    "shared_view_mode", "write_view_mode",
]
