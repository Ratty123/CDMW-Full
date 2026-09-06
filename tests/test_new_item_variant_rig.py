"""Plan validation distinguishes socket attachments from character skinning."""

from types import SimpleNamespace

import pytest

from cdmw.services.new_item_variants import validate_variant_rig


MODEL = "character/model/1_pc/1_phm/weapon/1_onehandweapon/test.pac"
PREFAB = "character/bin__/prefab/1_pc/01_phm/weapon/01_onehandweapon/test_r.prefab"


def _pac(*, weighted_accessory=False, attachment_slot=0):
    from tests.test_pac_skin_extra_influences import _record
    from tests.test_static_mesh_replacer_preview import _minimal_two_part_pac_original

    data, mesh = _minimal_two_part_pac_original()
    result = bytearray(data)
    for part_index, part in enumerate(mesh.submeshes):
        for vertex_index, offset in enumerate(part.source_vertex_offsets):
            weighted = weighted_accessory and part_index == 1 and vertex_index == 0
            record = _record(
                palette=(0, 43, 0, 0, 0, 0) if weighted else (attachment_slot, 0, 0, 0, 0, 0),
                weights=(128, 127, 0, 0, 0, 0, 0, 0) if weighted else (255, 0, 0, 0, 0, 0, 0, 0),
            )
            for start, end in ((12, 16), (20, 36), (39, 40)):
                result[offset + start:offset + end] = record[start:end]
    return bytes(result)


def _snapshot(*, prefab_model=MODEL, attached="RHand_Socket", pivot="Basic_ChildSocket"):
    from tests.test_archive_relationships import ArchiveRelationshipTests

    prefab = ArchiveRelationshipTests()._minimal_prefab_profile_payload(
        attached=attached,
        pivot=pivot,
        part="CD_MainWeapon_Sword_R",
        model=prefab_model,
        socket_file="character/descriptors/socketbonedata/test.sockets.xml",
    )
    files = {MODEL: _pac(weighted_accessory=True), PREFAB: prefab}
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
