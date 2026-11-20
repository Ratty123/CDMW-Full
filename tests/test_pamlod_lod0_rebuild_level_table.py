"""A LOD0 vertex count change keeps the PAMLOD level table and the lower LODs intact."""

from __future__ import annotations

import copy
import math
import struct

import pytest

from cdmw.modding.mesh_pamlod_builder import build_pamlod
from cdmw.modding.mesh_parser import _pamlod_level_blocks, parse_pamlod
from tests.static_mesh_fixtures import shipped_pamlod


def _edit(mesh, mode):
    edited = copy.deepcopy(mesh)
    lod0 = edited.lod_levels[0]
    if mode == "hide_part":
        lod0[1].vertices, lod0[1].faces, lod0[1].uvs = [], [], []
    else:
        part = lod0[0]
        vertex = (0.1, 0.1, 0.0) if mode == "add_vertex" else (3.0, 0.5, 0.0)
        part.vertices = [*part.vertices, vertex]
        part.uvs = [*part.uvs, (0.5, 0.5)]
        part.faces = [*part.faces, (0, 1, len(part.vertices) - 1)]
    edited.submeshes = lod0
    return edited


@pytest.mark.parametrize("mode", ["hide_part", "add_vertex", "add_vertex_outside_bounds"])
def test_lod0_count_change_restates_the_level_table(mode):
    source = shipped_pamlod()
    original = parse_pamlod(source, "object/stone.pamlod")
    rebuilt = build_pamlod(_edit(original, mode), source)

    geometry = struct.unpack_from("<I", rebuilt, 4)[0]
    stated = _pamlod_level_blocks(rebuilt, 3, geometry)
    assert stated is not None
    assert all(offset % 16 == 0 for offset, _size in stated[1])
    reparsed = parse_pamlod(rebuilt, "object/stone.pamlod")
    assert [[len(part.vertices) for part in level] for level in reparsed.lod_levels[1:]] == [[3, 3], [3]]
    worst = max(
        math.dist(a, b)
        for new_level, old_level in zip(reparsed.lod_levels[1:], original.lod_levels[1:])
        for new_part, old_part in zip(new_level, old_level)
        for a, b in zip(new_part.vertices, old_part.vertices, strict=True)
    )
    assert worst < 1e-4
    if mode != "add_vertex_outside_bounds":
        # Unchanged bounds keep every lower level byte for byte.
        old_blocks = _pamlod_level_blocks(source, 3, geometry)[1]
        for (old_offset, size), (new_offset, new_size) in zip(old_blocks[1:], stated[1][1:]):
            assert size == new_size
            assert rebuilt[new_offset:new_offset + size] == source[old_offset:old_offset + size]
    else:
        assert reparsed.lod_levels[0][0].vertices[-1][0] == pytest.approx(3.0, abs=1e-4)


def test_single_part_lod0_hide_keeps_lower_levels():
    source = shipped_pamlod(levels=((5,), (4,), (3,)))
    original = parse_pamlod(source, "object/stone.pamlod")
    edited = copy.deepcopy(original)
    edited.lod_levels[0][0].vertices = edited.lod_levels[0][0].vertices[:3]
    edited.lod_levels[0][0].uvs = edited.lod_levels[0][0].uvs[:3]
    edited.lod_levels[0][0].faces = [(0, 1, 2)]
    edited.submeshes = edited.lod_levels[0]
    reparsed = parse_pamlod(build_pamlod(edited, source), "object/stone.pamlod")
    assert [[len(part.vertices) for part in level] for level in reparsed.lod_levels] == [[3], [4], [3]]
