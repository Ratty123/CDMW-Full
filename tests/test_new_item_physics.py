"""Imported New Items must not inherit their template's render simulation."""

from dataclasses import replace
import struct
from unittest.mock import patch

import pytest

from cdmw.domain.new_item.spec import ModelSource
from cdmw.modding.pac_cloth import pac_cloth_lods
from cdmw.services.new_item_planning import ModelFiles
from cdmw.services.new_item_skinning import strip_template_material_physics, strip_template_vertex_physics
from tests.test_new_item_provenance import setup_game, spec
from tests.test_new_item_service import PAC, PAC_XML
from tests.test_pac_physics_lods import empty_lod_part_fixture


def test_motion_is_removed_at_every_lod_without_changing_skin_or_geometry():
    source = bytearray(empty_lod_part_fixture())
    levels = pac_cloth_lods(bytes(source))
    for level in levels:
        for index, part in enumerate(level.submeshes):
            for offset in part.source_vertex_offsets:
                source[offset + 39] |= 0xC0
                if index == 0:
                    # In an ordinary row the fifth/sixth slots are skeletal,
                    # not guide data. They must survive motion removal.
                    source[offset + 39] |= 63
                # Include foreign bits in both packed index groups.
                source[offset + 23] |= 0xC0
                source[offset + 27] |= 0xC0
    source = bytes(source)
    output = strip_template_vertex_physics(source)
    expected = bytearray(source)
    for level in levels:
        for part in level.submeshes:
            for offset in part.source_vertex_offsets:
                if source[offset + 39] & 63 != 63:
                    expected[offset + 12:offset + 16] = struct.pack("<2e", 0, 1)
                    group = struct.unpack_from("<I", source, offset + 24)[0]
                    struct.pack_into("<I", expected, offset + 24, group & 0xC00003FF)
                    expected[offset + 32:offset + 36] = bytes(4)
                expected[offset + 38] = (source[offset + 38] & 0xF0) | 15
                expected[offset + 39] = 255
    assert output == expected
    for before, after in zip(pac_cloth_lods(source), pac_cloth_lods(output), strict=True):
        for original, updated in zip(before.submeshes, after.submeshes, strict=True):
            assert updated.vertices == original.vertices
            assert updated.faces == original.faces
            assert updated.bone_indices == original.bone_indices
            assert updated.bone_weights == original.bone_weights
    assert strip_template_vertex_physics(output) == output


@pytest.mark.parametrize("encoding,bom", [("utf-8", b""), ("utf-16-le", b"\xff\xfe")])
def test_material_cleanup_preserves_shader_parameters_and_comments(encoding, bom):
    text = '<!-- _pbdSimulationMaterialName="Keep comment" -->\r\n<ModelPropertyList>'
    for index, profile in enumerate(("WeaponSpline", "Flail")):
        text += (f'<ModelProperty Index="{index}"><SkinnedMeshProperty _pbdSimulationMaterialName="{profile}" '
                 '_physicsFileName="template.hkx"><SkinnedMeshMaterial _jiggleWindWeight="0.4" '
                 '_materialName="SkinnedMeshEyeCover"><MaterialParameterByte4 _name="_eyeCoverDiffuseParameter" '
                 '_value="128"/></SkinnedMeshMaterial></SkinnedMeshProperty></ModelProperty>')
    text += '</ModelPropertyList>'
    source = bom + text.encode(encoding)
    expected = text.replace('="WeaponSpline"', '=""').replace('="Flail"', '=""')
    expected = expected.replace('="template.hkx"', '=""').replace('_jiggleWindWeight="0.4"', '_jiggleWindWeight="0"')
    output = strip_template_material_physics(source)
    assert output == bom + expected.encode(encoding)
    assert strip_template_material_physics(output) == output


@pytest.mark.parametrize("current", [False, True])
@pytest.mark.parametrize("keep", [False, True])
def test_plan_cleans_embedded_motion_and_companions_together(tmp_path, current, keep):
    service, snapshot, _ = setup_game(tmp_path, current=current)
    payload = empty_lod_part_fixture()
    material = b'<ModelPropertyList><SkinnedMeshProperty _pbdSimulationMaterialName="Flail"/></ModelPropertyList>'
    model = ModelFiles(payload, {PAC_XML: material})
    requested = replace(spec(), model_source=ModelSource.IMPORTED, keep_template_physics=keep)
    # The table fixture has no body skeleton. Its rig contract has separate tests;
    # run the actual plan/export composition with a complete multi-LOD PAC here.
    with patch("cdmw.services.new_item_variants.validate_variant_rig"):
        plan = service.plan(requested, snapshot, model=model)
    models = [data for path, data in plan.loose_files.items() if path.endswith('.pac')]
    materials = [data for path, data in plan.loose_files.items() if path.endswith('.pac_xml')]
    assert models == [payload if keep else strip_template_vertex_physics(payload)]
    assert materials == [material if keep else strip_template_material_physics(material)]
    assert bool([path for path in plan.new_paths if path.endswith('.hkx')]) is keep
    assert model.pac_data == payload and model.side_files[PAC_XML] == material
    assert snapshot.payload(PAC) != payload


def test_unsupported_import_cannot_silently_keep_unknown_motion():
    with pytest.raises(ValueError, match="original PAC"):
        strip_template_vertex_physics(b"invalid mesh")


def test_owned_template_copy_keeps_its_motion(tmp_path):
    from cdmw.core.archive_format import parse_archive_pamt
    from cdmw.services.new_item_service import NewItemService
    from tests.test_new_item_provenance import current_files
    from tests.test_new_item_service import build_package, _read
    from tests.test_new_item_variant_authoring import selections

    files = current_files()
    files[PAC] = empty_lod_part_fixture()
    files[PAC_XML] = b'<SkinnedMeshProperty _pbdSimulationMaterialName="Flail"/>'
    service = NewItemService()
    snapshot = service.build_snapshot(parse_archive_pamt(build_package(tmp_path / 'game', files)), read_entry=_read)
    selected = next(choice for choice in selections(snapshot) if choice.model_path == PAC)
    plan = service.plan(replace(spec(), variants=(selected,)), snapshot)
    assert [data for path, data in plan.loose_files.items() if path.endswith('.pac')] == [files[PAC]]
    assert [data for path, data in plan.loose_files.items() if path.endswith('.pac_xml')] == [files[PAC_XML]]
    assert any(path.endswith('.hkx') for path in plan.new_paths)
