"""Analytic guide transforms and stored-LOD bindings, without game assets."""

from dataclasses import replace
import math
import struct

import pytest

from cdmw.modding.pac_cloth import decode_pac_cloth_binding, pac_cloth_binding, pac_cloth_lods
from cdmw.modding.pac_cloth_guides import decode_pac_cloth_guides
from cdmw.modding.pac_cloth_skinning import (
    blend_render_cloth_matrix, inspect_render_cloth_bindings, prepare_guide_skinning_matrices,
)
from tests.test_pac_cloth_guides import guide_fixture
from tools.pac_cloth_guide_study import inspect_pac


IDENTITY = ((1., 0., 0., 0.), (0., 1., 0., 0.), (0., 0., 1., 0.), (0., 0., 0., 1.))


def frame(position=(0., 0., 0.), blend=1.):
    return ((1., 0., 0., blend), IDENTITY[1], IDENTITY[2], (*position, 1.))


def record(blend=0, indices=(0, 0, 0, 0), weights=(255, 0, 0, 0)):
    data = bytearray(40)
    struct.pack_into("<2e", data, 12, *indices[2:])
    struct.pack_into("<I", data, 24, 7 | indices[0] << 10 | indices[1] << 20)
    data[28] = 255
    data[32:36] = bytes(weights)
    data[39] = 0xC0 | blend  # High bits must not affect the branch or blend.
    return bytes(data)


def point(matrix, value):
    return tuple(sum(value[i] * matrix[i][j] for i in range(3)) + matrix[3][j] for j in range(3))


def test_preparation_uses_shader_rest_positions_and_preserves_metadata():
    guides = decode_pac_cloth_guides(guide_fixture()[0])
    rest = guides.vertices[0]
    assert guides.cpu_unskinned_vertices[0] != rest
    # The whole object turns 90 degrees about Z and moves by (7, 8, 9).
    animated = ((0., 1., 0., .25), (-1., 0., 0., .125), IDENTITY[2],
                (-rest[1] + 7, rest[0] + 8, rest[2] + 9, 1.))
    matrices = prepare_guide_skinning_matrices(guides, (animated,) * 3)
    assert matrices[0][:3] == animated[:3]
    assert matrices[0][3] == pytest.approx((7, 8, 9, 1 - rest[0] * .25 - rest[1] * .125))
    result = blend_render_cloth_matrix(record(), 0, skeletal_matrix=IDENTITY, guide_matrices=matrices)
    assert point(result, (2, 3, 4)) == pytest.approx((4, 10, 13))


def test_rotation_moves_a_render_point_about_its_guide():
    guides = replace(decode_pac_cloth_guides(guide_fixture()[0]), vertices=((2., 3., 5.),))
    animated = ((0., 1., 0., 1.), (-1., 0., 0., 0.), IDENTITY[2], (8., 12., 5., 1.))
    matrices = prepare_guide_skinning_matrices(guides, (animated,))
    result = blend_render_cloth_matrix(record(), 0, skeletal_matrix=IDENTITY, guide_matrices=matrices)
    assert point(result, (3, 3, 5)) == pytest.approx((8, 13, 5))
    # Adding just the guide displacement would incorrectly produce (9, 12, 5).
    assert point(result, guides.vertices[0]) == pytest.approx((8, 12, 5))


def test_render_weights_are_normalized_and_runtime_blend_is_weighted():
    matrices = (frame((4, 0, 0), 0), frame((0, 8, 0), 1),
                frame((0, 0, 12), .5), frame((16, 0, 0), .25))
    result = blend_render_cloth_matrix(record(42, (0, 1, 2, 3), (80, 60, 40, 20)), 0,
                                       skeletal_matrix=frame((10, 10, 10)), guide_matrices=matrices)
    # Guide translation = (3.2, 2.4, 2.4); effective skeletal fraction = 17/60.
    assert point(result, (1, 2, 3)) == pytest.approx((6.1266666667, 6.5533333333, 7.5533333333))


@pytest.mark.parametrize("weights", [(128, 126, 0, 0), (128, 128, 0, 0)])
def test_render_weight_rounding_does_not_scale_a_uniform_transform(weights):
    result = blend_render_cloth_matrix(record(0, weights=weights), 0,
                                       skeletal_matrix=IDENTITY, guide_matrices=(frame((4, 5, 6)),))
    assert point(result, (1, 2, 3)) == pytest.approx((5, 7, 9))


def test_runtime_zero_keeps_guide_transform_until_explicit_bypass():
    matrices = (frame((4, 5, 6), 0),)
    result = blend_render_cloth_matrix(record(62), 0, skeletal_matrix=frame((10, 20, 30)),
                                       guide_matrices=matrices)
    assert point(result, (1, 2, 3)) == pytest.approx((5, 7, 9))
    # The bypass branch must not read malformed guide indices or missing frames.
    data = bytearray(record(63))
    struct.pack_into("<e", data, 12, math.nan)
    result = blend_render_cloth_matrix(data, 0, skeletal_matrix=frame((10, 20, 30)), guide_matrices=())
    assert point(result, (1, 2, 3)) == pytest.approx((11, 22, 33))


def test_zero_weight_slots_still_require_valid_guide_indices():
    with pytest.raises(ValueError, match="outside"):
        blend_render_cloth_matrix(record(0, (0, 1, 2, 3)), 0,
                                  skeletal_matrix=IDENTITY, guide_matrices=(frame(),) * 3)


@pytest.mark.parametrize("fault", ["frame_count", "frame_shape", "frame_nan", "guide_nan", "skeletal_shape", "skeletal_inf"])
def test_unusable_inputs_are_rejected(fault):
    guides = decode_pac_cloth_guides(guide_fixture()[0])
    frames = (frame(),) * 3
    skeletal = IDENTITY
    data = record()
    if fault == "frame_count":
        frames = frames[:1]
    elif fault == "frame_shape":
        frames = (IDENTITY[:3],) * 3
    elif fault == "frame_nan":
        frames = (frame((math.nan, 0, 0)),) * 3
    elif fault == "guide_nan":
        guides = replace(guides, vertices=((math.nan, 0, 0),) * 3)
    elif fault == "skeletal_shape":
        skeletal = IDENTITY[:3]
    elif fault == "skeletal_inf":
        skeletal = frame((math.inf, 0, 0))
    with pytest.raises(ValueError):
        matrices = prepare_guide_skinning_matrices(guides, frames)
        blend_render_cloth_matrix(data, 0, skeletal_matrix=skeletal, guide_matrices=matrices)


def test_zero_guide_total_is_decodable_but_not_editable_or_a_usable_normal_basis():
    data = record(61, weights=(0, 0, 0, 0))
    assert decode_pac_cloth_binding(data, 0) == (61, (0, 0, 0, 0), (0, 0, 0, 0))
    with pytest.raises(ValueError, match="both skeletal and guide weights"):
        pac_cloth_binding(data, 0)
    result = blend_render_cloth_matrix(data, 0, skeletal_matrix=frame((10, 20, 30)),
                                       guide_matrices=(frame((4, 5, 6)),))
    assert result == ((0., 0., 0.),) * 4


def bound_fixture():
    data = bytearray(guide_fixture()[0])
    for mesh in pac_cloth_lods(data):
        for part in mesh.submeshes:
            for vertex, offset in enumerate(part.source_vertex_offsets):
                data[offset:offset + 40] = (record(21, (0, 1, 2, 2), (128, 127, 0, 0))
                                          if vertex == 0 else record(63))
    return bytes(data)


def test_inspector_follows_bindings_at_every_stored_lod_without_mutation():
    data = bound_fixture()
    before = bytes(data)
    report = inspect_pac(data)
    result = report["render_bindings"]
    assert report["status"] == result["status"] == "decoded"
    assert result["invalid_vertex_count"] == 0
    assert len(result["lods"]) == 4
    for lod, row in enumerate(result["lods"]):
        assert row["lod"] == lod
        part = row["parts"][0]
        assert (part["bound_vertex_count"], part["bypass_vertex_count"], part["invalid_vertex_count"]) == (1, 2, 0)
        assert part["fetched_guide_indices"] == [0, 1, 2]
        assert part["weighted_guide_indices"] == [0, 1]
        assert part["guide_weight_sums"] == [255]
        assert part["skeletal_blend_values"] == [21]
    assert data == before


def test_inspector_reports_bad_lower_lod_zero_weight_index_with_source_offset():
    data = bytearray(bound_fixture())
    offset = pac_cloth_lods(data)[3].submeshes[0].source_vertex_offsets[0]
    struct.pack_into("<e", data, offset + 14, 3)
    report = inspect_pac(data)
    assert report["status"] == "decoded"  # Guide decoding still succeeded.
    result = report["render_bindings"]
    assert result["status"] == "invalid_bindings"
    assert result["invalid_vertex_count"] == 1
    bad = result["lods"][3]["parts"][0]
    assert bad["bound_vertex_count"] == 0
    assert bad["invalid_examples"][0]["source_offset"] == offset
    assert "zero-weight" in bad["invalid_examples"][0]["reason"]


@pytest.mark.parametrize("channel", ["guide", "skeletal"])
def test_inspector_retains_zero_totals_without_relaxing_editing(channel):
    data = bytearray(bound_fixture())
    offset = pac_cloth_lods(data)[0].submeshes[0].source_vertex_offsets[0]
    start = offset + (32 if channel == "guide" else 28)
    data[start:start + 4] = bytes(4)
    result = inspect_pac(data)["render_bindings"]
    assert result["status"] == "decoded"
    part = result["lods"][0]["parts"][0]
    assert part[f"zero_{channel}_weight_vertex_count"] == 1
    assert part["bound_vertex_count"] == 1
    assert part["invalid_vertex_count"] == 0
    with pytest.raises(ValueError, match="both skeletal and guide weights"):
        pac_cloth_binding(data, offset)


def test_inspector_keeps_unreadable_render_layout_separate_from_decoded_guides():
    data = bound_fixture()
    guides = decode_pac_cloth_guides(data)
    result = inspect_render_cloth_bindings(data[:-40], guides)
    assert result["status"] == "unavailable"
    assert result["reason"]
