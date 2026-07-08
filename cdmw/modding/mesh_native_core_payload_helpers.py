from __future__ import annotations

import math
from collections.abc import Iterable, Mapping

from cdmw.modding.mesh_native_core_constants import Vec2, Vec3
from cdmw.modding.mesh_parser import ParsedMesh


def _index(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
        return None
    try:
        index = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return index


def _valid_face_triplet(face: object, vertex_count: int) -> tuple[int, int, int] | None:
    if not isinstance(face, (tuple, list)) or len(face) < 3:
        return None
    raw_a = face[0]
    raw_b = face[1]
    raw_c = face[2]
    if (
        isinstance(raw_a, int)
        and not isinstance(raw_a, bool)
        and isinstance(raw_b, int)
        and not isinstance(raw_b, bool)
        and isinstance(raw_c, int)
        and not isinstance(raw_c, bool)
    ):
        a = raw_a
        b = raw_b
        c = raw_c
    else:
        parsed_a = _index(raw_a)
        parsed_b = _index(raw_b)
        parsed_c = _index(raw_c)
        if parsed_a is None or parsed_b is None or parsed_c is None:
            return None
        a = parsed_a
        b = parsed_b
        c = parsed_c
    if 0 <= a < vertex_count and 0 <= b < vertex_count and 0 <= c < vertex_count:
        return a, b, c
    return None


def _face_count_json(faces: object, vertex_count: int) -> int:
    if not isinstance(faces, list):
        return 0
    count = 0
    for face in faces:
        if not isinstance(face, (tuple, list)) or len(face) < 3:
            continue
        raw_a = face[0]
        raw_b = face[1]
        raw_c = face[2]
        if (
            isinstance(raw_a, int)
            and not isinstance(raw_a, bool)
            and isinstance(raw_b, int)
            and not isinstance(raw_b, bool)
            and isinstance(raw_c, int)
            and not isinstance(raw_c, bool)
        ):
            a = raw_a
            b = raw_b
            c = raw_c
        else:
            parsed = _valid_face_triplet(face, vertex_count)
            if parsed is None:
                continue
            a, b, c = parsed
        if 0 <= a < vertex_count and 0 <= b < vertex_count and 0 <= c < vertex_count:
            count += 1
    return count


def _face_json(faces: object, vertex_count: int) -> list[list[int]]:
    result: list[list[int]] = []
    if not isinstance(faces, list):
        return result
    append = result.append
    for face in faces:
        parsed = _valid_face_triplet(face, vertex_count)
        if parsed is not None:
            append([parsed[0], parsed[1], parsed[2]])
    return result


def _face_json_with_source_indices(faces: object, vertex_count: int) -> tuple[list[list[int]], list[int]]:
    result: list[list[int]] = []
    source_indices: list[int] = []
    if not isinstance(faces, list):
        return result, source_indices
    append = result.append
    source_append = source_indices.append
    for face_index, face in enumerate(faces):
        parsed = _valid_face_triplet(face, vertex_count)
        if parsed is not None:
            append([parsed[0], parsed[1], parsed[2]])
            source_append(face_index)
    return result, source_indices


def _remap_vertex_aligned_list(values: object, index_map: list[int]) -> list[object]:
    if not isinstance(values, list) or len(values) != len(index_map):
        return []
    size = max((index for index in index_map if index >= 0), default=-1) + 1
    result: list[object] = [None] * size
    for old_index, new_index in enumerate(index_map):
        if 0 <= new_index < size and result[new_index] is None:
            result[new_index] = values[old_index]
    return [] if any(item is None for item in result) else result


def _copy_vertex_aligned_list(values: object, remap: list[int]) -> list[object]:
    if not isinstance(values, list) or not remap:
        return []
    if max(remap, default=-1) >= len(values):
        return []
    return [values[old_index] for old_index in remap]


def _vec3_json(value: object, fallback: float = 0.0) -> list[float]:
    parsed = _vec3(value, fallback=fallback)
    return [parsed[0], parsed[1], parsed[2]]


def _vec2_json(value: object, fallback: float = 0.0) -> list[float]:
    parsed = _vec2(value, fallback=fallback)
    return [parsed[0], parsed[1]]


def _native_uv_transform_payload(value: Mapping[str, object]) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    payload = {
        "offset": _vec2_json(value.get("offset", (0.0, 0.0))),
        "scale": _vec2_json(value.get("scale", (1.0, 1.0)), fallback=1.0),
        "rotate": _finite_float(value.get("rotate", value.get("rotate_degrees", 0.0)), 0.0),
        "flip_u": bool(value.get("flip_u", False)),
        "flip_v": bool(value.get("flip_v", False)),
        "pivot": _vec2_json(value.get("pivot", (0.0, 0.0))),
    }
    for key in ("input_bounds_min", "input_bounds_max", "input_clamp_min", "input_clamp_max"):
        if key in value:
            payload[key] = _vec2_json(value.get(key))
    if "clamp_input_uv" in value:
        payload["clamp_input_uv"] = bool(value.get("clamp_input_uv"))
    for key in ("projection", "plane", "axis"):
        text = str(value.get(key, "") or "").strip().lower()
        if text:
            payload[key] = text
    if bool(value.get("initialize_missing_uvs")):
        payload["initialize_missing_uvs"] = True
    if bool(value.get("normalize")):
        payload["normalize"] = True
        payload["target_min"] = _vec2_json(value.get("target_min", value.get("normalize_min", (0.0, 0.0))))
        payload["target_max"] = _vec2_json(value.get("target_max", value.get("normalize_max", (1.0, 1.0))), fallback=1.0)
    if bool(value.get("pack")):
        payload["pack"] = True
        payload["pack_columns"] = max(0, _index(value.get("pack_columns")) or 0)
        payload["padding"] = max(0.0, _finite_float(value.get("padding", value.get("pack_padding", 0.02)), 0.02))
    for key in ("align_u", "align_v"):
        if key in value and value.get(key) is not None:
            raw_align = value.get(key)
            if isinstance(raw_align, str):
                payload[key] = raw_align.strip().lower()
            else:
                payload[key] = _finite_float(raw_align, 0.0)
    raw_snap_step = value.get("snap_step")
    if raw_snap_step is not None:
        snap_step = _vec2_json(raw_snap_step)
        if snap_step[0] > 0.0 and snap_step[1] > 0.0:
            payload["snap"] = True
            payload["snap_step"] = snap_step
    return payload


def _finite_vec3_list_or_none(values: object) -> list[list[float]] | None:
    result: list[list[float]] = []
    try:
        raw_values = tuple(values or ())
    except TypeError:
        return None
    for value in raw_values:
        if not isinstance(value, (tuple, list)) or len(value) < 3:
            return None
        try:
            parsed = (float(value[0]), float(value[1]), float(value[2]))
        except (TypeError, ValueError, OverflowError):
            return None
        if not all(math.isfinite(component) for component in parsed):
            return None
        result.append([parsed[0], parsed[1], parsed[2]])
    return result


def _finite_vec2_list_or_none(values: object) -> list[list[float]] | None:
    result: list[list[float]] = []
    try:
        raw_values = tuple(values or ())
    except TypeError:
        return None
    for value in raw_values:
        if not isinstance(value, (tuple, list)) or len(value) < 2:
            return None
        try:
            parsed = (float(value[0]), float(value[1]))
        except (TypeError, ValueError, OverflowError):
            return None
        if not all(math.isfinite(component) for component in parsed):
            return None
        result.append([parsed[0], parsed[1]])
    return result


def _vec3(value: object, *, fallback: float = 0.0) -> Vec3:
    if not isinstance(value, (tuple, list)) or len(value) < 3:
        return (fallback, fallback, fallback)
    return (
        _finite_float(value[0], fallback),
        _finite_float(value[1], fallback),
        _finite_float(value[2], fallback),
    )


def _vec2(value: object, *, fallback: float = 0.0) -> Vec2:
    if not isinstance(value, (tuple, list)) or len(value) < 2:
        return (fallback, fallback)
    return (
        _finite_float(value[0], fallback),
        _finite_float(value[1], fallback),
    )


def _finite_float(value: object, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return fallback
    return parsed if math.isfinite(parsed) else fallback


def _finite_float_sequence(value: object, *, expected_count: int) -> tuple[float, ...] | None:
    try:
        items = tuple(value or ())  # type: ignore[arg-type]
    except TypeError:
        return None
    if len(items) != expected_count:
        return None
    result: list[float] = []
    for item in items:
        try:
            parsed = float(item)  # type: ignore[arg-type]
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(parsed):
            return None
        result.append(parsed)
    return tuple(result)


def _source_part_adjustment_payload(value: object) -> dict[str, object] | None:
    if value is None:
        return None

    def raw_field(name: str, fallback: object = None) -> object:
        if isinstance(value, Mapping):
            return value.get(name, fallback)
        return getattr(value, name, fallback)

    def vec3_field(name: str, fallback: tuple[float, float, float]) -> tuple[float, float, float] | None:
        raw = raw_field(name, None)
        if raw is None:
            return fallback
        parsed = _finite_float_sequence(raw, expected_count=3)
        return parsed if parsed is not None else None

    scale = vec3_field("scale_xyz", (1.0, 1.0, 1.0))
    offset = vec3_field("offset_xyz", (0.0, 0.0, 0.0))
    rotation = vec3_field("rotate_xyz_degrees", (0.0, 0.0, 0.0))
    if scale is None or offset is None or rotation is None:
        return None
    payload: dict[str, object] = {
        "scale_xyz": list(scale),
        "uniform_scale": _finite_float(raw_field("uniform_scale", 1.0), 1.0),
        "offset_xyz": list(offset),
        "rotate_xyz_degrees": list(rotation),
    }
    pivot = vec3_field("pivot", (0.0, 0.0, 0.0)) if raw_field("pivot", None) is not None else None
    if pivot is not None:
        payload["pivot"] = list(pivot)
    return payload


def _source_part_adjustment_pivot_vertices(value: object) -> tuple[object, ...]:
    if value is None:
        return ()
    raw = value.get("pivot_vertices") if isinstance(value, Mapping) else getattr(value, "pivot_vertices", None)
    try:
        return tuple(raw or ())  # type: ignore[arg-type]
    except TypeError:
        return ()


def _same_vec3(left: Vec3, right: Vec3) -> bool:
    return abs(left[0] - right[0]) <= 1e-8 and abs(left[1] - right[1]) <= 1e-8 and abs(left[2] - right[2]) <= 1e-8


def _same_vec3_tuple(left: tuple[Vec3, ...], right: tuple[Vec3, ...]) -> bool:
    return len(left) == len(right) and all(_same_vec3(left_item, right_item) for left_item, right_item in zip(left, right))


def _iter_valid_submesh_indices(mesh: ParsedMesh, values: object, *, all_when_none: bool = False) -> Iterable[int]:
    if values is None:
        if all_when_none:
            yield from range(len(mesh.submeshes))
        return
    try:
        iterator = iter(values or ())  # type: ignore[arg-type]
    except TypeError:
        return
    for raw_value in iterator:
        index = _index(raw_value)
        if index is not None and 0 <= index < len(mesh.submeshes):
            yield index


def _sorted_unique_valid_submesh_indices(mesh: ParsedMesh, values: object, *, all_when_none: bool = False) -> tuple[int, ...]:
    return tuple(sorted(set(_iter_valid_submesh_indices(mesh, values, all_when_none=all_when_none))))
