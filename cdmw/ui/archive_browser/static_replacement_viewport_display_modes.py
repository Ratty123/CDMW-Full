"""Resident viewport display modes shared by Mesh Editor preview controls."""

from __future__ import annotations


MESH_PREVIEW_DEFAULT_DISPLAY_MODE = "untextured_wire"

MESH_PREVIEW_DISPLAY_MODE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Solid (Textured)", "textured"),
    ("Faces (No Textures)", "untextured_faces"),
    ("Faces + Wire", "untextured_wire"),
    ("Solid + Wire", "textured_wire"),
    ("Wire", "wire"),
    ("Vertices", "vertices"),
    ("Wire + Vertices", "wire_vertices"),
    ("X-Ray", "xray"),
)

# The Mesh Editor tool rail caps this control near 118px, where the full labels
# elide to nothing readable. Same modes in the same order, shorter text; the
# popup and the item tooltips still carry the full label.
MESH_PREVIEW_COMPACT_DISPLAY_MODE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Solid", "textured"),
    ("Faces", "untextured_faces"),
    ("Faces+W", "untextured_wire"),
    ("Solid+W", "textured_wire"),
    ("Wire", "wire"),
    ("Verts", "vertices"),
    ("Wire+V", "wire_vertices"),
    ("X-Ray", "xray"),
)

MESH_PREVIEW_DISPLAY_MODES = tuple(
    mode for _label, mode in MESH_PREVIEW_DISPLAY_MODE_OPTIONS
)

if MESH_PREVIEW_DISPLAY_MODES != tuple(
    mode for _label, mode in MESH_PREVIEW_COMPACT_DISPLAY_MODE_OPTIONS
):
    raise RuntimeError(
        "Mesh preview display-mode tables must offer the same modes in the same order."
    )

# Modes that sample the material, so the resident viewport needs resolved
# textures before the mode can be honoured.
MESH_PREVIEW_TEXTURED_DISPLAY_MODES = frozenset({"textured", "textured_wire"})

# What to show while a textured mode waits for its textures. The .NET viewport
# applies the same rule in ExperimentForm.ConfigurePreviewModeCombo, so keeping
# them equal stops the wire overlay from disappearing only when the mode is
# chosen from the Qt control.
_UNTEXTURED_FALLBACK_DISPLAY_MODES = {
    "textured": "untextured_faces",
    "textured_wire": "untextured_wire",
}


def untextured_fallback_display_mode(value: object) -> str:
    """Return the mode to show while `value`'s textures are still loading."""
    normalized = normalize_mesh_preview_display_mode(value)
    return _UNTEXTURED_FALLBACK_DISPLAY_MODES.get(normalized, normalized)


def normalize_mesh_preview_display_mode(value: object) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in MESH_PREVIEW_DISPLAY_MODES:
        return normalized
    return MESH_PREVIEW_DEFAULT_DISPLAY_MODE


__all__ = [
    "MESH_PREVIEW_COMPACT_DISPLAY_MODE_OPTIONS",
    "MESH_PREVIEW_DEFAULT_DISPLAY_MODE",
    "MESH_PREVIEW_DISPLAY_MODE_OPTIONS",
    "MESH_PREVIEW_DISPLAY_MODES",
    "MESH_PREVIEW_TEXTURED_DISPLAY_MODES",
    "normalize_mesh_preview_display_mode",
    "untextured_fallback_display_mode",
]
