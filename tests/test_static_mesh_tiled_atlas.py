"""Tiled import materials retain a runtime slot while other materials share an atlas."""
from copy import deepcopy

import pytest

from cdmw.modding.mesh_parser import SubMesh, parse_pac
from cdmw.modding.static_mesh_replacer import (
    StaticMeshReplacementOptions, StaticReplacementTransform, StaticSubmeshMapping,
    StaticTextureUvTransform, build_static_mesh_replacement, plan_static_output_draw_sections,
)
from tests.test_static_mesh_replacer_preview import _mesh, _minimal_pac_original, _minimal_two_part_pac_original


def _source():
    return _mesh("sword.gltf", [
        SubMesh(name=name, material=name,
                vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                faces=[(0, 1, 2)],
                uvs=[(-0.75 if name == "Handle" else 0.0, 0.0), (1.0, 0.0), (0.0, 1.0)])
        for name in ("Blade", "Handle", "Skull")
    ])


def _options(handle_group=(1, 2)):
    return StaticMeshReplacementOptions(
        transform=StaticReplacementTransform(alignment_mode="manual", scale_to_original_length=False),
        submesh_mappings=[StaticSubmeshMapping(0, "target0", [0], 0),
                          StaticSubmeshMapping(1, "target1", list(handle_group), 1)],
        complete_external_swap=True,
        texture_uv_transforms=[StaticTextureUvTransform("Handle", flip_v=True)],
    )


@pytest.mark.parametrize("handle_group", [(1, 2), (2, 1)])
def test_build_keeps_tiled_handle_uvs_and_atlases_other_materials(handle_group):
    original_data, original = _minimal_two_part_pac_original()
    source = _source()
    before = deepcopy(source)
    rebuilt, report = build_static_mesh_replacement(original_data, original, source, _options(handle_group))
    parsed = parse_pac(rebuilt, "rebuilt.pac")

    assert not report.errors
    assert len(parsed.submeshes) == len(original.submeshes)
    assert [part.name for part in parsed.submeshes] == [part.name for part in original.submeshes]
    handle = next(section for section in report.output_draw_sections if section.source_submesh_indices == [1])
    atlas = next(section for section in report.output_draw_sections if section.atlas_rects)
    assert set(atlas.atlas_source_material_names) == {"Blade", "Skull"}
    assert not handle.atlas_rects
    assert parsed.total_faces == source.total_faces
    for actual, (u, v) in zip(parsed.submeshes[handle.output_index].uvs, source.submeshes[1].uvs):
        assert actual == pytest.approx((u, 1.0 - v), abs=0.001)
    assert [part.uvs for part in source.submeshes] == [part.uvs for part in before.submeshes]


def test_tiling_created_by_uv_controls_also_gets_a_dedicated_slot():
    _, original = _minimal_two_part_pac_original()
    source = _source()
    source.submeshes[1].uvs[0] = (0.0, 0.0)
    options = _options()
    options.texture_uv_transforms = [StaticTextureUvTransform("Handle", scale_uv=(2.0, 1.0))]
    sections, _, errors = plan_static_output_draw_sections(original, source, options.submesh_mappings, options)
    assert not errors
    assert next(section for section in sections if 1 in section.source_submesh_indices).source_submesh_indices == [1]


def test_tiled_materials_fail_clearly_when_no_runtime_slot_can_be_reserved():
    data, original = _minimal_pac_original()
    options = _options()
    options.submesh_mappings = [StaticSubmeshMapping(0, "target", [0, 1, 2], 0)]
    with pytest.raises(ValueError, match="tiled.*material.*slot"):
        build_static_mesh_replacement(data, original, _source(), options)
