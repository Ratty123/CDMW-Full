"""Static replacement D3D11 drag UI queue state helpers."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from typing import Optional


def alignment_d3d11_drag_ui_initial_state() -> dict[str, object]:
    return {
        "global_offset": None,
        "global_rotation": None,
        "part_controls": {},
    }


def alignment_d3d11_drag_transaction_initial_state() -> dict[str, object]:
    return {
        "active": False,
        "generation": 0,
        "part_source_indices": (),
        "global": None,
        "parts": {},
    }


def alignment_d3d11_drag_generation_initial_state() -> dict[str, int]:
    return {"value": 0, "active": 0, "committed": 0}


def _vector3(values: Sequence[float]) -> tuple[float, float, float]:
    vector = tuple(float(value) for value in tuple(values)[:3])
    return (
        vector[0] if len(vector) > 0 else 0.0,
        vector[1] if len(vector) > 1 else 0.0,
        vector[2] if len(vector) > 2 else 0.0,
    )


def _vector3_with_default(
    values: Sequence[float],
    default: tuple[float, float, float],
) -> tuple[float, float, float]:
    vector = tuple(float(value) for value in tuple(values)[:3])
    return (
        vector[0] if len(vector) > 0 else default[0],
        vector[1] if len(vector) > 1 else default[1],
        vector[2] if len(vector) > 2 else default[2],
    )


def alignment_d3d11_active_transform_preview_key(mode: object) -> str:
    active_mode = str(mode or "side_by_side")
    if active_mode == "replacement_only":
        return "replacement_only"
    if active_mode == "overlay":
        return "overlay"
    return "static"


def alignment_d3d11_global_fast_preview_edit_range(
    mode: object,
    *,
    original_mesh_count: Optional[int],
    current_mesh_count: int,
) -> tuple[int, int]:
    if str(mode or "side_by_side") != "overlay" or original_mesh_count is None:
        return 0, -1
    original_count = max(0, int(original_mesh_count))
    replacement_count = max(0, int(current_mesh_count) - original_count)
    return original_count, replacement_count


def alignment_d3d11_part_fast_preview_edit_indices(
    selected_preview_indices: object,
    mode: object,
    *,
    original_mesh_count: Optional[int],
) -> tuple[int, ...] | None:
    if selected_preview_indices is None:
        return None
    normalized_indices = tuple(int(index) for index in tuple(selected_preview_indices or ()))
    if str(mode or "side_by_side") == "overlay" and original_mesh_count is not None:
        original_count = max(0, int(original_mesh_count))
        return tuple(original_count + index for index in normalized_indices)
    return normalized_indices


def alignment_d3d11_fast_transform_payload(
    *,
    source_submesh_indices: Sequence[int] = (),
    translation: Sequence[float] = (0.0, 0.0, 0.0),
    rotation_degrees: Sequence[float] = (0.0, 0.0, 0.0),
    scale_xyz: Sequence[float] = (1.0, 1.0, 1.0),
    transform_generation: int = 0,
) -> dict[str, object]:
    return {
        "source_submesh_indices": tuple(
            sorted({int(index) for index in tuple(source_submesh_indices or ()) if int(index) >= 0})
        ),
        "translation": _vector3_with_default(translation, (0.0, 0.0, 0.0)),
        "rotation_degrees": _vector3_with_default(rotation_degrees, (0.0, 0.0, 0.0)),
        "scale_xyz": _vector3_with_default(scale_xyz, (1.0, 1.0, 1.0)),
        "transform_generation": int(transform_generation),
    }


def alignment_d3d11_begin_drag_generation(
    drag_generation: MutableMapping[str, object],
    drag_transaction: MutableMapping[str, object],
    *,
    part_source_indices: Sequence[int],
    global_values: object,
    part_values_by_source_index: Mapping[int, object],
) -> int:
    generation = int(drag_generation.get("value", 0) or 0) + 1
    normalized_indices = tuple(int(index) for index in tuple(part_source_indices or ()))
    drag_generation["value"] = generation
    drag_generation["active"] = generation
    drag_transaction["active"] = True
    drag_transaction["generation"] = generation
    drag_transaction["part_source_indices"] = normalized_indices
    drag_transaction["global"] = global_values
    drag_transaction["parts"] = {
        int(source_index): part_values_by_source_index[int(source_index)]
        for source_index in normalized_indices
    }
    return generation


def alignment_d3d11_commit_drag_generation(
    drag_generation: MutableMapping[str, object],
    drag_transaction: MutableMapping[str, object],
) -> int:
    generation = int(drag_transaction.get("generation", 0) or 0)
    if generation <= 0:
        generation = int(drag_generation.get("active", 0) or 0)
    committed = max(int(drag_generation.get("committed", 0) or 0), int(generation))
    drag_generation["committed"] = committed
    drag_generation["active"] = 0
    drag_transaction["generation"] = 0
    return committed


def alignment_d3d11_finish_drag_transaction(
    drag_generation: MutableMapping[str, object],
    drag_transaction: MutableMapping[str, object],
) -> tuple[int, ...]:
    part_source_indices = alignment_d3d11_drag_part_source_indices(drag_transaction)
    drag_transaction["active"] = False
    alignment_d3d11_commit_drag_generation(drag_generation, drag_transaction)
    return part_source_indices


def alignment_d3d11_finish_drag_preview_state(part_source_indices: Sequence[int]) -> dict[str, object]:
    indices = tuple(int(index) for index in tuple(part_source_indices or ()))
    return {
        "part_source_indices": indices,
        "refresh_source_columns": bool(indices),
        "queue_part_preview": bool(indices),
        "queue_global_preview": not bool(indices),
    }


def alignment_d3d11_finish_drag_update_state(
    drag_generation: MutableMapping[str, object],
    drag_transaction: MutableMapping[str, object],
) -> dict[str, object]:
    part_source_indices = alignment_d3d11_finish_drag_transaction(
        drag_generation,
        drag_transaction,
    )
    return alignment_d3d11_finish_drag_preview_state(part_source_indices)


def alignment_d3d11_base_global_transform(
    drag_transaction: Mapping[str, object],
    fallback_values: object,
) -> object:
    base = drag_transaction.get("global")
    if isinstance(base, tuple) and len(base) == 3:
        return base
    return fallback_values


def alignment_d3d11_base_part_transform(
    drag_transaction: Mapping[str, object],
    source_index: int,
    fallback_values: object,
) -> object:
    parts = drag_transaction.get("parts")
    if isinstance(parts, Mapping):
        base = parts.get(int(source_index))
        if isinstance(base, tuple) and len(base) == 4:
            return base
    return fallback_values


def alignment_d3d11_drag_part_source_indices(
    drag_transaction: Mapping[str, object],
) -> tuple[int, ...]:
    return tuple(int(index) for index in tuple(drag_transaction.get("part_source_indices", ()) or ()))


def alignment_d3d11_preview_scale(preview_model: object) -> float:
    if preview_model is None:
        return 1.0
    try:
        scale = float(getattr(preview_model, "normalization_scale", 1.0) or 1.0)
    except (TypeError, ValueError, OverflowError):
        return 1.0
    return scale


def alignment_d3d11_translation_to_transform_units(
    delta_xyz: Sequence[float],
    *,
    preview_scale: float,
) -> tuple[float, float, float]:
    try:
        scale = float(preview_scale)
    except (TypeError, ValueError, OverflowError):
        scale = 1.0
    if abs(scale) <= 1e-8:
        scale = 1.0
    dx, dy, dz = _vector3(delta_xyz)
    return dx / scale, dy / scale, dz / scale


def alignment_d3d11_drag_total_values(
    base_values: Sequence[float],
    delta_xyz: Sequence[float],
) -> tuple[float, float, float]:
    base = _vector3(base_values)
    delta = _vector3(delta_xyz)
    return tuple(float(base[index]) + float(delta[index]) for index in range(3))


def alignment_d3d11_drag_total_update_state(
    *,
    part_source_indices: Sequence[int],
    delta_xyz: Sequence[float],
    global_base_values: Sequence[float] = (0.0, 0.0, 0.0),
    part_base_values: Mapping[int, Sequence[float]] | None = None,
) -> dict[str, object]:
    indices = tuple(int(index) for index in tuple(part_source_indices or ()))
    if indices:
        base_values = part_base_values if isinstance(part_base_values, Mapping) else {}
        return {
            "scope": "parts",
            "global_value": None,
            "part_values": {
                int(source_index): alignment_d3d11_drag_total_values(
                    base_values.get(int(source_index), (0.0, 0.0, 0.0)),
                    delta_xyz,
                )
                for source_index in indices
            },
        }
    return {
        "scope": "global",
        "global_value": alignment_d3d11_drag_total_values(global_base_values, delta_xyz),
        "part_values": {},
    }


def alignment_d3d11_drag_transform_update_state(
    *,
    part_source_indices: Sequence[int],
    delta_xyz: Sequence[float],
    value_index: int,
    global_base_values: Sequence[float] = (0.0, 0.0, 0.0),
    part_transform_values: Mapping[int, object] | None = None,
) -> dict[str, object]:
    indices = tuple(int(index) for index in tuple(part_source_indices or ()))
    if indices:
        part_values: dict[int, Sequence[float]] = {}
        transform_values = part_transform_values if isinstance(part_transform_values, Mapping) else {}
        for source_index in indices:
            values = transform_values.get(int(source_index))
            if isinstance(values, tuple) and len(values) > int(value_index):
                base_values = values[int(value_index)]
                if isinstance(base_values, Sequence):
                    part_values[int(source_index)] = base_values
        return alignment_d3d11_drag_total_update_state(
            part_source_indices=indices,
            delta_xyz=delta_xyz,
            part_base_values=part_values,
        )
    return alignment_d3d11_drag_total_update_state(
        part_source_indices=(),
        delta_xyz=delta_xyz,
        global_base_values=global_base_values,
    )


def _optional_vector3(values: Sequence[float] | None) -> tuple[float, float, float] | None:
    if values is None:
        return None
    return _vector3(values)


def alignment_d3d11_selected_part_control_state(
    current_source_index: object,
    source_index: object,
    *,
    offset: Sequence[float] | None = None,
    rotation: Sequence[float] | None = None,
) -> dict[str, object]:
    try:
        current_index = int(current_source_index)
        target_index = int(source_index)
    except (TypeError, ValueError, OverflowError):
        return {"apply": False, "offset": None, "rotation": None}
    if current_index != target_index:
        return {"apply": False, "offset": None, "rotation": None}
    return {
        "apply": True,
        "offset": _optional_vector3(offset),
        "rotation": _optional_vector3(rotation),
    }


def alignment_d3d11_global_control_state(
    *,
    offset: Sequence[float] | None = None,
    rotation: Sequence[float] | None = None,
) -> dict[str, object]:
    return {
        "apply": offset is not None or rotation is not None,
        "offset": _optional_vector3(offset),
        "rotation": _optional_vector3(rotation),
    }


def alignment_d3d11_drag_ui_timer_state(*, active: bool) -> dict[str, bool]:
    return {"start_timer": not bool(active)}


def alignment_d3d11_drag_ui_queue_global(
    state: MutableMapping[str, object],
    *,
    offset: Sequence[float] | None = None,
    rotation: Sequence[float] | None = None,
) -> None:
    if offset is not None:
        state["global_offset"] = _vector3(offset)
    if rotation is not None:
        state["global_rotation"] = _vector3(rotation)


def alignment_d3d11_drag_ui_queue_part(
    state: MutableMapping[str, object],
    source_index: int,
    *,
    offset: Sequence[float] | None = None,
    rotation: Sequence[float] | None = None,
) -> None:
    controls = state.get("part_controls")
    if not isinstance(controls, dict):
        controls = {}
        state["part_controls"] = controls
    current = dict(controls.get(int(source_index), {}) or {})
    if offset is not None:
        current["offset"] = _vector3(offset)
    if rotation is not None:
        current["rotation"] = _vector3(rotation)
    controls[int(source_index)] = current


def alignment_d3d11_drag_ui_take(
    state: MutableMapping[str, object],
) -> tuple[object, object, dict[int, Mapping[str, object]]]:
    global_offset = state.get("global_offset")
    global_rotation = state.get("global_rotation")
    controls = state.get("part_controls")
    part_controls = dict(controls) if isinstance(controls, dict) else {}
    state["global_offset"] = None
    state["global_rotation"] = None
    state["part_controls"] = {}
    return global_offset, global_rotation, part_controls


def _tuple_vector3_or_none(value: object) -> tuple[float, float, float] | None:
    if not isinstance(value, tuple):
        return None
    return _vector3(value)


def alignment_d3d11_drag_ui_flush_state(
    global_offset: object,
    global_rotation: object,
    controls: object,
) -> dict[str, object]:
    offset = _tuple_vector3_or_none(global_offset)
    rotation = _tuple_vector3_or_none(global_rotation)
    part_updates: list[dict[str, object]] = []
    if isinstance(controls, Mapping):
        for source_index, values in controls.items():
            if not isinstance(values, Mapping):
                continue
            try:
                normalized_source_index = int(source_index)
            except (TypeError, ValueError, OverflowError):
                continue
            part_updates.append(
                {
                    "source_index": normalized_source_index,
                    "offset": _tuple_vector3_or_none(values.get("offset")),
                    "rotation": _tuple_vector3_or_none(values.get("rotation")),
                }
            )
    return {
        "global": alignment_d3d11_global_control_state(offset=offset, rotation=rotation),
        "parts": tuple(part_updates),
    }


__all__ = [
    "alignment_d3d11_active_transform_preview_key",
    "alignment_d3d11_base_global_transform",
    "alignment_d3d11_base_part_transform",
    "alignment_d3d11_begin_drag_generation",
    "alignment_d3d11_commit_drag_generation",
    "alignment_d3d11_drag_generation_initial_state",
    "alignment_d3d11_drag_part_source_indices",
    "alignment_d3d11_drag_total_values",
    "alignment_d3d11_drag_transform_update_state",
    "alignment_d3d11_drag_total_update_state",
    "alignment_d3d11_drag_transaction_initial_state",
    "alignment_d3d11_drag_ui_initial_state",
    "alignment_d3d11_finish_drag_preview_state",
    "alignment_d3d11_finish_drag_transaction",
    "alignment_d3d11_finish_drag_update_state",
    "alignment_d3d11_preview_scale",
    "alignment_d3d11_translation_to_transform_units",
    "alignment_d3d11_fast_transform_payload",
    "alignment_d3d11_global_fast_preview_edit_range",
    "alignment_d3d11_global_control_state",
    "alignment_d3d11_part_fast_preview_edit_indices",
    "alignment_d3d11_drag_ui_queue_global",
    "alignment_d3d11_drag_ui_queue_part",
    "alignment_d3d11_drag_ui_flush_state",
    "alignment_d3d11_drag_ui_take",
    "alignment_d3d11_drag_ui_timer_state",
    "alignment_d3d11_selected_part_control_state",
]
