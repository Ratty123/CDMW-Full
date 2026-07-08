from __future__ import annotations

from collections.abc import Mapping

from cdmw.modding.mesh_native_core_payload_helpers import _finite_float, _index


def _apply_vertex_aligned_topology_result(
    submesh: object,
    copy_indices: list[int],
    vertex_blends: Mapping[int, tuple[int, int, float]],
    old_vertex_count: int,
    *,
    skip_normals: bool = False,
    skip_uvs: bool = False,
    skip_tangents: bool = False,
    skip_tangent_signs: bool = False,
    skip_bones: bool = False,
    skip_source_vertex_map: bool = False,
    skip_source_vertex_offsets: bool = False,
) -> None:
    if not skip_uvs:
        submesh.uvs = _copy_blend_tuple_list(submesh.uvs, copy_indices, vertex_blends, old_vertex_count, size=2)  # type: ignore[attr-defined]
    if not skip_normals:
        submesh.normals = _copy_blend_tuple_list(submesh.normals, copy_indices, vertex_blends, old_vertex_count, size=3)  # type: ignore[attr-defined]
    if not skip_tangents:
        submesh.tangents = _copy_blend_tuple_list(submesh.tangents, copy_indices, vertex_blends, old_vertex_count, size=3)  # type: ignore[attr-defined]
    if not skip_tangent_signs and getattr(submesh, "tangent_signs", None):
        setattr(submesh, "tangent_signs", _copy_blend_scalar_list(getattr(submesh, "tangent_signs"), copy_indices, vertex_blends, old_vertex_count))
    if not skip_bones:
        submesh.bone_indices, submesh.bone_weights = _copy_blend_bone_lists(  # type: ignore[attr-defined]
            submesh.bone_indices,
            submesh.bone_weights,
            copy_indices,
            vertex_blends,
            old_vertex_count,
        )
    if not skip_source_vertex_map:
        submesh.source_vertex_map = _copy_with_blend_default(submesh.source_vertex_map, copy_indices, vertex_blends, old_vertex_count, -1)  # type: ignore[attr-defined]
    if not skip_source_vertex_offsets:
        submesh.source_vertex_offsets = _copy_with_blend_default(submesh.source_vertex_offsets, copy_indices, vertex_blends, old_vertex_count, -1)  # type: ignore[attr-defined]


def _clear_vertex_aligned_topology_result(submesh: object) -> None:
    submesh.uvs = []  # type: ignore[attr-defined]
    submesh.normals = []  # type: ignore[attr-defined]
    submesh.tangents = []  # type: ignore[attr-defined]
    if hasattr(submesh, "tangent_signs"):
        setattr(submesh, "tangent_signs", [])
    submesh.bone_indices = []  # type: ignore[attr-defined]
    submesh.bone_weights = []  # type: ignore[attr-defined]
    submesh.source_vertex_map = []  # type: ignore[attr-defined]
    submesh.source_vertex_offsets = []  # type: ignore[attr-defined]


def _copy_blend_tuple_list(
    values: object,
    copy_indices: list[int],
    vertex_blends: Mapping[int, tuple[int, int, float]],
    old_vertex_count: int,
    *,
    size: int,
) -> list[tuple[float, ...]]:
    if not isinstance(values, list) or len(values) != old_vertex_count:
        return []
    result: list[tuple[float, ...]] = []
    for new_index, old_index in enumerate(copy_indices):
        if 0 <= old_index < old_vertex_count:
            result.append(_tuple_value(values[old_index], size))
            continue
        blend = vertex_blends.get(new_index)
        if blend is None:
            return []
        left, right, factor = blend
        if not (0 <= left < old_vertex_count and 0 <= right < old_vertex_count):
            return []
        left_values = _tuple_value(values[left], size)
        right_values = _tuple_value(values[right], size)
        result.append(tuple(left_values[index] + (right_values[index] - left_values[index]) * factor for index in range(size)))
    return result


def _copy_blend_scalar_list(
    values: object,
    copy_indices: list[int],
    vertex_blends: Mapping[int, tuple[int, int, float]],
    old_vertex_count: int,
) -> list[float]:
    if not isinstance(values, list) or len(values) != old_vertex_count:
        return []
    result: list[float] = []
    for new_index, old_index in enumerate(copy_indices):
        if 0 <= old_index < old_vertex_count:
            result.append(_finite_float(values[old_index], 1.0))
            continue
        blend = vertex_blends.get(new_index)
        if blend is None:
            return []
        left, right, factor = blend
        if not (0 <= left < old_vertex_count and 0 <= right < old_vertex_count):
            return []
        left_value = _finite_float(values[left], 1.0)
        right_value = _finite_float(values[right], 1.0)
        result.append(left_value + (right_value - left_value) * factor)
    return result


def _copy_with_blend_default(
    values: object,
    copy_indices: list[int],
    vertex_blends: Mapping[int, tuple[int, int, float]],
    old_vertex_count: int,
    default: object,
) -> list[object]:
    if not isinstance(values, list) or len(values) != old_vertex_count:
        return []
    result: list[object] = []
    for new_index, old_index in enumerate(copy_indices):
        if 0 <= old_index < old_vertex_count:
            result.append(values[old_index])
        elif new_index in vertex_blends:
            result.append(default)
        else:
            return []
    return result


def _copy_blend_bone_lists(
    bone_indices: object,
    bone_weights: object,
    copy_indices: list[int],
    vertex_blends: Mapping[int, tuple[int, int, float]],
    old_vertex_count: int,
) -> tuple[list[tuple[int, ...]], list[tuple[float, ...]]]:
    if (
        not isinstance(bone_indices, list)
        or not isinstance(bone_weights, list)
        or len(bone_indices) != old_vertex_count
        or len(bone_weights) != old_vertex_count
    ):
        return [], []
    result_indices: list[tuple[int, ...]] = []
    result_weights: list[tuple[float, ...]] = []
    for new_index, old_index in enumerate(copy_indices):
        if 0 <= old_index < old_vertex_count:
            result_indices.append(tuple(int(value) for value in tuple(bone_indices[old_index] or ())))
            result_weights.append(tuple(float(value) for value in tuple(bone_weights[old_index] or ())))
            continue
        blend = vertex_blends.get(new_index)
        if blend is None:
            return [], []
        blended = _blend_bone_assignment(bone_indices, bone_weights, blend[0], blend[1], old_vertex_count, blend[2])
        if blended is None:
            return [], []
        indices, weights = blended
        result_indices.append(indices)
        result_weights.append(weights)
    return result_indices, result_weights


def _blend_bone_assignment(
    bone_indices: list[object],
    bone_weights: list[object],
    left: int,
    right: int,
    old_vertex_count: int,
    factor: float,
) -> tuple[tuple[int, ...], tuple[float, ...]] | None:
    if not (0 <= left < old_vertex_count and 0 <= right < old_vertex_count):
        return None
    try:
        left_indices = tuple(int(value) for value in tuple(bone_indices[left] or ()))
        right_indices = tuple(int(value) for value in tuple(bone_indices[right] or ()))
        left_weights = tuple(float(value) for value in tuple(bone_weights[left] or ()))
        right_weights = tuple(float(value) for value in tuple(bone_weights[right] or ()))
    except (TypeError, ValueError, OverflowError):
        return None
    factor = max(0.0, min(1.0, factor))
    weights_by_bone: dict[int, float] = {}
    for bone, weight in zip(left_indices, left_weights):
        if bone >= 0 and weight > 0.0:
            weights_by_bone[bone] = weights_by_bone.get(bone, 0.0) + weight * (1.0 - factor)
    for bone, weight in zip(right_indices, right_weights):
        if bone >= 0 and weight > 0.0:
            weights_by_bone[bone] = weights_by_bone.get(bone, 0.0) + weight * factor
    if not weights_by_bone:
        return (), ()
    strongest = sorted(weights_by_bone.items(), key=lambda item: (-item[1], item[0]))[:4]
    total = sum(weight for _bone, weight in strongest)
    if total <= 0.0:
        return (), ()
    return tuple(bone for bone, _weight in strongest), tuple(weight / total for _bone, weight in strongest)


def _tuple_value(value: object, size: int) -> tuple[float, ...]:
    if not isinstance(value, (tuple, list)):
        return tuple(0.0 for _index in range(size))
    items = tuple(value)
    return tuple(_finite_float(items[index], 0.0) if index < len(items) else 0.0 for index in range(size))


def _int_list(value: object) -> list[int]:
    if not isinstance(value, list):
        return []
    return [parsed for raw in value for parsed in [_index(raw)] if parsed is not None]


def _edge_list(value: object) -> list[tuple[int, int]]:
    if not isinstance(value, list):
        return []
    result: list[tuple[int, int]] = []
    for item in value:
        if not isinstance(item, (tuple, list)) or len(item) < 2:
            continue
        left = _index(item[0])
        right = _index(item[1])
        if left is None or right is None or left == right:
            continue
        result.append((left, right) if left <= right else (right, left))
    return result


def _vertex_blends(value: object) -> dict[int, tuple[int, int, float]]:
    if not isinstance(value, list):
        return {}
    result: dict[int, tuple[int, int, float]] = {}
    for item in value:
        if not isinstance(item, Mapping):
            continue
        index = _index(item.get("index"))
        left = _index(item.get("left"))
        right = _index(item.get("right"))
        if index is None or left is None or right is None:
            continue
        result[index] = (left, right, max(0.0, min(1.0, _finite_float(item.get("factor"), 0.5))))
    return result


def _mirror_pairs_json(value: object, submesh_index: int) -> list[list[int]]:
    if not isinstance(value, Mapping):
        return []
    pairs = value.get(submesh_index, value.get(str(submesh_index)))
    if not isinstance(pairs, Mapping):
        return []
    result: list[list[int]] = []
    for raw_index, raw_mirror in pairs.items():
        index = _index(raw_index)
        mirror = _index(raw_mirror)
        if index is not None and mirror is not None and index >= 0 and mirror >= 0:
            result.append([index, mirror])
    return result


def _vertex_weights_json(value: object) -> list[list[float]]:
    if value is None:
        return []
    items = value.items() if isinstance(value, Mapping) else value
    result: list[list[float]] = []
    try:
        iterator = iter(items)  # type: ignore[arg-type]
    except TypeError:
        return []
    for item in iterator:
        try:
            raw_index, raw_weight = item  # type: ignore[misc]
        except (TypeError, ValueError):
            continue
        index = _index(raw_index)
        if index is None or index < 0:
            continue
        result.append([float(index), max(0.0, min(1.0, _finite_float(raw_weight, 0.0)))])
    return result
