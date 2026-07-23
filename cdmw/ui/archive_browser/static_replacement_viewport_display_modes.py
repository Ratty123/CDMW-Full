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

MESH_PREVIEW_DISPLAY_MODES = tuple(
    mode for _label, mode in MESH_PREVIEW_DISPLAY_MODE_OPTIONS
)


def normalize_mesh_preview_display_mode(value: object) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in MESH_PREVIEW_DISPLAY_MODES:
        return normalized
    return MESH_PREVIEW_DEFAULT_DISPLAY_MODE


__all__ = [
    "MESH_PREVIEW_DEFAULT_DISPLAY_MODE",
    "MESH_PREVIEW_DISPLAY_MODE_OPTIONS",
    "MESH_PREVIEW_DISPLAY_MODES",
    "normalize_mesh_preview_display_mode",
]
