"""Plan validation distinguishes socket attachments from character skinning."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cdmw.services.new_item_variants import validate_variant_rig


MODEL = "character/model/1_pc/1_phm/weapon/1_onehandweapon/test.pac"
PREFAB = "character/bin__/prefab/1_pc/01_phm/weapon/01_onehandweapon/test_r.prefab"


def _pac(*, weighted_accessory=False, attachment_slot=0, extra_accessory=False):
    from tests.test_pac_skin_extra_influences import _record
    from tests.test_static_mesh_replacer_preview import _minimal_two_part_pac_original

    data, mesh = _minimal_two_part_pac_original()
    result = bytearray(data)
    for part_index, part in enumerate(mesh.submeshes):
        for vertex_index, offset in enumerate(part.source_vertex_offsets):
            weighted = weighted_accessory and part_index == 1 and vertex_index == 0
            record = _record(
                palette=(0, 43, 0, 0, 0, 0) if weighted else (attachment_slot, 0, 0, 0, 0, 0),
                weights=(128, 127, 0, 0, 0, 0, 40, 60) if weighted and extra_accessory
                else (128, 127, 0, 0, 0, 0, 0, 0) if weighted else (255, 0, 0, 0, 0, 0, 0, 0),
                extra=(20.0, 19.0) if weighted and extra_accessory else (0.0, 1.0),
                gate=0 if weighted and extra_accessory else 63,
            )
            for start, end in ((12, 16), (20, 36), (39, 40)):
                result[offset + start:offset + end] = record[start:end]
    return bytes(result)


def _snapshot(*, prefab_model=MODEL, attached="RHand_Socket", pivot="Basic_ChildSocket", extra_accessory=False):
    from tests.test_archive_relationships import ArchiveRelationshipTests

    prefab = ArchiveRelationshipTests()._minimal_prefab_profile_payload(
        attached=attached,
        pivot=pivot,
        part="CD_MainWeapon_Sword_R",
        model=prefab_model,
        socket_file="character/descriptors/socketbonedata/test.sockets.xml",
    )
    files = {MODEL: _pac(weighted_accessory=True, extra_accessory=extra_accessory), PREFAB: prefab}
    return SimpleNamespace(entries=files, payload=files.__getitem__)


def test_rigid_weapon_import_uses_its_exact_prefab_attachment():
    snapshot = _snapshot()
    assert validate_variant_rig(snapshot, MODEL, _pac(), prefab_path=PREFAB) == "rigid prefab attachment"


def test_unchanged_template_keeps_its_existing_binding_without_resolving_a_body_rig():
    snapshot = _snapshot()
    assert validate_variant_rig(snapshot, MODEL, snapshot.payload(MODEL)) == "unchanged template binding"


@pytest.mark.parametrize("profile", [
    {"prefab_model": MODEL.replace("test.pac", "another.pac")},
    {"attached": ""},
    {"pivot": ""},
])
def test_rigid_import_cannot_borrow_another_models_or_an_incomplete_attachment(profile):
    with pytest.raises(ValueError, match="skeleton is missing or ambiguous"):
        validate_variant_rig(_snapshot(**profile), MODEL, _pac(), prefab_path=PREFAB)


@pytest.mark.parametrize("imported", [_pac(attachment_slot=1), _pac(weighted_accessory=True, attachment_slot=1)])
def test_socket_attachment_does_not_approve_changed_skin_bindings(imported):
    with pytest.raises(ValueError, match="skeleton is missing or ambiguous"):
        validate_variant_rig(_snapshot(), MODEL, imported, prefab_path=PREFAB)


def test_rigid_import_still_requires_a_rig_when_no_exact_attachment_was_supplied():
    with pytest.raises(ValueError, match="skeleton is missing or ambiguous"):
        validate_variant_rig(_snapshot(), MODEL, _pac())


def test_rigid_template_still_rejects_a_different_attachment_slot():
    snapshot = _snapshot()
    snapshot.entries[MODEL] = _pac()
    with pytest.raises(ValueError, match="single attachment slot"):
        validate_variant_rig(snapshot, MODEL, _pac(attachment_slot=1), prefab_path=PREFAB)


@pytest.mark.parametrize("attachment_supplied", [False, True])
@pytest.mark.parametrize("source_part_count", [1, 2])
@pytest.mark.parametrize("extra_accessory", [False, True])
def test_static_import_build_does_not_inherit_a_socket_weapons_accessory_weights(
    attachment_supplied, source_part_count, extra_accessory,
):
    from cdmw.modding.mesh_parser import ParsedMesh, SubMesh, parse_pac
    from cdmw.modding.scene_import_result_ops import SceneImportResult
    from cdmw.modding.static_mesh_replacer import build_static_mesh_replacement
    from cdmw.ui.new_item.model_import import ModelImportSource, ModelPlacement, build_placed_import

    snapshot = _snapshot(extra_accessory=extra_accessory)
    original = snapshot.payload(MODEL)
    target = parse_pac(original, MODEL)
    source_parts = target.submeshes[:source_part_count]
    mesh = ParsedMesh(path="multi_part.obj", format="obj", total_vertices=sum(len(part.vertices) for part in source_parts), submeshes=[
        SubMesh(name=part.name, material=part.material, vertices=list(part.vertices),
                faces=list(part.faces), normals=list(part.normals), uvs=list(part.uvs))
        for part in source_parts
    ])
    source = ModelImportSource(Path(mesh.path), Path(mesh.path), SceneImportResult(mesh=mesh), None, None)

    def build(_entry, _path, **kwargs):
        payload, report = build_static_mesh_replacement(
            original, target, kwargs["scene_import_result"].mesh, kwargs["static_replacement_options"],
        )
        assert not report.errors
        return payload

    with patch("cdmw.services.preview_workflow_service.build_mesh_import_preview", build):
        payload = build_placed_import(
            SimpleNamespace(path=MODEL), source, ModelPlacement(),
            attachment_prefab_data=snapshot.payload(PREFAB) if attachment_supplied else b"",
        )
    assert not mesh.has_bones and all(not part.bone_weights for part in mesh.submeshes)
    assert snapshot.payload(MODEL) == original
    if attachment_supplied:
        assert validate_variant_rig(snapshot, MODEL, payload, prefab_path=PREFAB) == "rigid prefab attachment"
        rebuilt = parse_pac(payload, MODEL)
        assert rebuilt.total_vertices == mesh.total_vertices + 3 * (len(target.submeshes) - source_part_count)
        assert [part.faces for part in rebuilt.submeshes[:source_part_count]] == [part.faces for part in mesh.submeshes]
        assert all(len(part.vertices) == 3 and len(part.faces) == 1 for part in rebuilt.submeshes[source_part_count:])
    else:
        with pytest.raises(ValueError, match="skeleton is missing or ambiguous"):
            validate_variant_rig(snapshot, MODEL, payload, prefab_path=PREFAB)


@pytest.mark.parametrize("profile", [{"prefab_model":MODEL.replace("test.pac", "foreign.pac")}, {"attached":""}])
def test_static_import_does_not_claim_a_foreign_or_incomplete_attachment(profile):
    from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
    from cdmw.services.new_item_variants import bind_static_import_to_attachment

    mesh = ParsedMesh(submeshes=[SubMesh(vertices=[(0.0,0.0,0.0)])])
    assert bind_static_import_to_attachment(mesh, MODEL, _snapshot(**profile).payload(PREFAB)) is mesh


@pytest.mark.parametrize("skin", ["has_bones", "rows", "palette", "layout"])
def test_static_attachment_binding_preserves_authored_skin(skin):
    from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
    from cdmw.services.new_item_variants import bind_static_import_to_attachment

    part = SubMesh(vertices=[(0.0,0.0,0.0)])
    mesh = ParsedMesh(submeshes=[part], has_bones=skin=="has_bones")
    if skin == "rows":
        part.bone_indices, part.bone_weights = [(1,)], [(1.0,)]
    elif skin == "palette":
        part.source_bone_palette = (43,)
    elif skin == "layout":
        part.source_skin_weight_layout = "pac_slot_u10x6"
    assert bind_static_import_to_attachment(mesh, MODEL, _snapshot().payload(PREFAB)) is mesh
