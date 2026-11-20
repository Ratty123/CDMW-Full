"""Carrying a small LOD0 edit onto lower LODs stays fast and finds the same neighbours."""

from __future__ import annotations

import math
import random
import time

from cdmw.modding.mesh_builder_common import _build_spatial_hash, _nearby_point_indices, _spatial_cell_key
from cdmw.modding.mesh_pamlod_builder import transfer_edit_to_lower_parts
from cdmw.modding.mesh_parser import SubMesh


def _cube_scan(point, source_points, cell_size, grid, radius):
    base = _spatial_cell_key(point, cell_size)
    cell_radius = max(1, int(math.ceil(radius / max(cell_size, 1e-6))))
    found = []
    for dx in range(-cell_radius, cell_radius + 1):
        for dy in range(-cell_radius, cell_radius + 1):
            for dz in range(-cell_radius, cell_radius + 1):
                for index in grid.get((base[0] + dx, base[1] + dy, base[2] + dz), ()):
                    if math.dist(source_points[index], point) <= radius:
                        found.append(index)
    return found


def test_occupied_cell_scan_returns_the_cube_scan_result_in_the_same_order():
    rng = random.Random(7)
    points = [(rng.uniform(0, 1), rng.uniform(0, 1), rng.uniform(0, 1)) for _ in range(40)]
    cell_size, grid = _build_spatial_hash(points)
    for _ in range(60):
        query = (rng.uniform(-0.2, 1.2), rng.uniform(-0.2, 1.2), rng.uniform(-0.2, 1.2))
        for radius in (0.05, 0.4, 2.5):
            assert _nearby_point_indices(query, points, cell_size, grid, radius) == _cube_scan(
                query, points, cell_size, grid, radius)


def _grid_part(count: int, offset: float = 0.0) -> SubMesh:
    side = int(math.ceil(math.sqrt(count)))
    vertices = [((index % side) * 0.01 + offset, (index // side) * 0.01, 0.0) for index in range(count)]
    faces = [(index, index + 1, index + side) for index in range(count - side - 1) if (index + 1) % side]
    return SubMesh(name="part", material="stone", vertices=vertices, faces=faces,
                   vertex_count=len(vertices), face_count=len(faces))


def test_one_moved_vertex_reaches_lower_lods_in_bounded_time():
    original = _grid_part(900).vertices
    edited = list(original)
    edited[450] = (edited[450][0], edited[450][1], edited[450][2] + 0.05)
    lower = [_grid_part(400, 0.001), _grid_part(100, 0.002)]
    before = [list(part.vertices) for part in lower]
    started = time.perf_counter()
    transfer_edit_to_lower_parts(original, edited, lower, one_to_one=True)
    assert time.perf_counter() - started < 10.0
    moved = [sum(a != b for a, b in zip(old, part.vertices)) for old, part in zip(before, lower)]
    assert moved[0] > 0
