from __future__ import annotations

import math
from typing import Mapping

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
from cdmw.domain.textures.material_authority import (
    complete_swap_material_authority_contract,
    sanitize_texture_component,
)
from cdmw.modding.mesh_edit_ops import MESH_TOPOLOGY_ACTIONS
from cdmw.services.mesh_service_reports import _coerce_index
from cdmw.services.mesh_service_state import _MeshEditSession

_LEGACY_SCREEN_CAMERA_FIELDS = frozenset(
    {"camera_world", "yaw_degrees", "pitch_degrees", "distance", "vertical_fov_degrees", "pan"}
)
_NATIVE_EDITOR_SCREEN_PAYLOAD_KEYS = frozenset({"screen_drag", "screen_brush", "screen_radius", "screen_region"})
_NATIVE_MATERIAL_OVERRIDE_KEYS = frozenset(
    {
        "texture_brightness",
        "roughness",
        "metalness",
        "specular",
        "height_scale",
        "emissive_intensity",
        "emissive_color",
        "contrast",
        "saturation",
        "gamma",
        "tint_color",
        "native_material_hints",
        "material_shader_family",
    }
)

def _native_editor_selection_payload(selection: MeshEditSelection) -> dict[str, object]:
    payload: dict[str, object] = {
        "vertices_by_submesh": selection.vertex_map(),
        "edges_by_submesh": selection.edge_map(),
        "faces_by_submesh": selection.face_map(),
    }
    if selection.source_indices:
        payload["source_indices"] = selection.source_indices
    return payload


def _native_editor_select_payload_for_params(
    selection: MeshEditSelection,
    params: Mapping[str, object],
) -> dict[str, object]:
    raw_payload = params.get("_native_selection_payload")
    payload = dict(raw_payload) if isinstance(raw_payload, Mapping) else _native_editor_selection_payload(selection)
    raw_screen_payload = params.get("_native_screen_selection_payload")
    if isinstance(raw_screen_payload, Mapping):
        _add_native_editor_screen_selection_payload(payload, raw_screen_payload)
    if "target_mode" in params:
        payload["target_mode"] = str(params.get("target_mode") or "vertex")
    return payload


def _add_native_editor_screen_selection_payload(
    payload: dict[str, object],
    raw_screen_payload: Mapping[str, object],
) -> dict[str, object]:
    raw_screen_brush = raw_screen_payload.get("screen_brush")
    if isinstance(raw_screen_brush, Mapping):
        payload["screen_brush"] = _native_editor_screen_payload(raw_screen_brush)
    raw_screen_region = raw_screen_payload.get("screen_region")
    if isinstance(raw_screen_region, Mapping):
        payload["screen_region"] = _native_editor_screen_payload(raw_screen_region)
    if "falloff" in raw_screen_payload:
        payload["falloff"] = str(raw_screen_payload.get("falloff") or "smooth")
    if "target_mode" in raw_screen_payload:
        payload["target_mode"] = str(raw_screen_payload.get("target_mode") or "vertex")
    if "selection_depth_mode" in raw_screen_payload:
        payload["selection_depth_mode"] = str(raw_screen_payload.get("selection_depth_mode") or "visible")
    return payload


def _native_editor_screen_payload(payload: Mapping[object, object]) -> dict[object, object]:
    return {key: value for key, value in payload.items() if str(key) not in _LEGACY_SCREEN_CAMERA_FIELDS}


def _native_editor_selection_target_indices(selection: MeshEditSelection) -> set[int]:
    result = {_coerce_index(index) for index in selection.source_indices}
    for mapping in (selection.vertex_map(), selection.edge_map(), selection.face_map()):
        result.update(_coerce_index(index) for index in mapping)
    return {index for index in result if index is not None and index >= 0}


def _native_editor_edit_payload(action: str, params: Mapping[str, object]) -> dict[str, object]:
    if action == "transform":
        return _native_editor_transform_payload(params)
    payload: dict[str, object] = {
        "operation": "compact_orphans" if action == "delete_loose_vertices" else action
    }
    for key, value in params.items():
        key_text = str(key)
        if key in {"stop_event", "source_mesh", "stroke_phase", "stroke_id"} or key_text.startswith("_"):
            continue
        json_value = _native_editor_json_value(value)
        if json_value is not None:
            if key_text in _NATIVE_EDITOR_SCREEN_PAYLOAD_KEYS and isinstance(json_value, Mapping):
                payload[key_text] = _native_editor_screen_payload(json_value)
            else:
                payload[key_text] = json_value
    if action == "material_assign":
        material_extra_attrs = _native_editor_material_extra_attrs(params)
        if material_extra_attrs:
            payload["material_extra_attrs"] = material_extra_attrs
    if action in MESH_TOPOLOGY_ACTIONS:
        payload["suppress_vertex_remap_report"] = True
    return payload


def _native_editor_material_extra_attrs(params: Mapping[str, object]) -> dict[str, object]:
    attrs: dict[str, object] = {}
    profile = _first_param(params, "material_authority_profile", "material_profile", "complete_swap_material_profile")
    contract = _first_param(params, "authority_contract", "material_authority_contract")
    if not contract and profile:
        contract = complete_swap_material_authority_contract(profile)
    if profile:
        attrs["cdmw_material_authority_profile"] = str(profile)
    if contract:
        attrs["cdmw_material_authority_contract"] = sanitize_texture_component(contract)
    for param_key, attr_name in (
        ("source_material_name", "cdmw_source_material_name"),
        ("target_material_name", "cdmw_target_material_name"),
        ("slot_kind", "cdmw_material_slot_kind"),
        ("source_texture_set_key", "cdmw_source_texture_set_key"),
        ("route_status", "cdmw_material_route_status"),
        ("route_reason", "cdmw_material_route_reason"),
    ):
        if param_key in params:
            attrs[attr_name] = _material_route_value(params[param_key])
    slot_index = _first_param(params, "target_material_slot_index", "material_slot_index")
    if slot_index is not None:
        attrs["cdmw_target_material_slot_index"] = _optional_int(slot_index)
    overrides: dict[str, object] = {}
    raw_overrides = _first_param(params, "preview_native_material_overrides", "native_material_overrides")
    if isinstance(raw_overrides, Mapping):
        overrides.update({str(key): value for key, value in raw_overrides.items()})
    for key in _NATIVE_MATERIAL_OVERRIDE_KEYS:
        if key in params:
            overrides[key] = params[key]
    if overrides:
        attrs["preview_native_material_overrides"] = overrides
    result: dict[str, object] = {}
    for key, value in attrs.items():
        json_value = _native_editor_json_value(value)
        if json_value is not None:
            result[key] = json_value
    return result


def _first_param(params: Mapping[str, object], *keys: str) -> object:
    for key in keys:
        if key in params:
            return params[key]
    return None


def _material_route_value(value: object) -> object:
    return value.strip() if isinstance(value, str) else value


def _optional_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return -1


def _native_editor_transform_payload(params: Mapping[str, object]) -> dict[str, object]:
    translate = _native_editor_transform_vec3_payload(
        params.get("translate", params.get("delta", (0.0, 0.0, 0.0))),
        fallback=(0.0, 0.0, 0.0),
    )
    scale = _native_editor_transform_vec3_payload(
        params.get("scale", (1.0, 1.0, 1.0)),
        fallback=(1.0, 1.0, 1.0),
    )
    rotate = _native_editor_transform_vec3_payload(
        params.get("rotate", params.get("rotate_degrees", (0.0, 0.0, 0.0))),
        fallback=(0.0, 0.0, 0.0),
    )
    pivot_value = params.get("pivot")
    payload: dict[str, object] = {
        "operation": "transform",
        "translate": translate,
        "scale": scale,
        "rotate": rotate,
        "pivot": _native_editor_vec3(pivot_value) if pivot_value is not None else (0.0, 0.0, 0.0),
        "pivot_from_selection": pivot_value is None,
        "snap": _native_editor_positive_float(params.get("snap", params.get("snap_increment", 0.0))),
        "mirror_x": bool(params.get("mirror_x", False)) and scale == (1.0, 1.0, 1.0) and rotate == (0.0, 0.0, 0.0),
        "recompute_normals": bool(params.get("recompute_normals", True)),
    }
    axis = str(params.get("axis", params.get("constraint_axis", "")) or "").strip().lower()
    if axis:
        payload["axis"] = axis
    screen_drag = _native_editor_json_value(params.get("screen_drag"))
    if isinstance(screen_drag, Mapping):
        payload["screen_drag"] = _native_editor_screen_payload(screen_drag)
    mirror_pairs = _native_editor_mirror_pairs_by_submesh(params.get("mirror_pairs_by_submesh"))
    if mirror_pairs:
        payload["mirror_pairs_by_submesh"] = mirror_pairs
    return payload


def _native_editor_transform_vec3_payload(
    value: object,
    *,
    fallback: tuple[float, float, float],
) -> object:
    parsed = _native_editor_json_value(value)
    if isinstance(parsed, Mapping):
        return parsed
    if isinstance(parsed, list) and len(parsed) >= 3:
        return tuple(parsed[:3])
    return fallback


def _native_editor_stroke_phase(params: Mapping[str, object]) -> str | None:
    value = params.get("stroke_phase")
    if value is None:
        return None
    text = str(value or "").strip().lower()
    return text or None


def _native_editor_stroke_id(params: Mapping[str, object]) -> str | None:
    value = params.get("stroke_id")
    if value is None:
        return None
    text = str(value or "").strip()
    return text or None


def _mesh_edit_selection_signature(selection: MeshEditSelection) -> tuple[object, ...]:
    return (
        selection.vertices_by_submesh,
        selection.edges_by_submesh,
        selection.faces_by_submesh,
        selection.source_indices,
    )


def _native_editor_selection_payload_for_apply(
    selection: MeshEditSelection,
    params: Mapping[str, object],
) -> dict[str, object]:
    raise_if_cancelled(_stop_event_from_params(params), "Native mesh edit cancelled.")
    raw_screen_payload = params.get("_native_screen_selection_payload")
    if isinstance(raw_screen_payload, Mapping):
        raw_payload = params.get("_native_selection_payload")
        payload = dict(raw_payload) if isinstance(raw_payload, Mapping) else {}
        result = _add_native_editor_binary_vertex_selection_payload(
            _add_native_editor_screen_selection_payload(payload, raw_screen_payload),
            params,
        )
    else:
        payload = params.get("_native_selection_payload")
        result = _add_native_editor_binary_vertex_selection_payload(
            dict(payload) if isinstance(payload, Mapping) else _native_editor_selection_payload(selection),
            params,
        )
    raise_if_cancelled(_stop_event_from_params(params), "Native mesh edit cancelled.")
    return result


def _add_native_editor_binary_vertex_selection_payload(
    payload: dict[str, object],
    params: Mapping[str, object],
) -> dict[str, object]:
    raw = params.get("native_selected_vertices_binary_by_submesh")
    if not isinstance(raw, Mapping):
        return payload
    existing = payload.get("vertices_by_submesh")
    vertices_by_submesh = dict(existing) if isinstance(existing, Mapping) else {}
    for raw_submesh_index, raw_descriptor in raw.items():
        descriptor = _native_editor_json_value(raw_descriptor)
        if isinstance(descriptor, Mapping):
            vertices_by_submesh[str(raw_submesh_index)] = {"selected_vertices_binary": dict(descriptor)}
    if vertices_by_submesh:
        payload["vertices_by_submesh"] = vertices_by_submesh
    return payload


def _native_editor_selection_signature_for_apply(
    selection: MeshEditSelection,
    params: Mapping[str, object],
) -> tuple[object, ...]:
    raise_if_cancelled(_stop_event_from_params(params), "Native mesh edit cancelled.")
    if isinstance(params.get("_native_screen_selection_payload"), Mapping):
        signature = ("native-screen", _freeze_native_selection_value(_native_editor_selection_payload_for_apply(selection, params)))
    else:
        payload = params.get("_native_selection_payload")
        signature = (
            "native" if isinstance(payload, Mapping) else "selection",
            _freeze_native_selection_value(
                _add_native_editor_binary_vertex_selection_payload(dict(payload), params)
                if isinstance(payload, Mapping)
                else _native_editor_selection_payload_for_apply(selection, params)
            ),
        )
    raise_if_cancelled(_stop_event_from_params(params), "Native mesh edit cancelled.")
    return signature


def _freeze_native_selection_value(value: object) -> object:
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _freeze_native_selection_value(item)) for key, item in value.items()))
    if isinstance(value, (str, bytes)):
        return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
    try:
        return tuple(_freeze_native_selection_value(item) for item in value)  # type: ignore[arg-type]
    except TypeError:
        return value


def _can_reuse_native_live_stroke_selection(
    session: _MeshEditSession,
    params: Mapping[str, object],
    selection_signature: tuple[object, ...],
) -> bool:
    phase = _native_editor_stroke_phase(params)
    if phase not in {"update", "end", "cancel"}:
        return False
    stroke_id = _native_editor_stroke_id(params)
    if not stroke_id or stroke_id != session.native_editor_active_stroke_id:
        return False
    if phase in {"end", "cancel"} and not isinstance(params.get("_native_selection_payload"), Mapping):
        return bool(session.native_editor_session_ready and session.native_editor_selection_signature)
    return bool(
        session.native_editor_session_ready
        and session.native_editor_selection_signature
        and selection_signature == session.native_editor_selection_signature
    )


def _can_reuse_native_stroke_begin_selection(
    session: _MeshEditSession,
    params: Mapping[str, object],
    selection_signature: tuple[object, ...],
) -> bool:
    if _native_editor_stroke_phase(params) != "begin":
        return False
    if isinstance(params.get("_native_selection_payload"), Mapping):
        return False
    if isinstance(params.get("_native_screen_selection_payload"), Mapping):
        return False
    return bool(
        session.native_editor_session_ready
        and session.native_editor_selection_signature
        and _native_editor_selection_signature_matches_resident(session.native_editor_selection_signature, selection_signature)
    )


def _can_reuse_native_stroke_begin_mesh_selection(
    session: _MeshEditSession,
    params: Mapping[str, object],
    selection: MeshEditSelection,
) -> bool:
    if _native_editor_stroke_phase(params) != "begin":
        return False
    if isinstance(params.get("_native_selection_payload"), Mapping):
        return False
    if isinstance(params.get("_native_screen_selection_payload"), Mapping):
        return False
    if isinstance(params.get("native_selected_vertices_binary_by_submesh"), Mapping):
        return False
    return bool(
        session.native_editor_session_ready
        and session.native_editor_selection_signature
        and session.native_editor_selection_signature == _mesh_edit_selection_signature(selection)
    )


def _native_editor_selection_signature_matches_resident(
    resident_signature: tuple[object, ...],
    selection_signature: tuple[object, ...],
) -> bool:
    if selection_signature == resident_signature:
        return True
    return (
        len(selection_signature) == 2
        and selection_signature[0] == "selection"
        and selection_signature[1] == resident_signature
    )


def _native_editor_vec3(value: object, fallback: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> tuple[float, float, float]:
    if isinstance(value, (str, bytes)):
        return fallback
    if isinstance(value, Mapping):
        items = (value.get("x"), value.get("y"), value.get("z"))
    else:
        try:
            items = tuple(value)  # type: ignore[arg-type]
        except TypeError:
            return fallback
    if len(items) < 3:
        return fallback
    result: list[float] = []
    for item in items[:3]:
        if isinstance(item, bool):
            return fallback
        try:
            number = float(item)  # type: ignore[arg-type]
        except (TypeError, ValueError, OverflowError):
            return fallback
        if not math.isfinite(number):
            return fallback
        result.append(number)
    return (result[0], result[1], result[2])


def _native_editor_positive_float(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return number if math.isfinite(number) and number > 0.0 else 0.0


def _native_editor_mirror_pairs_by_submesh(value: object) -> dict[str, list[list[int]]]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, list[list[int]]] = {}
    for raw_submesh, raw_pairs in value.items():
        submesh_index = _coerce_index(raw_submesh)
        if submesh_index is None or submesh_index < 0 or not isinstance(raw_pairs, Mapping):
            continue
        pairs: list[list[int]] = []
        for raw_left, raw_right in raw_pairs.items():
            left = _coerce_index(raw_left)
            right = _coerce_index(raw_right)
            if left is not None and right is not None and left >= 0 and right >= 0:
                pairs.append([left, right])
        if pairs:
            result[str(submesh_index)] = pairs
    return result


def _native_editor_metrics(report: Mapping[str, object]) -> dict[str, float]:
    raw_metrics = report.get("metrics")
    metrics = _coerce_metrics(raw_metrics if isinstance(raw_metrics, Mapping) else None)
    for key in (
        "history_undo_count",
        "history_redo_count",
        "history_undo_retained_bytes",
        "history_redo_retained_bytes",
        "history_retained_bytes",
        "history_max_operations",
        "history_max_bytes",
        "resident_sparse_update_count",
    ):
        value = _coerce_index(report.get(key))
        if value is not None and value >= 0:
            metrics[f"native_{key}"] = float(value)
    return metrics


def _native_editor_stroke_metrics(report: Mapping[str, object]) -> tuple[dict[str, float], str, str, bool]:
    raw_stroke = report.get("stroke")
    if not isinstance(raw_stroke, Mapping):
        return {}, "", "", False
    stroke_id = str(raw_stroke.get("stroke_id") or "").strip()
    phase = str(raw_stroke.get("phase") or "").strip().lower()
    update_count = _coerce_index(raw_stroke.get("update_count"))
    metrics = {
        "native_stroke_active": 1.0 if bool(raw_stroke.get("active")) else 0.0,
        "native_stroke_history_coalesced": 1.0 if bool(raw_stroke.get("history_coalesced")) else 0.0,
        "native_stroke_history_cancelled": 1.0 if bool(raw_stroke.get("history_cancelled")) else 0.0,
    }
    if update_count is not None and update_count >= 0:
        metrics["native_stroke_update_count"] = float(update_count)
    return metrics, stroke_id, phase, bool(raw_stroke.get("history_cancelled"))


def _prefixed_metrics(metrics: Mapping[str, float], prefix: str) -> dict[str, float]:
    return {f"{prefix}_{key}": value for key, value in metrics.items()}


def _coerce_metrics(metrics: Mapping[str, object] | None) -> dict[str, float]:
    result: dict[str, float] = {}
    for key, value in dict(metrics or {}).items():
        try:
            parsed = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(parsed):
            result[str(key)] = parsed
    return result


def _native_editor_json_value(value: object) -> object | None:
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, (int, float)):
        number = float(value)
        return value if math.isfinite(number) else None
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            parsed = _native_editor_json_value(item)
            if parsed is not None:
                result[str(key)] = parsed
        return result
    if isinstance(value, (tuple, list)):
        result: list[object] = []
        for item in value:
            parsed = _native_editor_json_value(item)
            if parsed is not None:
                result.append(parsed)
        return result
    return None


def _can_defer_native_live_history(action: str, command: MeshEditCommand) -> bool:
    if action not in {"transform", "brush"}:
        return False
    return True


def _stop_event_from_params(params: Mapping[str, object]) -> object | None:
    candidate = params.get("stop_event") if isinstance(params, Mapping) else None
    return candidate if callable(getattr(candidate, "is_set", None)) else None
