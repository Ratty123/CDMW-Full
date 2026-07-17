"""Authoritative resident .NET/Vortice preview view modes."""

from __future__ import annotations


DOTNET_PREVIEW_VIEW_MODE_SPECS: tuple[tuple[str, str, int], ...] = (
    ("lit", "Lit", 0),
    ("game_outdoor", "Game Outdoor Approx", 0),
    ("base_direct", "Base Texture", 1),
    ("normal", "Normals", 2),
    ("uv_checker", "UV Checker", 8),
    ("base_alpha", "Alpha", 9),
    ("part_id", "Part ID", 10),
    ("material_response", "Material Response", 11),
    ("layer_mask", "Layer Mask", 12),
)

DOTNET_PREVIEW_VIEW_MODE_OPTIONS: tuple[tuple[str, str], ...] = tuple(
    (label, key) for key, label, _debug_mode in DOTNET_PREVIEW_VIEW_MODE_SPECS
)
DOTNET_PREVIEW_VIEW_MODES: tuple[str, ...] = tuple(
    key for key, _label, _debug_mode in DOTNET_PREVIEW_VIEW_MODE_SPECS
)
DOTNET_PREVIEW_VIEW_MODE_DEBUG_MODES: dict[str, int] = {
    key: debug_mode for key, _label, debug_mode in DOTNET_PREVIEW_VIEW_MODE_SPECS
}


def normalize_dotnet_preview_view_mode(value: object) -> str:
    """Return a renderer-backed mode, falling back to the stable lit view."""
    normalized = str(value or "").strip().lower()
    return normalized if normalized in DOTNET_PREVIEW_VIEW_MODE_DEBUG_MODES else "lit"


def dotnet_preview_material_debug_mode(value: object) -> int:
    """Resolve the Vortice shader branch for one supported view mode."""
    return DOTNET_PREVIEW_VIEW_MODE_DEBUG_MODES[normalize_dotnet_preview_view_mode(value)]


__all__ = [
    "DOTNET_PREVIEW_VIEW_MODE_DEBUG_MODES",
    "DOTNET_PREVIEW_VIEW_MODE_OPTIONS",
    "DOTNET_PREVIEW_VIEW_MODE_SPECS",
    "DOTNET_PREVIEW_VIEW_MODES",
    "dotnet_preview_material_debug_mode",
    "normalize_dotnet_preview_view_mode",
]
