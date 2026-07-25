"""Geodesic falloff for body-region weights.

Segmenting a body by its primary skin influence gives every vertex to exactly
one region, which is anatomically right but hard-edged: a slider driven from
those weights creases the surface along the region boundary.

This softens the boundary by walking the mesh surface. Each region's weight
decays from 1 inside to 0 at a fixed geodesic distance outside it, and the
result is renormalized so every vertex's region weights still sum to 1.

Geodesic distance rather than adjacency-ring count, because rings are a
resolution artefact: the same "two rings" is a few millimetres across a dense
hand and several centimetres across a sparse thigh. A band in metres feathers
the same amount of surface everywhere.

Adjacency is per-submesh, so a band never leaks across the body/head seam. That
suits sliders, whose regions live inside one submesh anyway.
"""

from __future__ import annotations

from dataclasses import replace
import heapq
import math
from typing import Mapping, Sequence

from .body_regions import BodyRegion, BodyRegionMap, BodyRegionWeights


DEFAULT_FALLOFF_BAND = 0.03
"""Metres of surface over which a region fades out. ~3 cm on a 1.8 m body."""

Vec3 = tuple[float, float, float]
_Adjacency = dict[int, tuple[tuple[int, float], ...]]


def smooth_body_region_weights(
    mesh: object,
    region_map: BodyRegionMap,
    *,
    band: float = DEFAULT_FALLOFF_BAND,
    minimum_weight: float = 1.0e-3,
) -> BodyRegionMap:
    """Feather every region outward by ``band`` metres of surface distance.

    Returns a new map; the input is untouched. A non-positive ``band`` returns
    the map unchanged, which is the way to ask for hard region edges.
    """

    if band <= 0.0 or not region_map.populated_regions:
        return region_map

    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    adjacency: dict[int, _Adjacency] = {}
    for index in _touched_submeshes(region_map):
        if 0 <= index < len(submeshes):
            adjacency[index] = _weighted_adjacency(submeshes[index])

    # region id -> submesh -> vertex -> weight, before renormalizing.
    spread: dict[str, dict[int, dict[int, float]]] = {}
    for region in region_map.regions:
        if region.empty:
            continue
        spread[region.region_id] = {
            part.submesh_index: _feathered_part(
                part, adjacency.get(part.submesh_index, {}), band, minimum_weight
            )
            for part in region.parts
        }

    # Totals come after the cull, so the surviving weights renormalize to
    # exactly 1 per vertex. Culling afterwards would leave them short.
    totals = _totals(spread)
    regions = tuple(
        _rebuilt_region(region, spread.get(region.region_id, {}), totals)
        for region in region_map.regions
    )
    return replace(
        region_map,
        regions=regions,
        diagnostics=tuple(
            message
            for message in region_map.diagnostics
            # The hard-edge warning no longer applies once feathering has run.
            if "falloff" not in message
        )
        + (f"Region weights were feathered over {band * 1000.0:.0f} mm of surface distance.",),
    )


def _touched_submeshes(region_map: BodyRegionMap) -> tuple[int, ...]:
    return tuple(
        sorted({part.submesh_index for region in region_map.regions for part in region.parts})
    )


def _weighted_adjacency(submesh: object) -> _Adjacency:
    """Vertex graph whose edge costs are real distances along the surface."""

    vertices = tuple(getattr(submesh, "vertices", ()) or ())
    neighbours: dict[int, set[int]] = {}
    for face in tuple(getattr(submesh, "faces", ()) or ()):
        if len(face) < 3:
            continue
        a, b, c = int(face[0]), int(face[1]), int(face[2])
        for first, second in ((a, b), (b, c), (c, a)):
            if first == second:
                continue
            neighbours.setdefault(first, set()).add(second)
            neighbours.setdefault(second, set()).add(first)
    adjacency: _Adjacency = {}
    for index, linked in neighbours.items():
        if not 0 <= index < len(vertices):
            continue
        origin = _point3(vertices[index])
        row: list[tuple[int, float]] = []
        for other in linked:
            if not 0 <= other < len(vertices):
                continue
            row.append((other, _distance(origin, _point3(vertices[other]))))
        adjacency[index] = tuple(row)
    return adjacency


def _feathered_part(
    part: BodyRegionWeights,
    adjacency: _Adjacency,
    band: float,
    minimum_weight: float,
) -> dict[int, float]:
    """Region weights for one submesh, extended outward by a geodesic band.

    Multi-source Dijkstra from every vertex already in the region, stopped at
    ``band`` so the walk stays local rather than covering the whole mesh.
    """

    weights: dict[int, float] = {}
    distance: dict[int, float] = {}
    queue: list[tuple[float, int]] = []
    for vertex_index, weight in zip(part.vertex_indices, part.weights):
        weights[vertex_index] = float(weight)
        distance[vertex_index] = 0.0
        heapq.heappush(queue, (0.0, vertex_index))
    if not adjacency:
        return weights

    while queue:
        travelled, vertex_index = heapq.heappop(queue)
        if travelled > distance.get(vertex_index, math.inf):
            continue
        for neighbour, step in adjacency.get(vertex_index, ()):
            reached = travelled + step
            if reached >= band or reached >= distance.get(neighbour, math.inf):
                continue
            distance[neighbour] = reached
            heapq.heappush(queue, (reached, neighbour))

    for vertex_index, travelled in distance.items():
        if travelled <= 0.0:
            continue
        faded = _smoothstep(1.0 - (travelled / band))
        if faded >= minimum_weight and faded > weights.get(vertex_index, 0.0):
            weights[vertex_index] = faded
    return weights


def _totals(spread: Mapping[str, Mapping[int, Mapping[int, float]]]) -> dict[tuple[int, int], float]:
    totals: dict[tuple[int, int], float] = {}
    for parts in spread.values():
        for submesh_index, rows in parts.items():
            for vertex_index, weight in rows.items():
                key = (submesh_index, vertex_index)
                totals[key] = totals.get(key, 0.0) + weight
    return totals


def _rebuilt_region(
    region: BodyRegion,
    parts: Mapping[int, Mapping[int, float]],
    totals: Mapping[tuple[int, int], float],
) -> BodyRegion:
    if not parts:
        return region
    rebuilt: list[BodyRegionWeights] = []
    peak = 0.0
    total_weight = 0.0
    for submesh_index, rows in sorted(parts.items()):
        indices: list[int] = []
        values: list[float] = []
        for vertex_index in sorted(rows):
            share = totals.get((submesh_index, vertex_index), 0.0)
            if share <= 0.0:
                continue
            weight = rows[vertex_index] / share
            indices.append(vertex_index)
            values.append(weight)
            peak = max(peak, weight)
            total_weight += weight
        if indices:
            rebuilt.append(BodyRegionWeights(submesh_index, tuple(indices), tuple(values)))
    return replace(
        region,
        parts=tuple(rebuilt),
        vertex_count=sum(len(part.vertex_indices) for part in rebuilt),
        peak_weight=peak,
        total_weight=total_weight,
    )


def _smoothstep(value: float) -> float:
    clamped = max(0.0, min(1.0, float(value)))
    return clamped * clamped * (3.0 - (2.0 * clamped))


def _point3(value: Sequence[object]) -> Vec3:
    try:
        return (float(value[0]), float(value[1]), float(value[2]))
    except (TypeError, ValueError, IndexError, OverflowError):
        return (0.0, 0.0, 0.0)


def _distance(left: Vec3, right: Vec3) -> float:
    return math.sqrt(
        ((left[0] - right[0]) ** 2) + ((left[1] - right[1]) ** 2) + ((left[2] - right[2]) ** 2)
    )
