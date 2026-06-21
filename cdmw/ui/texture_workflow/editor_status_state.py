from __future__ import annotations

"""Status text rules for the standalone Texture Editor UI."""

from dataclasses import dataclass
from typing import Optional

from cdmw.models import TextureEditorAdjustmentLayer, TextureEditorDocument, TextureEditorToolSettings


@dataclass(frozen=True, slots=True)
class TextureEditorCanvasStatusState:
    tool_text: str
    layer_text: str
    selection_text: str
    state_text: str
    document_text: str
    pixel_text: str
    source_text: str


@dataclass(frozen=True, slots=True)
class TextureEditorZoomLabels:
    zoom_label: str
    canvas_status_zoom_label: str


def texture_editor_zoom_labels(
    display_scale: float,
    *,
    fit_to_view: bool,
    has_document: bool,
) -> TextureEditorZoomLabels:
    scale_text = f"{float(display_scale):.0%}"
    zoom_label = f"Fit {scale_text}" if fit_to_view else scale_text
    if not has_document:
        status_label = "No zoom"
    elif fit_to_view:
        status_label = f"Zoom Fit {scale_text}"
    else:
        status_label = f"Zoom {scale_text}"
    return TextureEditorZoomLabels(zoom_label=zoom_label, canvas_status_zoom_label=status_label)


def texture_editor_sampled_color_status(color_hex: str) -> str:
    return f"Sampled color {color_hex}."


def texture_editor_busy_status_text() -> str:
    return "Texture Editor is already busy. Wait for the current task to finish."


def texture_editor_task_failed_status_text(task_label: object) -> str:
    label = str(task_label or "Texture Editor task")
    return f"{label} failed."


def texture_editor_tool_status_text(tool_key: str) -> str:
    if tool_key in {"clone", "heal"}:
        return "Ctrl+right-click sets the clone/heal source point. Use aligned sampling for classic retouching, or turn it off to stamp from a fixed source."
    if tool_key == "smudge":
        return "Smudge tool active. Drag to pull nearby texture detail for seam cleanup and blending."
    if tool_key == "dodge_burn":
        return "Dodge/Burn tool active. Use exposure and tonal mode to lighten or darken local texture detail."
    if tool_key == "patch":
        return "Patch tool active. Make a selection first, then drag to define the repair source offset for that selected region."
    if tool_key == "gradient":
        return "Gradient tool active. Drag to paint a linear or radial gradient using the primary and secondary colors."
    if tool_key == "recolor":
        return "Adjust recolor settings and use 'Apply Recolor To Active Layer'."
    if tool_key == "sharpen":
        return "Sharpen tool active. Adjust brush preset, brush tip, brush size, strength, sharpen mode, and whether to sample visible layers."
    if tool_key == "soften":
        return "Soften tool active. Adjust brush preset, brush tip, brush size, strength, soften mode, and whether to sample visible layers."
    if tool_key == "select_rect":
        return "Drag on the canvas to create a rectangular selection. Use the Selection panel to replace, add, subtract, intersect, feather, grow, or shrink."
    if tool_key == "lasso":
        return "Drag freely on the canvas to create a lasso selection. Optional edge snapping can pull it toward nearby texture edges, and the Selection panel controls how it combines."
    if tool_key == "move":
        return "Move tool active. Drag to reposition the active layer non-destructively."
    if tool_key == "fill":
        return "Fill tool active. Click to flood-fill the active layer using the current color, tolerance, and blend mode. Alt+click samples a color into the paint swatch."
    if tool_key == "paint":
        return "Paint tool active. Brush presets, image stamps, patterns, and symmetry are available here. Alt+click samples a color into the paint swatch."
    return f"{tool_key.replace('_', ' ').title()} tool active."


def texture_editor_hover_pixel_text(hover_pixel_info: Optional[object]) -> str:
    if not isinstance(hover_pixel_info, dict):
        return "XY -, -  RGBA -"
    rgba = hover_pixel_info.get("rgba", ())
    if isinstance(rgba, tuple) and len(rgba) == 4:
        return (
            f"XY {int(hover_pixel_info.get('x', 0))}, {int(hover_pixel_info.get('y', 0))}  "
            f"RGBA {int(rgba[0])}, {int(rgba[1])}, {int(rgba[2])}, {int(rgba[3])}"
        )
    return "XY -, -  RGBA -"


def texture_editor_selection_status_text(document: TextureEditorDocument, *, has_floating_pixels: bool) -> str:
    selection_text = "No selection"
    if document.floating_selection is not None and has_floating_pixels:
        selection_text = "Floating selection active"
    elif document.selection.mode != "none":
        selection_text = f"Selection: {document.selection.mode}"
    if document.quick_mask_enabled:
        selection_text = f"{selection_text} | Quick Mask"
    return selection_text


def texture_editor_canvas_status_state(
    document: Optional[TextureEditorDocument],
    tool_settings: TextureEditorToolSettings,
    *,
    hover_pixel_info: Optional[object],
    editing_mask_target: bool,
    layer_property_dirty: bool,
    adjustment_property_dirty: bool,
    selected_adjustment: Optional[TextureEditorAdjustmentLayer],
    has_floating_pixels: bool,
) -> TextureEditorCanvasStatusState:
    if document is None:
        return TextureEditorCanvasStatusState(
            tool_text="No tool",
            layer_text="No layer",
            selection_text="No selection",
            state_text="No state",
            document_text="No document",
            pixel_text="XY -, -  RGBA -",
            source_text="",
        )

    active_layer = next(
        (candidate for candidate in document.layers if candidate.layer_id == document.active_layer_id),
        None,
    )
    state_bits: list[str] = []
    if editing_mask_target:
        state_bits.append("Edit Mask")
    if layer_property_dirty:
        state_bits.append("Layer Pending")
    if adjustment_property_dirty:
        state_bits.append("Adjustment Pending")
    if selected_adjustment is not None:
        state_bits.append(f"Adj {selected_adjustment.name}")
    channel_bits = "".join(
        marker
        for enabled, marker in (
            (document.edit_red_channel, "R"),
            (document.edit_green_channel, "G"),
            (document.edit_blue_channel, "B"),
            (document.edit_alpha_channel, "A"),
        )
        if enabled
    ) or "None"
    state_bits.append(f"Ch {channel_bits}")
    if tool_settings.symmetry_mode != "off":
        state_bits.append(f"Sym {tool_settings.symmetry_mode.title()}")
    source_summary = (
        document.source_binding.relative_path
        or document.source_binding.archive_relative_path
        or document.source_binding.source_path
    )
    return TextureEditorCanvasStatusState(
        tool_text=f"Tool {tool_settings.tool.replace('_', ' ').title()}",
        layer_text=f"Layer {active_layer.name if active_layer is not None else '-'}",
        selection_text=texture_editor_selection_status_text(document, has_floating_pixels=has_floating_pixels),
        state_text=" | ".join(state_bits) if state_bits else "Ready",
        document_text=f"{document.width}x{document.height}",
        pixel_text=texture_editor_hover_pixel_text(hover_pixel_info),
        source_text=source_summary,
    )
