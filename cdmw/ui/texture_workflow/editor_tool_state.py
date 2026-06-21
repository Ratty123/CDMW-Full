from __future__ import annotations

"""Tool visibility state rules for the standalone Texture Editor UI."""

import dataclasses
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import numpy as np

from cdmw.core.texture_editor import (
    apply_texture_editor_fill,
    apply_texture_editor_gradient,
    apply_texture_editor_patch,
    apply_texture_editor_recolor,
    apply_texture_editor_selection_fill,
    apply_texture_editor_selection_stroke,
    apply_texture_editor_stroke,
    build_texture_editor_selection_mask,
    bump_texture_editor_layer_revision,
    flatten_texture_editor_layers,
)
from cdmw.models import TextureEditorDocument, TextureEditorToolSettings


@dataclass(frozen=True, slots=True)
class TextureEditorToolVisibility:
    rows: Dict[str, bool]
    selection_section_visible: bool


@dataclass(frozen=True, slots=True)
class TextureEditorActiveToolState:
    settings: TextureEditorToolSettings
    clone_source_point: Optional[tuple[int, int]]


@dataclass(frozen=True, slots=True)
class TextureEditorRecolorControlState:
    mode: str
    source_color: str
    target_color: str
    tolerance: int
    strength: int
    preserve_luminance: bool


@dataclass(frozen=True, slots=True)
class TextureEditorRecolorLayerState:
    document: TextureEditorDocument
    layer_pixels: Dict[str, np.ndarray]
    before_layer_pixels: Dict[str, np.ndarray]
    layer_id: str
    dirty_bounds: Optional[Tuple[int, int, int, int]]
    history_label: str
    kind: str
    tracked_layer_ids: Tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TextureEditorQuickMaskStrokeState:
    document: TextureEditorDocument
    history_label: str
    kind: str
    tracked_layer_ids: Tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TextureEditorLayerStrokeState:
    document: TextureEditorDocument
    layer_pixels: Dict[str, np.ndarray]
    before_layer_pixels: Dict[str, np.ndarray]
    layer_id: str
    thumbnail_layer_id: Optional[str]
    dirty_bounds: Optional[Tuple[int, int, int, int]]
    history_label: str
    kind: str
    tracked_layer_ids: Tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TextureEditorCloneSourceState:
    settings: TextureEditorToolSettings
    clone_source_point: Optional[tuple[int, int]]


@dataclass(frozen=True, slots=True)
class TextureEditorToolControlSnapshot:
    color_hex: object = "#C85A30"
    secondary_color_hex: object = "#FFFFFF"
    brush_preset: object = "custom"
    brush_tip: object = "round"
    brush_pattern: object = "solid"
    custom_brush_tip_path: object = ""
    symmetry_mode: object = "off"
    size: object = 32.0
    size_step_mode: object = "normal"
    hardness: object = 80
    roundness: object = 100
    angle_degrees: object = 0
    smoothing: object = 0
    opacity: object = 100
    flow: object = 100
    spacing: object = 20
    strength: object = 50
    smudge_strength: object = 45
    dodge_burn_mode: object = "dodge_midtones"
    dodge_burn_exposure: object = 20
    patch_blend: object = 70
    gradient_type: object = "linear"
    paint_blend_mode: object = "normal"
    fill_tolerance: object = 24
    fill_contiguous: object = True
    sharpen_mode: object = "unsharp_mask"
    soften_mode: object = "gaussian"
    sample_visible_layers: object = True
    clone_aligned: object = True
    selection_combine_mode: object = "replace"
    lasso_snap_to_edges: object = False
    lasso_snap_radius: object = 10
    lasso_edge_sensitivity: object = 55
    recolor_mode: object = "tint"
    recolor_source_hex: object = "#808080"
    recolor_target_hex: object = "#C85A30"
    recolor_tolerance: object = 48
    recolor_strength: object = 100
    recolor_preserve_luminance: object = True


@dataclass(frozen=True, slots=True)
class TextureEditorBrushVisualState:
    size: float
    hardness: int
    tip: str
    roundness: int
    angle_degrees: int
    pattern: str
    symmetry_mode: str


@dataclass(frozen=True, slots=True)
class TextureEditorStrokePayloadState:
    tool: str
    points: list[object]


def texture_editor_active_tool_state(
    settings: TextureEditorToolSettings,
    tool_key: str,
) -> TextureEditorActiveToolState:
    previous_tool = settings.tool
    next_clone_source = settings.clone_source_point
    if previous_tool in {"clone", "heal"} and tool_key not in {"clone", "heal"}:
        next_clone_source = None
    updated = dataclasses.replace(settings, tool=str(tool_key), clone_source_point=next_clone_source)
    return TextureEditorActiveToolState(settings=updated, clone_source_point=next_clone_source)


def texture_editor_recolor_control_state(
    *,
    mode: str = "tint",
    source_color: str = "#808080",
    target_color: str = "#C85A30",
    tolerance: int = 48,
    strength: int = 100,
    preserve_luminance: bool = True,
) -> TextureEditorRecolorControlState:
    return TextureEditorRecolorControlState(
        mode=str(mode or "tint"),
        source_color=str(source_color or "#808080"),
        target_color=str(target_color or "#C85A30"),
        tolerance=max(0, min(255, int(tolerance))),
        strength=max(1, min(100, int(strength))),
        preserve_luminance=bool(preserve_luminance),
    )


def texture_editor_recolor_settings_loaded_status_text() -> str:
    return "Recolor settings loaded. Use Apply Recolor To Active Layer to commit."


def texture_editor_recolor_layer_history_label() -> str:
    return "Recolor Layer"


def texture_editor_recolor_layer_state(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    settings: TextureEditorToolSettings,
    *,
    layer_id: str,
    dirty_bounds: Optional[Tuple[int, int, int, int]],
) -> Optional[TextureEditorRecolorLayerState]:
    if not layer_id or layer_id not in layer_pixels:
        return None
    selection_mask = build_texture_editor_selection_mask(document.width, document.height, document.selection)
    before_pixels = layer_pixels[layer_id].copy()
    recolored = apply_texture_editor_recolor(
        layer_pixels[layer_id],
        settings,
        selection_mask=selection_mask,
    )
    active_layer = next((layer for layer in document.layers if layer.layer_id == layer_id), None)
    recolored = texture_editor_recolor_pixels_with_channel_locks(
        recolored,
        before_pixels,
        edit_red_channel=document.edit_red_channel,
        edit_green_channel=document.edit_green_channel,
        edit_blue_channel=document.edit_blue_channel,
        edit_alpha_channel=document.edit_alpha_channel,
        alpha_locked=bool(active_layer is not None and active_layer.alpha_locked),
    )
    updated_pixels = dict(layer_pixels)
    updated_pixels[layer_id] = recolored
    return TextureEditorRecolorLayerState(
        document=bump_texture_editor_layer_revision(document, layer_id),
        layer_pixels=updated_pixels,
        before_layer_pixels={layer_id: before_pixels},
        layer_id=layer_id,
        dirty_bounds=dirty_bounds,
        history_label=texture_editor_recolor_layer_history_label(),
        kind="recolor_stroke",
        tracked_layer_ids=(layer_id,),
    )


def normalized_texture_editor_clone_source_point(point: object) -> Optional[tuple[int, int]]:
    if not isinstance(point, tuple) or len(point) != 2:
        return None
    return (int(point[0]), int(point[1]))


def texture_editor_clone_source_picked_state(
    settings: TextureEditorToolSettings,
    point: object,
) -> Optional[TextureEditorCloneSourceState]:
    clone_source_point = normalized_texture_editor_clone_source_point(point)
    if clone_source_point is None:
        return None
    return TextureEditorCloneSourceState(
        settings=dataclasses.replace(settings, clone_source_point=clone_source_point),
        clone_source_point=clone_source_point,
    )


def texture_editor_clone_source_cleared_state(settings: TextureEditorToolSettings) -> TextureEditorCloneSourceState:
    return TextureEditorCloneSourceState(
        settings=dataclasses.replace(settings, clone_source_point=None),
        clone_source_point=None,
    )


def texture_editor_clone_source_picked_status_text(point: object) -> str:
    return f"Clone source set to {point}."


def texture_editor_clone_source_cleared_status_text() -> str:
    return "Clone/heal source cleared."


def texture_editor_tool_settings_from_controls(
    current: TextureEditorToolSettings,
    controls: TextureEditorToolControlSnapshot,
) -> TextureEditorToolSettings:
    return TextureEditorToolSettings(
        tool=current.tool,
        color_hex=str(controls.color_hex).strip() or "#C85A30",
        secondary_color_hex=str(controls.secondary_color_hex).strip() or "#FFFFFF",
        brush_preset=str(controls.brush_preset or "custom"),
        brush_tip=str(controls.brush_tip or "round"),
        brush_pattern=str(controls.brush_pattern or "solid"),
        custom_brush_tip_path=str(controls.custom_brush_tip_path).strip(),
        symmetry_mode=str(controls.symmetry_mode or "off"),
        size=float(controls.size),
        size_step_mode=str(controls.size_step_mode or "normal"),
        hardness=int(controls.hardness),
        roundness=int(controls.roundness),
        angle_degrees=int(controls.angle_degrees),
        smoothing=int(controls.smoothing),
        opacity=int(controls.opacity),
        flow=int(controls.flow),
        spacing=int(controls.spacing),
        strength=int(controls.strength),
        smudge_strength=int(controls.smudge_strength),
        dodge_burn_mode=str(controls.dodge_burn_mode or "dodge_midtones"),
        dodge_burn_exposure=int(controls.dodge_burn_exposure),
        patch_blend=int(controls.patch_blend),
        gradient_type=str(controls.gradient_type or "linear"),
        paint_blend_mode=str(controls.paint_blend_mode or "normal"),
        fill_tolerance=int(controls.fill_tolerance),
        fill_contiguous=bool(controls.fill_contiguous),
        sharpen_mode=str(controls.sharpen_mode or "unsharp_mask"),
        soften_mode=str(controls.soften_mode or "gaussian"),
        sample_visible_layers=bool(controls.sample_visible_layers),
        clone_aligned=bool(controls.clone_aligned),
        clone_source_point=current.clone_source_point,
        selection_combine_mode=str(controls.selection_combine_mode or "replace"),
        lasso_snap_to_edges=bool(controls.lasso_snap_to_edges),
        lasso_snap_radius=int(controls.lasso_snap_radius),
        lasso_edge_sensitivity=int(controls.lasso_edge_sensitivity),
        recolor_mode=str(controls.recolor_mode or "tint"),
        recolor_source_hex=str(controls.recolor_source_hex).strip() or "#808080",
        recolor_target_hex=str(controls.recolor_target_hex).strip() or "#C85A30",
        recolor_tolerance=int(controls.recolor_tolerance),
        recolor_strength=int(controls.recolor_strength),
        recolor_preserve_luminance=bool(controls.recolor_preserve_luminance),
    )


def texture_editor_brush_visual_state(settings: TextureEditorToolSettings) -> TextureEditorBrushVisualState:
    return TextureEditorBrushVisualState(
        size=float(settings.size),
        hardness=int(settings.hardness),
        tip=str(settings.brush_tip),
        roundness=int(settings.roundness),
        angle_degrees=int(settings.angle_degrees),
        pattern=str(settings.brush_pattern),
        symmetry_mode=str(settings.symmetry_mode),
    )


def texture_editor_stroke_payload_state(
    payload: object,
    fallback_tool: str,
) -> Optional[TextureEditorStrokePayloadState]:
    if not isinstance(payload, dict):
        return None
    points = payload.get("points")
    if not isinstance(points, list) or not points:
        return None
    tool = str(payload.get("tool", fallback_tool))
    if tool == "recolor":
        return None
    return TextureEditorStrokePayloadState(tool=tool, points=points)


def texture_editor_move_delta(points: list[object]) -> Optional[tuple[int, int]]:
    start_x, start_y = points[0]  # type: ignore[misc]
    end_x, end_y = points[-1]  # type: ignore[misc]
    dx = int(end_x - start_x)
    dy = int(end_y - start_y)
    if dx == 0 and dy == 0:
        return None
    return (dx, dy)


def texture_editor_tool_settings_for_stroke(
    settings: TextureEditorToolSettings,
    tool: str,
) -> TextureEditorToolSettings:
    return dataclasses.replace(settings, tool=str(tool))


def texture_editor_quick_mask_stroke_state(
    document: TextureEditorDocument,
    settings: TextureEditorToolSettings,
    points: list[object],
) -> Optional[TextureEditorQuickMaskStrokeState]:
    tool = str(settings.tool)
    if not texture_editor_quick_mask_tool_allowed(tool):
        return None
    if tool == "fill":
        updated_document = apply_texture_editor_selection_fill(
            document,
            settings,
            tuple(int(value) for value in points[-1]),  # type: ignore[union-attr]
        )
    else:
        updated_document = apply_texture_editor_selection_stroke(document, settings, points)
    return TextureEditorQuickMaskStrokeState(
        document=updated_document,
        history_label=f"Quick Mask {tool.title()}",
        kind="selection_update",
        tracked_layer_ids=(),
    )


def texture_editor_layer_stroke_state(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    settings: TextureEditorToolSettings,
    points: list[object],
    *,
    layer_id: str,
    editing_mask_target: bool,
    selection_bounds: Optional[Tuple[int, int, int, int]],
    layer_canvas_bounds: Optional[Tuple[int, int, int, int]],
    brush_dirty_bounds: Optional[Tuple[int, int, int, int]],
    source_snapshot: Optional[np.ndarray] = None,
) -> Optional[TextureEditorLayerStrokeState]:
    if not layer_id or layer_id not in layer_pixels:
        return None
    working_document = (
        document
        if layer_id == document.active_layer_id
        else dataclasses.replace(document, active_layer_id=layer_id)
    )
    before_layer_pixels = {layer_id: layer_pixels[layer_id].copy()}
    tool = str(settings.tool)
    dirty_bounds: Optional[Tuple[int, int, int, int]]
    if tool == "fill":
        updated_layer_pixels = apply_texture_editor_fill(
            working_document,
            layer_pixels,
            settings,
            tuple(int(value) for value in points[-1]),  # type: ignore[union-attr]
            source_snapshot=source_snapshot,
        )
        dirty_bounds = selection_bounds or layer_canvas_bounds
    elif tool == "gradient":
        updated_layer_pixels = apply_texture_editor_gradient(
            working_document,
            layer_pixels,
            settings,
            tuple(int(value) for value in points[0]),  # type: ignore[union-attr]
            tuple(int(value) for value in points[-1]),  # type: ignore[union-attr]
        )
        dirty_bounds = selection_bounds or layer_canvas_bounds
    elif tool == "patch":
        updated_layer_pixels = apply_texture_editor_patch(
            working_document,
            layer_pixels,
            settings,
            delta_x=int(points[-1][0] - points[0][0]),  # type: ignore[index]
            delta_y=int(points[-1][1] - points[0][1]),  # type: ignore[index]
            source_snapshot=source_snapshot,
        )
        dirty_bounds = selection_bounds or brush_dirty_bounds
    else:
        updated_layer_pixels = apply_texture_editor_stroke(
            working_document,
            layer_pixels,
            settings,
            points,
            source_snapshot=source_snapshot,
        )
        dirty_bounds = brush_dirty_bounds
    active_layer_id = document.active_layer_id
    bumped_layer_id = active_layer_id if editing_mask_target and active_layer_id else layer_id
    return TextureEditorLayerStrokeState(
        document=bump_texture_editor_layer_revision(document, bumped_layer_id),
        layer_pixels=updated_layer_pixels,
        before_layer_pixels=before_layer_pixels,
        layer_id=layer_id,
        thumbnail_layer_id=active_layer_id,
        dirty_bounds=dirty_bounds,
        history_label=f"{tool.replace('_', ' ').title()}{' Mask' if editing_mask_target else ''}",
        kind=f"{tool}_stroke",
        tracked_layer_ids=(layer_id,),
    )


def texture_editor_quick_mask_tool_allowed(tool: str) -> bool:
    return str(tool) in {"paint", "erase", "fill"}


def texture_editor_quick_mask_tool_status() -> str:
    return "Quick Mask editing currently supports Paint, Erase, and Fill."


def texture_editor_clone_source_required(settings: TextureEditorToolSettings) -> bool:
    return settings.tool in {"clone", "heal"} and settings.clone_source_point is None


def texture_editor_clone_source_required_status() -> str:
    return "Set a clone/heal source point first with Ctrl+right-click."


def texture_editor_layer_has_visible_pixels(pixels: Optional[np.ndarray]) -> bool:
    return bool(pixels is not None and pixels.size > 0 and np.any(pixels[..., 3] > 0))


def texture_editor_empty_active_layer_filter_blocked(
    settings: TextureEditorToolSettings,
    *,
    active_layer_exists: bool,
    active_layer_has_visible_pixels: bool,
) -> bool:
    return (
        settings.tool in {"sharpen", "soften"}
        and bool(active_layer_exists)
        and not settings.sample_visible_layers
        and not bool(active_layer_has_visible_pixels)
    )


def texture_editor_empty_active_layer_filter_status() -> str:
    return "The active layer is empty. Duplicate a layer first, or enable 'Sample visible layers'."


def texture_editor_stroke_source_snapshot_mode(settings: TextureEditorToolSettings) -> str:
    if settings.tool in {"clone", "heal", "sharpen", "soften", "smudge", "patch"} and settings.sample_visible_layers:
        return "visible_layers"
    if settings.tool in {"clone", "heal", "smudge", "patch"}:
        return "active_layer"
    return "none"


def texture_editor_stroke_source_snapshot(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    settings: TextureEditorToolSettings,
    active_layer: Optional[np.ndarray],
) -> Optional[np.ndarray]:
    source_snapshot_mode = texture_editor_stroke_source_snapshot_mode(settings)
    if source_snapshot_mode == "visible_layers":
        return flatten_texture_editor_layers(document, layer_pixels)
    if source_snapshot_mode == "active_layer" and active_layer is not None:
        return active_layer.copy()
    return None


def texture_editor_patch_selection_required(settings: TextureEditorToolSettings, selection_mode: str) -> bool:
    return settings.tool == "patch" and str(selection_mode or "none") == "none"


def texture_editor_patch_selection_required_status() -> str:
    return "Create a selection first, then drag with Patch to choose the repair source."


def texture_editor_recolor_pixels_with_channel_locks(
    recolored: object,
    before_pixels: object,
    *,
    edit_red_channel: bool,
    edit_green_channel: bool,
    edit_blue_channel: bool,
    edit_alpha_channel: bool,
    alpha_locked: bool,
) -> object:
    if not edit_red_channel:
        recolored[..., 0] = before_pixels[..., 0]  # type: ignore[index]
    if not edit_green_channel:
        recolored[..., 1] = before_pixels[..., 1]  # type: ignore[index]
    if not edit_blue_channel:
        recolored[..., 2] = before_pixels[..., 2]  # type: ignore[index]
    if not edit_alpha_channel or alpha_locked:
        recolored[..., 3] = before_pixels[..., 3]  # type: ignore[index]
    return recolored


def texture_editor_tool_setting_visibility(
    tool: str,
    *,
    brush_tip: str = "round",
    lasso_snap_enabled: bool = False,
    has_active_selection: bool = False,
) -> TextureEditorToolVisibility:
    brush_tools = {"paint", "erase", "clone", "heal", "sharpen", "soften", "smudge", "dodge_burn"}
    stamp_tools = {"paint", "erase", "clone", "heal", "smudge", "dodge_burn"}
    rows = {
        "brush_preset": tool in brush_tools,
        "brush_tip": tool in brush_tools,
        "custom_brush_tip": tool in stamp_tools and str(brush_tip or "round") == "image_stamp",
        "brush_pattern": tool in {"paint", "erase", "clone", "heal", "smudge", "dodge_burn"},
        "symmetry_mode": tool in {"paint", "erase", "sharpen", "soften", "smudge", "dodge_burn"},
        "paint_color": tool in {"paint", "fill", "gradient"},
        "secondary_color": tool == "gradient",
        "brush_size": tool in brush_tools,
        "size_step_mode": tool in brush_tools,
        "hardness": tool in {"paint", "erase", "clone", "heal", "smudge", "dodge_burn"},
        "roundness": tool in {"paint", "erase", "clone", "heal", "smudge", "dodge_burn"},
        "angle_degrees": tool in {"paint", "erase", "clone", "heal", "smudge", "dodge_burn"},
        "smoothing": tool in {"paint", "erase", "clone", "heal", "smudge", "dodge_burn"},
        "opacity": tool in {"paint", "erase", "clone", "heal", "fill", "gradient", "smudge", "dodge_burn"},
        "flow": tool in {"paint", "erase", "clone", "heal", "smudge", "dodge_burn"},
        "spacing": tool in {"paint", "erase", "clone", "heal", "smudge", "dodge_burn"},
        "paint_blend_mode": tool in {"paint", "fill", "gradient"},
        "fill_tolerance": tool == "fill",
        "fill_contiguous": tool == "fill",
        "strength": tool in {"sharpen", "soften"},
        "smudge_strength": tool == "smudge",
        "dodge_burn_mode": tool == "dodge_burn",
        "dodge_burn_exposure": tool == "dodge_burn",
        "patch_blend": tool == "patch",
        "gradient_type": tool == "gradient",
        "sharpen_mode": tool == "sharpen",
        "soften_mode": tool == "soften",
        "sample_visible_layers": tool in {"clone", "heal", "sharpen", "soften", "smudge", "patch"},
        "clone_aligned": tool in {"clone", "heal"},
        "clone_clear_source": tool in {"clone", "heal"},
        "lasso_snap_to_edges": tool == "lasso",
        "lasso_snap_radius": tool == "lasso" and lasso_snap_enabled,
        "lasso_snap_sensitivity": tool == "lasso" and lasso_snap_enabled,
        "clone_hint": tool in {"clone", "heal"},
        "recolor_mode": tool == "recolor",
        "recolor_source": tool == "recolor",
        "recolor_target": tool == "recolor",
        "recolor_tolerance": tool == "recolor",
        "recolor_strength": tool == "recolor",
        "recolor_preserve_luma": tool == "recolor",
        "recolor_apply": tool == "recolor",
    }
    selection_visible = tool in {"select_rect", "lasso"} or bool(has_active_selection)
    return TextureEditorToolVisibility(rows=rows, selection_section_visible=selection_visible)


def nudged_texture_editor_brush_size(
    current: float,
    direction: int,
    *,
    minimum: int,
    maximum: int,
    size_step_mode: str,
) -> int:
    step = 1 if str(size_step_mode or "normal") == "fine" else 4
    return int(max(int(minimum), min(int(maximum), float(current) + (step * int(direction)))))


def nudged_texture_editor_brush_hardness(
    current: int,
    direction: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    return max(int(minimum), min(int(maximum), int(current) + (5 * int(direction))))
