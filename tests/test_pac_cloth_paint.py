"""Painted cloth binds imported vertices to the template's existing guides."""

import pytest

from cdmw.modding.mesh_parser import _decode_pac_skin_influences
from cdmw.modding.pac_cloth import decode_pac_cloth_binding, pac_cloth_lods
from cdmw.modding.pac_cloth_guide_builder import create_pac_cloth_guides
from cdmw.modding.pac_cloth_guides import decode_pac_cloth_guides
from cdmw.modding.pac_cloth_paint import ClothPaintSamples, apply_pac_cloth_paint, blend_for_paint
from tests.test_pac_cloth_guide_builder import guide_free_pac, rule


def cloth_template(lods=3):
    """Part 0 carries guides (the template's cloth); part 1 is skeleton only."""
    return create_pac_cloth_guides(guide_free_pac(lods=lods, parts=2), {0: rule()})


def samples(part, value):
    return ClothPaintSamples(tuple(tuple(v) for v in part.vertices), (float(value),) * len(part.vertices))


def test_blend_byte_follows_paint():
    assert [blend_for_paint(v) for v in (0, .5, 1)] == [63, 32, 0]


@pytest.mark.parametrize("lods", [2, 3, 4])
def test_painted_part_binds_to_template_guides_at_every_lod_and_unpainted_part_follows_bones(lods):
    data = cloth_template(lods)
    before = pac_cloth_lods(data)
    guides = decode_pac_cloth_guides(data)
    result, report = apply_pac_cloth_paint(data, {1: samples(before[0].submeshes[1], 1.0)})
    assert len(result) == len(data)
    assert decode_pac_cloth_guides(result) == guides  # guide mesh, constraints and pins untouched
    assert report.guide_count == len(guides.vertices) and report.reduced_vertices == 0
    for level in before:
        cloth_part, painted = level.submeshes
        for offset in painted.source_vertex_offsets:
            blend, ids, weights = decode_pac_cloth_binding(result, offset)
            assert blend == 0 and sum(weights) == 255 and max(ids) < len(guides.vertices)
            # Skeletal slots survive the switch to cloth mode.
            assert result[offset + 28:offset + 30] == bytes((128, 127))
            assert result[offset:offset + 12] == data[offset:offset + 12]
            assert result[offset + 36:offset + 39] == data[offset + 36:offset + 39]
        for offset in cloth_part.source_vertex_offsets:
            # The template's own cloth part was not painted: it now follows the skeleton.
            assert decode_pac_cloth_binding(result, offset) is None
            assert result[offset + 28:offset + 30] == bytes((128, 127))
    assert report.cloth_vertices == sum(len(level.submeshes[1].vertices) for level in before)


def test_half_paint_blends_bones_and_cloth():
    data = cloth_template()
    part = pac_cloth_lods(data)[0].submeshes[1]
    result, _report = apply_pac_cloth_paint(data, {1: samples(part, .5)})
    for offset in part.source_vertex_offsets:
        assert decode_pac_cloth_binding(result, offset)[0] == 32


def test_already_skeletal_vertex_left_skeletal_is_byte_identical():
    data = cloth_template()
    levels = pac_cloth_lods(data)
    result, report = apply_pac_cloth_paint(data, {0: samples(levels[0].submeshes[0], 1.0),
                                                  1: samples(levels[0].submeshes[1], 0.0)})
    for level in levels:
        for offset in level.submeshes[1].source_vertex_offsets:
            assert result[offset:offset + 40] == data[offset:offset + 40]
    assert report.rigid_vertices == sum(len(level.submeshes[1].vertices) for level in levels)


def test_switching_a_cloth_vertex_back_to_bones_keeps_its_skin():
    data = cloth_template()
    levels = pac_cloth_lods(data)
    result, _report = apply_pac_cloth_paint(data, {1: samples(levels[0].submeshes[1], 1.0)})
    for offset in levels[0].submeshes[0].source_vertex_offsets:
        assert _decode_pac_skin_influences(result, offset) == _decode_pac_skin_influences(data, offset)


def test_paint_that_does_not_line_up_is_refused():
    data = cloth_template()
    part = pac_cloth_lods(data)[0].submeshes[1]
    shifted = ClothPaintSamples(tuple((x + 5, y, z) for x, y, z in part.vertices), (1.0,) * len(part.vertices))
    with pytest.raises(ValueError, match="does not line up with the built model"):
        apply_pac_cloth_paint(data, {1: shifted}, max_sample_distance=.01)


def test_template_without_cloth_and_empty_paint_are_refused():
    plain = guide_free_pac(parts=2)
    part = pac_cloth_lods(plain)[0].submeshes[1]
    with pytest.raises(ValueError, match="no cloth guides"):
        apply_pac_cloth_paint(plain, {1: samples(part, 1.0)})
    data = cloth_template()
    with pytest.raises(ValueError, match="Paint at least one area"):
        apply_pac_cloth_paint(data, {1: samples(pac_cloth_lods(data)[0].submeshes[1], 0.0)})


def test_paint_values_are_validated():
    with pytest.raises(ValueError, match="between 0 and 1"):
        ClothPaintSamples(((0., 0., 0.),), (1.5,))
    with pytest.raises(ValueError, match="one value per painted point"):
        ClothPaintSamples(((0., 0., 0.),), ())
