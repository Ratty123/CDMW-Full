from __future__ import annotations

"""Canvas view-state rules for the standalone Texture Editor UI."""

from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Sequence, Tuple

import numpy as np

from cdmw.domain.textures.editor_composite import flatten_texture_editor_layers, flatten_texture_editor_layers_region
from cdmw.models import TextureEditorDocument
from cdmw.ui.texture_workflow.editor_floating_state import (
    compose_texture_editor_floating_selection,
    compose_texture_editor_floating_selection_region,
)


@dataclass(frozen=True, slots=True)
class TextureEditorGridColorButtonState:
    style_sheet: str
    text: str
    tooltip: str


@dataclass(frozen=True, slots=True)
class TextureEditorViewControlsState:
    compare_split_visible: bool
    compare_split_enabled: bool
    grid_size_enabled: bool
    grid_color_enabled: bool
    grid_opacity_enabled: bool


@dataclass(frozen=True, slots=True)
class TextureEditorGridControlState:
    enabled: bool
    grid_size: int
    grid_color: object
    grid_color_hex: str
    grid_opacity: int


@dataclass(frozen=True, slots=True)
class TextureEditorNavigationOverlayState:
    rulers_visible: bool
    guides_enabled: bool
    vertical_guides: Tuple[int, ...]
    horizontal_guides: Tuple[int, ...]


@dataclass(frozen=True, slots=True)
class TextureEditorRulerState:
    image_length: int
    other_length: int
    display_scale: float
    scroll_value: int
    viewport_offset: int
    hover_position: Optional[int]
    guides: Tuple[int, ...]

    def as_kwargs(self) -> Dict[str, object]:
        return {
            "image_length": self.image_length,
            "other_length": self.other_length,
            "display_scale": self.display_scale,
            "scroll_value": self.scroll_value,
            "viewport_offset": self.viewport_offset,
            "hover_position": self.hover_position,
            "guides": self.guides,
        }


@dataclass(frozen=True, slots=True)
class TextureEditorCompositeRenderState:
    rgba: np.ndarray
    cache: np.ndarray
    cache_revision: int
    dirty_bounds: Optional[Tuple[int, int, int, int]]


@dataclass(frozen=True, slots=True)
class TextureEditorResolvedViewState:
    view_mode: str
    compare_split: int
    grid_enabled: bool
    grid_size: int
    grid_color: str
    grid_opacity: int
    show_rulers: bool
    show_guides: bool
    vertical_guides: Tuple[int, ...]
    horizontal_guides: Tuple[int, ...]
    fit_to_view: bool
    zoom_factor: float
    scroll_x: int
    scroll_y: int


def _clamp_float(value: float, minimum: float, maximum: float) -> float:
    return max(float(minimum), min(float(maximum), float(value)))


def _clamp_int(value: int, minimum: int, maximum: int) -> int:
    return max(int(minimum), min(int(maximum), int(value)))


def merged_texture_editor_composite_dirty_bounds(
    current: Optional[Tuple[int, int, int, int]],
    dirty_bounds: Tuple[int, int, int, int],
) -> Tuple[int, int, int, int]:
    if current is None:
        return (
            int(dirty_bounds[0]),
            int(dirty_bounds[1]),
            int(dirty_bounds[2]),
            int(dirty_bounds[3]),
        )
    x0 = min(int(current[0]), int(dirty_bounds[0]))
    y0 = min(int(current[1]), int(dirty_bounds[1]))
    x1 = max(int(current[0]) + int(current[2]), int(dirty_bounds[0]) + int(dirty_bounds[2]))
    y1 = max(int(current[1]) + int(current[3]), int(dirty_bounds[1]) + int(dirty_bounds[3]))
    return (x0, y0, max(0, x1 - x0), max(0, y1 - y0))


def clamped_texture_editor_composite_dirty_bounds(
    dirty_bounds: Tuple[int, int, int, int],
    *,
    document_width: int,
    document_height: int,
) -> Optional[Tuple[int, int, int, int]]:
    dirty_x, dirty_y, dirty_w, dirty_h = dirty_bounds
    x0 = max(0, int(dirty_x))
    y0 = max(0, int(dirty_y))
    x1 = min(int(document_width), x0 + max(0, int(dirty_w)))
    y1 = min(int(document_height), y0 + max(0, int(dirty_h)))
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1 - x0, y1 - y0)


def texture_editor_composite_render_state(
    document: TextureEditorDocument,
    layer_pixels: Mapping[str, np.ndarray],
    floating_pixels: Optional[np.ndarray],
    *,
    revision: int,
    composite_cache: Optional[np.ndarray],
    composite_cache_revision: int,
    dirty_bounds: Optional[Tuple[int, int, int, int]],
) -> TextureEditorCompositeRenderState:
    if composite_cache is not None and int(revision) == int(composite_cache_revision):
        return TextureEditorCompositeRenderState(
            rgba=composite_cache,
            cache=composite_cache,
            cache_revision=int(revision),
            dirty_bounds=dirty_bounds,
        )
    if composite_cache is not None and dirty_bounds is not None:
        bounds = clamped_texture_editor_composite_dirty_bounds(
            dirty_bounds,
            document_width=document.width,
            document_height=document.height,
        )
        if bounds is not None:
            if not composite_cache.flags.writeable:
                composite_cache = composite_cache.copy()
            x0, y0, width, height = bounds
            x1 = x0 + width
            y1 = y0 + height
            base_region = flatten_texture_editor_layers_region(document, layer_pixels, bounds)
            composed_region = compose_texture_editor_floating_selection_region(
                document,
                base_region,
                floating_pixels,
                bounds,
            )
            composite_cache[y0:y1, x0:x1] = composed_region
            return TextureEditorCompositeRenderState(
                rgba=composite_cache,
                cache=composite_cache,
                cache_revision=int(revision),
                dirty_bounds=None,
            )
    base = flatten_texture_editor_layers(document, layer_pixels)
    composed = compose_texture_editor_floating_selection(document, base, floating_pixels)
    return TextureEditorCompositeRenderState(
        rgba=composed,
        cache=composed,
        cache_revision=int(revision),
        dirty_bounds=None,
    )


def texture_editor_zoom_factor_for_step(current_scale: float, step: int) -> float:
    current = max(0.0001, float(current_scale))
    return current * (1.15 if int(step) > 0 else 0.87)


def texture_editor_wheel_zoom_multiplier(delta: int) -> float:
    if abs(int(delta)) >= 60:
        return 1.15 ** _clamp_float(float(delta) / 120.0, -4.0, 4.0)
    return 1.0025 ** _clamp_float(float(delta), -480.0, 480.0)


def texture_editor_zoom_scroll_targets(
    *,
    widget_x: int,
    widget_y: int,
    old_scale: float,
    new_scale: float,
    viewport_x: int,
    viewport_y: int,
) -> Tuple[int, int]:
    safe_old_scale = max(0.0001, float(old_scale))
    safe_new_scale = max(0.0001, float(new_scale))
    image_x = float(widget_x) / safe_old_scale
    image_y = float(widget_y) / safe_old_scale
    return (
        int(round((image_x * safe_new_scale) - int(viewport_x))),
        int(round((image_y * safe_new_scale) - int(viewport_y))),
    )


def texture_editor_view_mode_key(value: object) -> str:
    return str(value or "edited")


def texture_editor_grid_color_hex(value: object) -> str:
    return str(value or "#74C1FF")


def texture_editor_grid_control_state(
    *,
    enabled: bool,
    grid_size: int,
    grid_color: object,
    grid_color_hex: object,
    grid_opacity: int,
) -> TextureEditorGridControlState:
    return TextureEditorGridControlState(
        enabled=bool(enabled),
        grid_size=int(grid_size),
        grid_color=grid_color,
        grid_color_hex=texture_editor_grid_color_hex(grid_color_hex),
        grid_opacity=int(grid_opacity),
    )


def texture_editor_view_controls_state(
    mode: str,
    *,
    has_document: bool,
    busy: bool,
    grid_enabled: bool,
) -> TextureEditorViewControlsState:
    available = bool(has_document) and not bool(busy)
    compare_split_visible = str(mode or "edited") == "split"
    grid_available = available and bool(grid_enabled)
    return TextureEditorViewControlsState(
        compare_split_visible=compare_split_visible,
        compare_split_enabled=available and compare_split_visible,
        grid_size_enabled=grid_available,
        grid_color_enabled=grid_available,
        grid_opacity_enabled=grid_available,
    )


def texture_editor_grid_color_button_state(color_hex: str) -> TextureEditorGridColorButtonState:
    color = str(color_hex or "#74C1FF").strip() or "#74C1FF"
    return TextureEditorGridColorButtonState(
        style_sheet=(
            "QToolButton {"
            f"background-color: {color};"
            "border: 1px solid rgba(220, 230, 245, 0.35);"
            "border-radius: 4px;"
            "}"
        ),
        text="",
        tooltip=f"Grid color: {color.upper()}",
    )


def texture_editor_navigation_overlay_state(
    *,
    has_document: bool,
    show_rulers: bool,
    show_guides: bool,
    vertical_guides: Sequence[int],
    horizontal_guides: Sequence[int],
) -> TextureEditorNavigationOverlayState:
    if not has_document:
        return TextureEditorNavigationOverlayState(
            rulers_visible=False,
            guides_enabled=False,
            vertical_guides=(),
            horizontal_guides=(),
        )
    return TextureEditorNavigationOverlayState(
        rulers_visible=bool(show_rulers),
        guides_enabled=bool(show_guides),
        vertical_guides=texture_editor_guides_from_view_state(vertical_guides),
        horizontal_guides=texture_editor_guides_from_view_state(horizontal_guides),
    )


def texture_editor_empty_ruler_state() -> TextureEditorRulerState:
    return TextureEditorRulerState(
        image_length=0,
        other_length=0,
        display_scale=1.0,
        scroll_value=0,
        viewport_offset=0,
        hover_position=None,
        guides=(),
    )


def _hover_coordinate(hover_pixel_info: object, key: str) -> Optional[int]:
    if not isinstance(hover_pixel_info, dict):
        return None
    return int(hover_pixel_info.get(key, 0))


def texture_editor_ruler_states(
    *,
    document_width: int,
    document_height: int,
    display_scale: float,
    scroll_x: int,
    scroll_y: int,
    viewport_offset_x: int,
    viewport_offset_y: int,
    hover_pixel_info: object,
    vertical_guides: Sequence[int],
    horizontal_guides: Sequence[int],
) -> Tuple[TextureEditorRulerState, TextureEditorRulerState]:
    scale = max(0.0001, float(display_scale))
    top = TextureEditorRulerState(
        image_length=int(document_width),
        other_length=int(document_height),
        display_scale=scale,
        scroll_value=int(scroll_x),
        viewport_offset=int(viewport_offset_x),
        hover_position=_hover_coordinate(hover_pixel_info, "x"),
        guides=texture_editor_guides_from_view_state(vertical_guides),
    )
    left = TextureEditorRulerState(
        image_length=int(document_height),
        other_length=int(document_width),
        display_scale=scale,
        scroll_value=int(scroll_y),
        viewport_offset=int(viewport_offset_y),
        hover_position=_hover_coordinate(hover_pixel_info, "y"),
        guides=texture_editor_guides_from_view_state(horizontal_guides),
    )
    return top, left


def texture_editor_navigator_viewport_rect(
    *,
    document_width: int,
    document_height: int,
    viewport_width: int,
    viewport_height: int,
    display_scale: float,
    scroll_x: int,
    scroll_y: int,
) -> Tuple[float, float, float, float]:
    scale = max(0.0001, float(display_scale))
    visible_w = min(float(document_width), max(1.0, float(viewport_width) / scale))
    visible_h = min(float(document_height), max(1.0, float(viewport_height) / scale))
    return (
        max(0.0, float(scroll_x) / scale),
        max(0.0, float(scroll_y) / scale),
        visible_w,
        visible_h,
    )


def texture_editor_center_scroll_values(
    *,
    image_x: float,
    image_y: float,
    display_scale: float,
    viewport_width: int,
    viewport_height: int,
    horizontal_minimum: int,
    horizontal_maximum: int,
    vertical_minimum: int,
    vertical_maximum: int,
) -> Tuple[int, int]:
    scale = max(0.0001, float(display_scale))
    target_x = int(round((float(image_x) * scale) - (float(viewport_width) / 2.0)))
    target_y = int(round((float(image_y) * scale) - (float(viewport_height) / 2.0)))
    return (
        _clamp_int(target_x, horizontal_minimum, horizontal_maximum),
        _clamp_int(target_y, vertical_minimum, vertical_maximum),
    )


def texture_editor_guides_from_view_state(values: object) -> Tuple[int, ...]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return ()
    return tuple(int(value) for value in values if isinstance(value, (int, float)))


def texture_editor_view_state_payload(
    *,
    zoom_factor: float,
    fit_to_view: bool,
    view_mode: str,
    compare_split: int,
    grid_enabled: bool,
    grid_size: int,
    grid_color: str,
    grid_opacity: int,
    show_rulers: bool,
    show_guides: bool,
    vertical_guides: Sequence[int],
    horizontal_guides: Sequence[int],
    scroll_x: int,
    scroll_y: int,
) -> Dict[str, object]:
    return {
        "zoom_factor": float(zoom_factor),
        "fit_to_view": bool(fit_to_view),
        "view_mode": str(view_mode or "edited"),
        "compare_split": int(compare_split),
        "grid_enabled": bool(grid_enabled),
        "grid_size": int(grid_size),
        "grid_color": str(grid_color or "#74C1FF"),
        "grid_opacity": int(grid_opacity),
        "show_rulers": bool(show_rulers),
        "show_guides": bool(show_guides),
        "vertical_guides": list(texture_editor_guides_from_view_state(vertical_guides)),
        "horizontal_guides": list(texture_editor_guides_from_view_state(horizontal_guides)),
        "scroll_x": int(scroll_x),
        "scroll_y": int(scroll_y),
    }


def texture_editor_resolved_view_state(
    state: Mapping[str, object],
    *,
    default_compare_split: int,
    default_grid_enabled: bool,
    default_grid_size: int,
    default_grid_color: str,
    default_grid_opacity: int,
) -> TextureEditorResolvedViewState:
    return TextureEditorResolvedViewState(
        view_mode=str(state.get("view_mode", "edited")),
        compare_split=int(state.get("compare_split", default_compare_split)),
        grid_enabled=bool(state.get("grid_enabled", default_grid_enabled)),
        grid_size=int(state.get("grid_size", default_grid_size)),
        grid_color=str(state.get("grid_color", default_grid_color)),
        grid_opacity=int(state.get("grid_opacity", default_grid_opacity)),
        show_rulers=bool(state.get("show_rulers", True)),
        show_guides=bool(state.get("show_guides", False)),
        vertical_guides=texture_editor_guides_from_view_state(state.get("vertical_guides")),
        horizontal_guides=texture_editor_guides_from_view_state(state.get("horizontal_guides")),
        fit_to_view=bool(state.get("fit_to_view", True)),
        zoom_factor=float(state.get("zoom_factor", 1.0)),
        scroll_x=int(state.get("scroll_x", 0)),
        scroll_y=int(state.get("scroll_y", 0)),
    )
