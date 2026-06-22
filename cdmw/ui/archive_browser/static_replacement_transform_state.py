"""Transform and tab state helpers for static replacement."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence

from cdmw.ui.archive_browser.static_replacement_geometry_math import (
    GlobalTransformValues,
    PartTransformValues,
    add_vector3_delta,
    alignment_global_rotation_origin_state,
    alignment_rotation_nudge_value,
    global_fast_preview_transform_delta,
    global_transform_values,
    part_fast_preview_transform_delta,
    part_transform_values,
)
from cdmw.ui.archive_browser.static_replacement_transform_control_state import (
    alignment_linked_scale_sync_state,
    alignment_transform_control_text,
    alignment_transform_reset_state,
    scale_syncing_initial_state,
)

DEFAULT_GLOBAL_TRANSFORM_VALUES: GlobalTransformValues = (
    (0.0, 0.0, 0.0),
    (0.0, 0.0, 0.0),
    (1.0, 1.0, 1.0),
)


def _vector3(values: Sequence[object]) -> tuple[float, float, float]:
    vector = tuple(float(value) for value in tuple(values or ())[:3])
    return vector + (0.0,) * (3 - len(vector))


def alignment_transform_location_original_text(center_xyz: Sequence[object]) -> str:
    center = tuple(float(value) for value in tuple(center_xyz)[:3])
    if len(center) < 3:
        center = center + (0.0,) * (3 - len(center))
    return f"{center[0]:.5f}, {center[1]:.5f}, {center[2]:.5f}"


def spinbox_transform_values(
    offset_widgets: Sequence[object],
    rotation_widgets: Sequence[object],
    scale_widgets: Sequence[object],
    *,
    catch_runtime: bool,
) -> GlobalTransformValues:
    try:
        return global_transform_values(
            tuple(float(widget.value()) for widget in tuple(offset_widgets)[:3]),
            tuple(float(widget.value()) for widget in tuple(rotation_widgets)[:3]),
            tuple(float(widget.value()) for widget in tuple(scale_widgets)[:3]),
        )
    except (AttributeError, NameError, RuntimeError):
        if catch_runtime:
            return DEFAULT_GLOBAL_TRANSFORM_VALUES
        raise


def source_part_transform_values(
    source_part_adjustments: Mapping[int, object],
    source_index: int,
    adjustment_factory: Callable[[int], object],
) -> PartTransformValues:
    adjustment = source_part_adjustments.get(source_index)
    if adjustment is None:
        adjustment = adjustment_factory(source_index)
    return part_transform_values(adjustment)


def alignment_part_delta_refresh_state(
    selected_source_index: object,
    source_indices: Sequence[int],
) -> dict[str, object]:
    indices = tuple(int(index) for index in tuple(source_indices or ()))
    try:
        selected_index = int(selected_source_index)
    except (TypeError, ValueError, OverflowError):
        selected_index = -1
    return {
        "source_indices": indices,
        "reload_selected_controls": selected_index in set(indices),
        "refresh_source_columns": bool(indices),
        "queue_part_preview": bool(indices),
    }


def alignment_preview_commit_state(
    part_source_indices: Sequence[int],
    *,
    current_values: Sequence[float],
    delta_xyz: Sequence[float],
) -> dict[str, object]:
    indices = tuple(int(index) for index in tuple(part_source_indices or ()))
    if indices:
        return {
            "scope": "parts",
            "part_source_indices": indices,
            "global_values": None,
        }
    return {
        "scope": "global",
        "part_source_indices": (),
        "global_values": add_vector3_delta(current_values, delta_xyz),
    }


def alignment_preview_rotation_context_state(
    selected_source_index: object,
    *,
    part_rotation: Sequence[object] = (),
    global_rotation: Sequence[object] = (),
    global_origin: Sequence[object] | None = None,
) -> dict[str, object]:
    try:
        selected_index = int(selected_source_index)
    except (TypeError, ValueError, OverflowError):
        selected_index = -1
    if selected_index >= 0:
        return {
            "scope": "part",
            "base_rotation": _vector3(part_rotation),
            "origin_override": None,
        }
    return {
        "scope": "global",
        "base_rotation": _vector3(global_rotation),
        "origin_override": None if global_origin is None else _vector3(global_origin),
    }


def alignment_preview_drag_prepare_state(
    part_source_indices: Sequence[int],
    *,
    undo_label: str,
) -> dict[str, object]:
    indices = tuple(int(index) for index in tuple(part_source_indices or ()))
    return {
        "part_source_indices": indices,
        "push_undo": bool(indices),
        "undo_label": str(undo_label),
    }


def alignment_global_fast_preview_state(
    baked_values: object,
    current_values: GlobalTransformValues,
    *,
    preview_scale: float,
    d3d11_active: bool,
    drag_active: bool,
) -> dict[str, object]:
    if not baked_values:
        return {"apply": False, "queue_d3d11": False}
    baked_offset, baked_rotation, baked_scale = baked_values  # type: ignore[misc]
    translation_delta, rotation_delta, scale_delta = global_fast_preview_transform_delta(
        (baked_offset, baked_rotation, baked_scale),
        current_values,
        preview_scale=preview_scale,
    )
    return {
        "apply": True,
        "queue_d3d11": bool(d3d11_active) and not bool(drag_active),
        "base_rotation": _vector3(baked_rotation),
        "origin_override": "global",
        "source_submesh_indices": (),
        "translation": translation_delta,
        "rotation_degrees": rotation_delta,
        "scale_xyz": scale_delta,
    }


def alignment_part_fast_preview_state(
    source_index: int,
    baked_values: object,
    current_values: PartTransformValues,
    *,
    preview_scale: float,
    d3d11_active: bool,
    drag_active: bool,
) -> dict[str, object]:
    if not baked_values:
        return {"apply": False, "queue_d3d11": False}
    baked_offset, baked_rotation, baked_scale, baked_uniform = baked_values  # type: ignore[misc]
    translation_delta, rotation_delta, scale_delta = part_fast_preview_transform_delta(
        (baked_offset, baked_rotation, baked_scale, baked_uniform),
        current_values,
        preview_scale=preview_scale,
    )
    return {
        "apply": True,
        "queue_d3d11": bool(d3d11_active) and not bool(drag_active),
        "base_rotation": _vector3(baked_rotation),
        "origin_override": None,
        "source_submesh_indices": (int(source_index),),
        "translation": translation_delta,
        "rotation_degrees": rotation_delta,
        "scale_xyz": scale_delta,
    }


def alignment_transform_preview_queue_state(
    *,
    now: float,
    applied: bool,
    interactive_seconds: float = 0.8,
) -> dict[str, object]:
    return {
        "interactive_until": float(now) + float(interactive_seconds),
        "start_timer": not bool(applied),
    }


def alignment_part_transform_preview_queue_indices(source_index: object) -> tuple[int, ...]:
    if isinstance(source_index, Sequence) and not isinstance(source_index, (str, bytes, bytearray)):
        raw_values = tuple(source_index)
    else:
        raw_values = (source_index,)
    normalized: set[int] = set()
    for raw_index in raw_values:
        try:
            index = int(raw_index)
        except (TypeError, ValueError, OverflowError):
            continue
        if index >= 0:
            normalized.add(index)
    return tuple(sorted(normalized))


def current_alignment_transform_generation(alignment_transform_generation: Mapping[str, object]) -> int:
    return int(alignment_transform_generation.get("value", 0) or 0)


def alignment_transform_generation_initial_state() -> dict[str, int]:
    return {"value": 0, "committed": 0}


def static_preview_baked_transform_initial_state() -> dict[str, object]:
    return {"global": None, "parts": {}, "transform_generation": 0}


def capture_static_preview_baked_transform_state(
    static_preview_baked_transform_state: dict[str, object],
    *,
    global_values: GlobalTransformValues,
    part_values: Mapping[int, object],
    selected_preview_indices: Sequence[int] | None,
    transform_generation: int,
) -> dict[str, object]:
    static_preview_baked_transform_state["global"] = global_values
    static_preview_baked_transform_state["transform_generation"] = int(transform_generation)
    static_preview_baked_transform_state["parts"] = dict(part_values)
    static_preview_baked_transform_state["selected_preview_indices"] = (
        tuple(int(index) for index in selected_preview_indices)
        if selected_preview_indices is not None
        else None
    )
    return static_preview_baked_transform_state


def static_preview_interactive_until_initial_state() -> dict[str, float]:
    return {"time": 0.0}


def alignment_preview_is_interactive(
    static_preview_interactive_until: Mapping[str, object],
    *,
    monotonic: Callable[[], float] = time.monotonic,
) -> bool:
    try:
        return monotonic() < float(static_preview_interactive_until.get("time", 0.0) or 0.0)
    except Exception:
        return False


def active_tab_is(control_tabs: object, tab: object) -> bool:
    try:
        return control_tabs.widget(control_tabs.currentIndex()) is tab
    except Exception:
        return False


def mesh_edit_raw_preview_active(
    mesh_edit_enabled_checkbox: object,
    mesh_edit_tab_active: Callable[[], bool],
) -> bool:
    try:
        return bool(mesh_edit_enabled_checkbox.isChecked() and mesh_edit_tab_active())
    except Exception:
        return False


__all__ = [
    "DEFAULT_GLOBAL_TRANSFORM_VALUES",
    "active_tab_is",
    "alignment_global_fast_preview_state",
    "alignment_part_delta_refresh_state",
    "alignment_part_fast_preview_state",
    "alignment_part_transform_preview_queue_indices",
    "alignment_preview_commit_state",
    "alignment_preview_drag_prepare_state",
    "alignment_global_rotation_origin_state",
    "alignment_linked_scale_sync_state",
    "alignment_rotation_nudge_value",
    "alignment_transform_control_text",
    "alignment_preview_rotation_context_state",
    "alignment_transform_generation_initial_state",
    "alignment_transform_location_original_text",
    "alignment_transform_preview_queue_state",
    "alignment_transform_reset_state",
    "alignment_preview_is_interactive",
    "capture_static_preview_baked_transform_state",
    "current_alignment_transform_generation",
    "mesh_edit_raw_preview_active",
    "scale_syncing_initial_state",
    "source_part_transform_values",
    "spinbox_transform_values",
    "static_preview_baked_transform_initial_state",
    "static_preview_interactive_until_initial_state",
]
