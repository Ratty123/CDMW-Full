from __future__ import annotations

"""Transform control state rules for the standalone Texture Editor UI."""

import dataclasses
from dataclasses import dataclass
from typing import Optional, Tuple

from cdmw.models import TextureEditorDocument


@dataclass(frozen=True, slots=True)
class TextureEditorTransformControlsState:
    floating_controls_enabled: bool
    float_layer_enabled: bool
    scale_percent: int
    rotation_degrees: int


@dataclass(frozen=True, slots=True)
class TextureEditorFloatingTransformDocumentState:
    document: TextureEditorDocument
    history_label: str


@dataclass(frozen=True, slots=True)
class TextureEditorCanvasFloatingTransformState:
    document: TextureEditorDocument
    changed: bool
    commit: bool
    history_label: str


def texture_editor_transform_controls_state(
    document: Optional[TextureEditorDocument],
) -> TextureEditorTransformControlsState:
    has_floating = document is not None and document.floating_selection is not None
    has_active_layer = document is not None and bool(document.active_layer_id)
    if not has_floating or document is None or document.floating_selection is None:
        return TextureEditorTransformControlsState(
            floating_controls_enabled=False,
            float_layer_enabled=bool(has_active_layer),
            scale_percent=100,
            rotation_degrees=0,
        )
    floating = document.floating_selection
    return TextureEditorTransformControlsState(
        floating_controls_enabled=True,
        float_layer_enabled=bool(has_active_layer),
        scale_percent=int(round(max(floating.scale_x, floating.scale_y) * 100.0)),
        rotation_degrees=int(round(floating.rotation_degrees)),
    )


def texture_editor_applied_floating_transform_state(
    document: Optional[TextureEditorDocument],
    *,
    scale_percent: int,
    rotation_degrees: int,
) -> Optional[TextureEditorFloatingTransformDocumentState]:
    if document is None or document.floating_selection is None:
        return None
    scale = max(0.1, float(scale_percent) / 100.0)
    return TextureEditorFloatingTransformDocumentState(
        document=dataclasses.replace(
            document,
            floating_selection=dataclasses.replace(
                document.floating_selection,
                scale_x=scale,
                scale_y=scale,
                rotation_degrees=float(rotation_degrees),
                committed=False,
            ),
        ),
        history_label="Transform Floating Selection",
    )


def texture_editor_flipped_floating_transform_state(
    document: Optional[TextureEditorDocument],
    *,
    flip_x: bool,
    flip_y: bool,
) -> Optional[TextureEditorFloatingTransformDocumentState]:
    if document is None or document.floating_selection is None:
        return None
    floating = document.floating_selection
    return TextureEditorFloatingTransformDocumentState(
        document=dataclasses.replace(
            document,
            floating_selection=dataclasses.replace(
                floating,
                flip_x=(not floating.flip_x) if flip_x else floating.flip_x,
                flip_y=(not floating.flip_y) if flip_y else floating.flip_y,
                committed=False,
            ),
        ),
        history_label="Flip Floating Selection",
    )


def texture_editor_rotated_floating_transform_state(
    document: Optional[TextureEditorDocument],
    *,
    degrees: int,
) -> Optional[TextureEditorFloatingTransformDocumentState]:
    if document is None or document.floating_selection is None:
        return None
    floating = document.floating_selection
    return TextureEditorFloatingTransformDocumentState(
        document=dataclasses.replace(
            document,
            floating_selection=dataclasses.replace(
                floating,
                rotation_degrees=float(((floating.rotation_degrees + int(degrees) + 180) % 360) - 180),
                committed=False,
            ),
        ),
        history_label="Rotate Floating Selection",
    )


def texture_editor_canvas_floating_transform_history_label(mode: str) -> str:
    return {
        "move": "Move Floating Selection",
        "rotate": "Rotate Floating Selection",
        "scale_nw": "Scale Floating Selection",
        "scale_ne": "Scale Floating Selection",
        "scale_sw": "Scale Floating Selection",
        "scale_se": "Scale Floating Selection",
    }.get(str(mode or "move"), "Transform Floating Selection")


def texture_editor_canvas_floating_transform_state(
    document: Optional[TextureEditorDocument],
    payload: object,
) -> Optional[TextureEditorCanvasFloatingTransformState]:
    if document is None or document.floating_selection is None or not isinstance(payload, dict):
        return None
    floating = document.floating_selection
    next_offset_x = int(payload.get("offset_x", floating.offset_x))
    next_offset_y = int(payload.get("offset_y", floating.offset_y))
    next_scale_x = max(0.05, float(payload.get("scale_x", floating.scale_x)))
    next_scale_y = max(0.05, float(payload.get("scale_y", floating.scale_y)))
    next_rotation = float(payload.get("rotation_degrees", floating.rotation_degrees))
    commit = bool(payload.get("commit", False))
    history_label = texture_editor_canvas_floating_transform_history_label(str(payload.get("mode", "move") or "move"))
    changed = not (
        next_offset_x == int(floating.offset_x)
        and next_offset_y == int(floating.offset_y)
        and abs(next_scale_x - float(floating.scale_x)) < 1e-6
        and abs(next_scale_y - float(floating.scale_y)) < 1e-6
        and abs(next_rotation - float(floating.rotation_degrees)) < 1e-6
    )
    if not changed:
        return TextureEditorCanvasFloatingTransformState(
            document=document,
            changed=False,
            commit=commit,
            history_label=history_label,
        )
    return TextureEditorCanvasFloatingTransformState(
        document=dataclasses.replace(
            document,
            floating_selection=dataclasses.replace(
                floating,
                offset_x=next_offset_x,
                offset_y=next_offset_y,
                scale_x=next_scale_x,
                scale_y=next_scale_y,
                rotation_degrees=next_rotation,
                committed=False,
            ),
        ),
        changed=True,
        commit=commit,
        history_label=history_label,
    )


def texture_editor_floating_transform_dirty_bounds(
    before_bounds: Optional[Tuple[int, int, int, int]],
    after_bounds: Optional[Tuple[int, int, int, int]],
) -> Optional[Tuple[int, int, int, int]]:
    if before_bounds is None or after_bounds is None:
        return None
    x0 = min(before_bounds[0], after_bounds[0])
    y0 = min(before_bounds[1], after_bounds[1])
    x1 = max(before_bounds[0] + before_bounds[2], after_bounds[0] + after_bounds[2])
    y1 = max(before_bounds[1] + before_bounds[3], after_bounds[1] + after_bounds[3])
    return (int(x0), int(y0), max(1, int(x1 - x0)), max(1, int(y1 - y0)))
