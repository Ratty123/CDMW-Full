"""Combo-box option specs for the static replacement dialog."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TypeAlias

from PySide6.QtWidgets import QComboBox

from cdmw.ui.archive_browser.static_replacement_viewport_display_modes import (
    MESH_PREVIEW_DEFAULT_DISPLAY_MODE,
    MESH_PREVIEW_DISPLAY_MODE_OPTIONS,
    MESH_PREVIEW_DISPLAY_MODES,
    normalize_mesh_preview_display_mode,
)

ComboOption: TypeAlias = tuple[str, object]
ToolButtonOption: TypeAlias = tuple[str, str, str]

PREVIEW_RENDERER_OPTIONS: tuple[ComboOption, ...] = (
    (".NET/Vortice Preview", "d3d11"),
)

PREVIEW_MODE_OPTIONS: tuple[ComboOption, ...] = (
    ("Side by side", "side_by_side"),
    ("Overlay", "overlay"),
    ("Replacement only", "replacement_only"),
    ("Original only", "original_only"),
)

TEXTURE_UV_ROTATION_OPTIONS: tuple[ComboOption, ...] = (
    ("0 deg", 0),
    ("90 deg", 90),
    ("180 deg", 180),
    ("270 deg", 270),
)

DONOR_MODE_OPTIONS: tuple[ComboOption, ...] = (
    ("Authoritative donor recipe", "authoritative_recipe"),
    ("Donor material behavior", "material_behavior"),
    ("Donor material profile", "material_profile"),
    ("Donor textures", "donor_textures"),
)

ALIGNMENT_MODE_OPTIONS: tuple[ComboOption, ...] = (
    ("Auto: Force grid flat", "grid_flat"),
    ("Manual only", "manual"),
)

EDGE_RELIEF_SOURCE_OPTIONS: tuple[ComboOption, ...] = (
    ("Hybrid", "hybrid"),
    ("Preserve target support", "preserve_target"),
    ("Generate from source", "generate_source"),
)

TEXTURE_OUTPUT_SIZE_OPTIONS: tuple[ComboOption, ...] = (
    ("Source image size", "source"),
    ("Original DDS size", "original"),
)

PARTS_OUTLINER_ROLE_OPTIONS: tuple[ComboOption, ...] = (
    ("auto", ""),
    ("blade", "blade"),
    ("handle", "handle"),
    ("guard", "guard"),
    ("accessory/detail", "accessory/detail"),
    ("glow/emissive", "glow"),
    ("cloth", "cloth"),
    ("unknown", "unknown"),
)

SOURCE_ROLE_OPTIONS: tuple[ComboOption, ...] = (
    ("Auto / inferred", ""),
    ("Head / face", "head/face"),
    ("Hair", "hair"),
    ("Body / nude", "body"),
    ("Hand / arm", "hand/arm"),
    ("Foot / leg", "foot/leg"),
    ("Helmet / mask", "helmet"),
    ("Blade", "blade"),
    ("Handle / grip", "handle"),
    ("Guard / crossguard", "guard"),
    ("Accessory / detail", "accessory/detail"),
    ("Glow / emissive", "glow"),
    ("Cloth / fabric", "cloth"),
    ("Armor / body", "armor/body"),
    ("Unknown", "unknown"),
)

SOURCE_TREE_ROLE_OPTIONS: tuple[ComboOption, ...] = (
    ("Auto / inferred", ""),
    ("Blade", "blade"),
    ("Handle / grip", "handle"),
    ("Guard / crossguard", "guard"),
    ("Accessory / detail", "accessory/detail"),
    ("Glow / emissive", "glow"),
    ("Cloth / fabric", "cloth"),
    ("Unknown", "unknown"),
)

MESH_EDIT_SCOPE_OPTIONS: tuple[ComboOption, ...] = (
    ("All editable parts", "all"),
    ("Selected part only", "selected"),
)

MESH_EDIT_TOOL_OPTIONS: tuple[ComboOption, ...] = (
    ("Move", "grab"),
    ("Smooth", "smooth"),
    ("Push/Pull", "inflate"),
    ("Pinch/Relax", "pinch"),
    ("Remove Faces", "remove"),
    ("Select Vertices", "vertex"),
)

MESH_EDIT_TOOL_BUTTON_OPTIONS: tuple[ToolButtonOption, ...] = (
    ("Move", "grab", "Move vertices inside the brush radius."),
    ("Smooth", "smooth", "Smooth vertices inside the brush radius."),
    ("Push/Pull", "inflate", "Push or pull vertices along their normals."),
    ("Pinch/Relax", "pinch", "Pinch vertices toward the brush center, or relax with inverted strokes."),
    ("Remove Faces", "remove", "Cut away faces touched by the brush. Boundaries stay open."),
    ("Select Vertices", "vertex", "Paint vertex selection for Delete Selected Faces."),
)

MESH_EDIT_DELETE_MODE_OPTIONS: tuple[ComboOption, ...] = (
    ("On release", "release"),
    ("During drag", "live"),
)

MESH_EDIT_FALLOFF_OPTIONS: tuple[ComboOption, ...] = (
    ("Smooth", "smooth"),
    ("Linear", "linear"),
    ("Sharp", "sharp"),
    ("Constant", "constant"),
)

MESH_EDIT_SELECTION_MODE_OPTIONS: tuple[ComboOption, ...] = (
    ("Brush Select", "brush"),
    ("Lasso Select", "lasso"),
    ("Rectangle Select", "rectangle"),
)

MESH_EDIT_SELECTION_DEPTH_OPTIONS: tuple[ComboOption, ...] = (
    ("Visible Only", "visible"),
    ("X-Ray", "xray"),
)


def d3d11_view_mode_options(
    modes: Sequence[str],
    labels: Mapping[str, str],
) -> tuple[ComboOption, ...]:
    return tuple((labels.get(mode, mode), mode) for mode in modes)


def populate_combo_options(combo: QComboBox, options: Sequence[ComboOption]) -> None:
    for label, value in options:
        combo.addItem(str(label), value)


__all__ = [
    "ALIGNMENT_MODE_OPTIONS",
    "DONOR_MODE_OPTIONS",
    "EDGE_RELIEF_SOURCE_OPTIONS",
    "MESH_EDIT_DELETE_MODE_OPTIONS",
    "MESH_EDIT_FALLOFF_OPTIONS",
    "MESH_EDIT_SCOPE_OPTIONS",
    "MESH_EDIT_SELECTION_DEPTH_OPTIONS",
    "MESH_EDIT_SELECTION_MODE_OPTIONS",
    "MESH_EDIT_TOOL_BUTTON_OPTIONS",
    "MESH_EDIT_TOOL_OPTIONS",
    "MESH_PREVIEW_DEFAULT_DISPLAY_MODE",
    "MESH_PREVIEW_DISPLAY_MODE_OPTIONS",
    "MESH_PREVIEW_DISPLAY_MODES",
    "PARTS_OUTLINER_ROLE_OPTIONS",
    "PREVIEW_MODE_OPTIONS",
    "PREVIEW_RENDERER_OPTIONS",
    "SOURCE_ROLE_OPTIONS",
    "SOURCE_TREE_ROLE_OPTIONS",
    "TEXTURE_OUTPUT_SIZE_OPTIONS",
    "TEXTURE_UV_ROTATION_OPTIONS",
    "d3d11_view_mode_options",
    "normalize_mesh_preview_display_mode",
    "populate_combo_options",
]
