"""Pure closest-surface skin-weight transfer rules."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Sequence


@dataclass(frozen=True, slots=True)
class WeightTransferSample:
    bone_indices: tuple[int, ...]
    bone_weights: tuple[float, ...]
    distance: float
    source_face: tuple[int, int, int] | None


def sample_weight_row(
    target: Sequence[float],
    source_vertices: Sequence[object],
    source_faces: Sequence[object],
    source_bone_indices: Sequence[object],
    source_bone_weights: Sequence[object],
) -> WeightTransferSample:
    point = _point3(target)
    if point is None:
        raise ValueError("Target skin-weight position is not finite.")
    best: tuple[float, tuple[float, float, float], tuple[int, int, int]] | None = None
    for raw_face in source_faces:
        face = _face3(raw_face, len(source_vertices))
        if face is None:
            continue
        vertices = tuple(_point3(source_vertices[index]) for index in face)
        if any(vertex is None for vertex in vertices):
            continue
        barycentric, distance_squared = _closest_triangle_barycentric(point, vertices[0], vertices[1], vertices[2])  # type: ignore[arg-type]
        if best is None or distance_squared < best[0]:
            best = distance_squared, barycentric, face
    if best is None:
        return _nearest_vertex_sample(point, source_vertices, source_bone_indices, source_bone_weights)
    distance_squared, barycentric, face = best
    blended: dict[int, float] = {}
    for source_index, blend in zip(face, barycentric):
        if blend <= 1e-12:
            continue
        pairs = _weight_pairs(source_bone_indices, source_bone_weights, source_index)
        if not pairs:
            raise ValueError(f"Source skin-weight row {source_index} is empty or invalid.")
        for bone_index, weight in pairs:
            blended[bone_index] = blended.get(bone_index, 0.0) + blend * weight
    indices, weights = _pack_pairs(blended.items())
    if not indices:
        raise ValueError("Interpolated source skin weights are empty or invalid.")
    return WeightTransferSample(indices, weights, math.sqrt(max(0.0, distance_squared)), face)


def spatial_transfer_distance_limit(source_vertices: Sequence[object]) -> float:
    points = tuple(point for value in source_vertices if (point := _point3(value)) is not None)
    if not points:
        return 0.0
    minimum = tuple(min(point[axis] for point in points) for axis in range(3))
    maximum = tuple(max(point[axis] for point in points) for axis in range(3))
    diagonal = math.sqrt(sum((maximum[axis] - minimum[axis]) ** 2 for axis in range(3)))
    return max(1e-8, diagonal * 0.05)


def percentile_95(values: Sequence[float]) -> float:
    finite = sorted(float(value) for value in values if math.isfinite(float(value)) and float(value) >= 0.0)
    if not finite:
        return 0.0
    return finite[max(0, math.ceil(len(finite) * 0.95) - 1)]


def _nearest_vertex_sample(
    target: tuple[float, float, float],
    source_vertices: Sequence[object],
    source_bone_indices: Sequence[object],
    source_bone_weights: Sequence[object],
) -> WeightTransferSample:
    candidates = (
        (sum((target[axis] - point[axis]) ** 2 for axis in range(3)), index)
        for index, value in enumerate(source_vertices)
        if (point := _point3(value)) is not None
    )
    try:
        distance_squared, source_index = min(candidates)
    except ValueError as exc:
        raise ValueError("Source mesh has no finite vertices for skin-weight transfer.") from exc
    indices, weights = _pack_pairs(_weight_pairs(source_bone_indices, source_bone_weights, source_index))
    if not indices:
        raise ValueError(f"Source skin-weight row {source_index} is empty or invalid.")
    return WeightTransferSample(indices, weights, math.sqrt(max(0.0, distance_squared)), None)


def _weight_pairs(indices: Sequence[object], weights: Sequence[object], row: int) -> tuple[tuple[int, float], ...]:
    raw_indices = tuple(indices[row]) if 0 <= row < len(indices) else ()  # type: ignore[arg-type]
    raw_weights = tuple(weights[row]) if 0 <= row < len(weights) else ()  # type: ignore[arg-type]
    merged: dict[int, float] = {}
    for raw_index, raw_weight in zip(raw_indices, raw_weights):
        try:
            index = int(raw_index)
            weight = float(raw_weight)
        except (TypeError, ValueError, OverflowError):
            continue
        if index >= 0 and math.isfinite(weight) and weight > 0.0:
            merged[index] = merged.get(index, 0.0) + weight
    total = sum(merged.values())
    if total <= 0.0:
        return ()
    return tuple((index, weight / total) for index, weight in merged.items())


def _pack_pairs(pairs: Iterable[tuple[int, float]]) -> tuple[tuple[int, ...], tuple[float, ...]]:
    strongest = sorted(
        ((int(index), float(weight)) for index, weight in pairs if int(index) >= 0 and float(weight) > 0.0),
        key=lambda item: item[1],
        reverse=True,
    )[:4]
    total = sum(weight for _index, weight in strongest)
    if total <= 0.0:
        return (), ()
    normalized = sorted((index, weight / total) for index, weight in strongest)
    return tuple(index for index, _weight in normalized), tuple(weight for _index, weight in normalized)


def _point3(value: object) -> tuple[float, float, float] | None:
    try:
        point = tuple(float(component) for component in value[:3])  # type: ignore[index]
    except (TypeError, ValueError, OverflowError):
        return None
    return point if len(point) == 3 and all(math.isfinite(component) for component in point) else None


def _face3(value: object, vertex_count: int) -> tuple[int, int, int] | None:
    try:
        face = tuple(int(index) for index in value[:3])  # type: ignore[index]
    except (TypeError, ValueError, OverflowError):
        return None
    return face if len(face) == 3 and len(set(face)) == 3 and all(0 <= index < vertex_count for index in face) else None


def _closest_triangle_barycentric(
    point: tuple[float, float, float],
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
) -> tuple[tuple[float, float, float], float]:
    ab, ac, ap = _sub(b, a), _sub(c, a), _sub(point, a)
    d1, d2 = _dot(ab, ap), _dot(ac, ap)
    if d1 <= 0.0 and d2 <= 0.0:
        return (1.0, 0.0, 0.0), _length_squared(ap)
    bp = _sub(point, b)
    d3, d4 = _dot(ab, bp), _dot(ac, bp)
    if d3 >= 0.0 and d4 <= d3:
        return (0.0, 1.0, 0.0), _length_squared(bp)
    vc = d1 * d4 - d3 * d2
    if vc <= 0.0 and d1 >= 0.0 and d3 <= 0.0:
        v = d1 / (d1 - d3)
        closest = _add(a, _scale(ab, v))
        return (1.0 - v, v, 0.0), _length_squared(_sub(point, closest))
    cp = _sub(point, c)
    d5, d6 = _dot(ab, cp), _dot(ac, cp)
    if d6 >= 0.0 and d5 <= d6:
        return (0.0, 0.0, 1.0), _length_squared(cp)
    vb = d5 * d2 - d1 * d6
    if vb <= 0.0 and d2 >= 0.0 and d6 <= 0.0:
        w = d2 / (d2 - d6)
        closest = _add(a, _scale(ac, w))
        return (1.0 - w, 0.0, w), _length_squared(_sub(point, closest))
    va = d3 * d6 - d5 * d4
    if va <= 0.0 and (d4 - d3) >= 0.0 and (d5 - d6) >= 0.0:
        edge = _sub(c, b)
        w = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        closest = _add(b, _scale(edge, w))
        return (0.0, 1.0 - w, w), _length_squared(_sub(point, closest))
    denominator = va + vb + vc
    if abs(denominator) <= 1e-20:
        return (1.0, 0.0, 0.0), _length_squared(ap)
    v, w = vb / denominator, vc / denominator
    closest = _add(a, _add(_scale(ab, v), _scale(ac, w)))
    return (1.0 - v - w, v, w), _length_squared(_sub(point, closest))


def _sub(left: tuple[float, float, float], right: tuple[float, float, float]) -> tuple[float, float, float]:
    return tuple(left[index] - right[index] for index in range(3))  # type: ignore[return-value]


def _add(left: tuple[float, float, float], right: tuple[float, float, float]) -> tuple[float, float, float]:
    return tuple(left[index] + right[index] for index in range(3))  # type: ignore[return-value]


def _scale(value: tuple[float, float, float], factor: float) -> tuple[float, float, float]:
    return tuple(component * factor for component in value)  # type: ignore[return-value]


def _dot(left: tuple[float, float, float], right: tuple[float, float, float]) -> float:
    return sum(left[index] * right[index] for index in range(3))


def _length_squared(value: tuple[float, float, float]) -> float:
    return _dot(value, value)


__all__ = ["WeightTransferSample", "percentile_95", "sample_weight_row", "spatial_transfer_distance_limit"]
