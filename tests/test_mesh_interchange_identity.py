"""A Part Blender returns with split copies of a source vertex keeps its edits, or is refused by name."""
from __future__ import annotations

import copy
import math

import pytest

from cdmw.domain.mesh.operations import mesh_edit_operations_from_dicts
from cdmw.modding.mesh_importer import apply_operation_channels_to_original
from cdmw.modding.mesh_interchange_identity import (
    collapse_split_vertices,
    recover_returned_vertex_splits,
    require_returned_part_counts,
)
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh, parse_pac
from tests.test_mesh_pac_topology_serializer import _pac_fixture


def _unit(*values):
    length = math.hypot(*values)
    return tuple(value / length for value in values)


def _quad(name="shirt"):
    return SubMesh(
        name=name,
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0)],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)],
        normals=[(0.0, 0.0, 1.0)] * 4,
        faces=[(0, 1, 2), (1, 3, 2)],
        source_vertex_map=[0, 1, 2, 3],
        source_vertex_offsets=[0, 40, 80, 120],
    )


def _split(part, *, copy_normal, kept_normal=None):
    """Vertex 0 moved out of plane; Blender wrote source vertex 1 twice, once per face."""
    returned = copy.deepcopy(part)
    returned.vertices[0] = (0.0, 0.0, 0.1)
    returned.normals = [_unit(0.0, -0.1, 1.0), kept_normal or _unit(0.01, -0.05, 1.0),
                        _unit(0.0, -0.05, 1.0), (0.0, 0.0, 1.0), copy_normal]
    returned.vertices.append(returned.vertices[1])
    returned.uvs.append(returned.uvs[1])
    returned.source_vertex_map.append(1)
    returned.source_vertex_offsets.append(returned.source_vertex_offsets[1])
    returned.uv_sets = {0: list(returned.uvs)}
    returned.interchange_vertex_ids = [0, 1, 2, 3, 1]
    returned.faces = [(0, 1, 2), (4, 3, 2)]
    return returned


def test_copies_that_agree_with_each_other_merge_to_their_mean_normal():
    source = _quad()
    part = _split(source, copy_normal=_unit(0.012, -0.05, 1.0))
    assert collapse_split_vertices(part, source, source)
    assert part.vertices == [(0.0, 0.0, 0.1), *source.vertices[1:]]
    assert part.faces == source.faces
    assert part.source_vertex_map == [0, 1, 2, 3]
    assert part.interchange_vertex_ids == [0, 1, 2, 3]
    assert len(part.uv_sets[0]) == 4
    mean = _unit(*(a + b for a, b in zip(_unit(0.01, -0.05, 1.0), _unit(0.012, -0.05, 1.0))))
    assert part.normals[1] == pytest.approx(mean, abs=1e-9)


def test_a_copy_carrying_the_source_normal_keeps_it():
    source = _quad()
    part = _split(source, copy_normal=(0.0, 0.0, 1.0))
    assert collapse_split_vertices(part, source, source)
    assert part.normals[1] == (0.0, 0.0, 1.0)


def test_copies_further_apart_than_rounding_are_a_new_hard_edge():
    source = _quad()
    part = _split(source, copy_normal=_unit(0.0, -1.0, 1.0))
    with pytest.raises(ValueError, match=r"Part 'shirt': split vertex 1 has no matching source normal"):
        collapse_split_vertices(part, source, source)


def test_copies_with_different_extra_uvs_are_a_new_seam():
    source = _quad()
    part = _split(source, copy_normal=_unit(0.012, -0.05, 1.0))
    part.uv_sets[1] = [(0.0, 0.0)] * 4 + [(0.5, 0.5)]
    with pytest.raises(ValueError, match=r"Part 'shirt': split vertex 1 changes uv_sets 1"):
        collapse_split_vertices(part, source, source)


def _returned(original):
    returned = copy.deepcopy(original)
    returned._cdmw_imported_from_obj = True
    returned._cdmw_obj_sidecar_present = True
    returned._cdmw_sidecar_import_rules = {}
    returned._cdmw_edit_operations = []  # import names only Parts that kept their source count
    return returned


def test_recovered_return_keeps_its_edit_when_channels_reach_the_source():
    original = parse_pac(_pac_fixture(), "split.pac")
    returned = _returned(original)
    part = returned.submeshes[0]
    donor = original.submeshes[0]
    moved = (donor.vertices[0][0], donor.vertices[0][1], donor.vertices[0][2] + 0.1)
    for attr in ("vertices", "normals", "uvs", "bone_indices", "bone_weights", "source_vertex_offsets"):
        rows = list(getattr(donor, attr))
        if len(rows) == len(donor.vertices):
            setattr(part, attr, [*rows, rows[1]])
    part.vertices[0] = moved
    part.normals[-1] = tuple(value * 0.999 for value in donor.normals[1])
    part.tangents = []
    part.source_vertex_map = [0, 1, 2, 3, 1]
    part.faces = [(0, 1, 2), (4, 3, 2)]

    recovered = recover_returned_vertex_splits(returned, original)

    assert len(returned.submeshes[0].vertices) == 5, "the caller's mesh is not modified"
    operations = {op.operation for op in mesh_edit_operations_from_dicts(recovered._cdmw_edit_operations)}
    assert "replace_positions_same_count" in operations
    rebuilt = apply_operation_channels_to_original(original, recovered).submeshes[0]
    assert rebuilt.vertices[0] == moved
    assert rebuilt.vertices[1:] == donor.vertices[1:]
    assert rebuilt.faces == donor.faces


def test_part_that_lost_a_vertex_is_refused_by_name():
    original = parse_pac(_pac_fixture(), "split.pac")
    returned = _returned(original)
    returned.submeshes[0].vertices = returned.submeshes[0].vertices[:3]
    name = original.submeshes[0].name
    with pytest.raises(ValueError, match=rf"Part '{name}' came back with 3 vertices; the game mesh has 4"):
        recover_returned_vertex_splits(returned, original)
    with pytest.raises(ValueError, match=rf"Part '{name}' came back with 3 vertices"):
        require_returned_part_counts(returned, original)


def test_count_is_not_enforced_when_topology_may_change_or_mesh_is_no_return():
    original = parse_pac(_pac_fixture(), "split.pac")
    allowed = _returned(original)
    allowed.submeshes[0].vertices = allowed.submeshes[0].vertices[:3]
    allowed._cdmw_sidecar_import_rules = {"allow_topology_change": True}
    assert recover_returned_vertex_splits(allowed, original) is allowed
    require_returned_part_counts(allowed, original)
    internal = ParsedMesh(submeshes=[_quad()])
    internal.submeshes[0].vertices = internal.submeshes[0].vertices[:3]
    require_returned_part_counts(internal, ParsedMesh(submeshes=[_quad()]))
    unmatched = _returned(original)  # an empty companion matches no Part and replaces the mesh
    unmatched.submeshes[0].vertices = unmatched.submeshes[0].vertices[:3]
    unmatched.submeshes[0].source_vertex_map = []
    require_returned_part_counts(unmatched, original)
