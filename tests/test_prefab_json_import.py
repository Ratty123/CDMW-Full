from __future__ import annotations

import inspect
import json

import pytest

from cdmw.core.archive_loose_export import export_archive_payloads_to_mod_ready_loose
from cdmw.core.archive_patching import ArchivePatchRequest
from cdmw.core.prefab_json import (
    PREFAB_EDIT_JSON_FORMAT,
    PrefabEditJsonError,
    apply_prefab_edit_document,
    apply_prefab_edit_json,
    build_prefab_edit_document,
    dumps_prefab_edit_json,
    rebuild_prefab_no_edit_from_edit_document,
)
from cdmw.core.crimson_formats import decode_prefab
from cdmw.models import ArchiveEntry, ModPackageInfo


def _lp(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return len(encoded).to_bytes(4, "little") + encoded


def _prefab_decl(name: str, declared_type: str, descriptor: bytes) -> bytes:
    return (
        len(name).to_bytes(4, "little")
        + name.encode("ascii")
        + len(declared_type).to_bytes(4, "little")
        + declared_type.encode("ascii")
        + descriptor
    )


def _prefab_ascii(value: str) -> bytes:
    encoded = value.encode("ascii")
    return len(encoded).to_bytes(4, "little") + encoded


def _prefab_profile_payload(
    *,
    attached: str = "Spine2_B_Socket",
    pivot: str = "Spine2_B_ChildSocket",
    part: str = "CD_TwoHandWeapon_Sword",
) -> bytes:
    string_descriptor = b"\x01\x00\x01\x00\x10\x00\x00\x00"
    bool_descriptor = b"\x00\x00\x01\x00\x00\x00\x00\x00"
    declarations = b"".join(
        (
            _prefab_decl("_attachedSocketName", "IndexedStringA", string_descriptor),
            _prefab_decl("_pivotSocketName", "IndexedStringA", string_descriptor),
            _prefab_decl("_applyPosition", "bool", bool_descriptor),
        )
    )
    return (
        b"\xff\xff\x04\x00"
        + declarations
        + b"\x00" * 32
        + _prefab_ascii(attached)
        + _prefab_ascii(pivot)
        + b"\x00\x01\x00\x00"
        + _prefab_ascii(part)
        + b"\x01\x01\x00\x01"
        + _prefab_ascii("character/model/1_pc/1_phm/weapon/2_twohandweapon/test.pac")
        + b"\x52\x00\x00\x00"
        + _prefab_ascii("character/descriptors/socketbonedata/1_pc/1_phm/weapon/2_twohandweapon/test.sockets.xml")
        + b"\x01\x01\x00\x00"
    )


def test_prefab_edit_json_no_edit_roundtrip_is_byte_identical() -> None:
    payload = b"\xff\xff\x04\x00" + _lp("ResourceReferencePath_SkinnedMesh") + _lp("character/model/test_a.pac")

    document = build_prefab_edit_document(payload, "character/prefab/test.prefab")
    patched = apply_prefab_edit_document(payload, document, virtual_path="character/prefab/test.prefab")

    assert document["format"] == PREFAB_EDIT_JSON_FORMAT
    assert document["policy"]["edit_mode"] == "same_length_resource_companion_and_placement_fields_only"
    assert document["policy"]["resizing_supported"] is False
    assert document["policy"]["length_changing_rebuild_supported"] is False
    assert document["policy"]["resize_readiness"]["length_changing_import_ready"] is False
    assert document["policy"]["resize_readiness"]["editable_row_count"] == 1
    assert document["policy"]["resize_readiness"]["affected_offset_candidate_rows"] == 0
    assert document["policy"]["layout_no_edit_rebuild_proven"] is True
    assert document["policy"]["same_length_resource_reference_edits"] is True
    assert document["policy"]["transform_value_editing_supported"] is False
    assert document["policy"]["array_resizing_supported"] is False
    assert document["structure"]["header"]["magic"] == 0xFFFF
    assert document["structure"]["header"]["version"] == 4
    assert document["structure"]["header"]["first_string_offset"] == 4
    assert document["structure"]["layout"]["fully_accounted"] is True
    assert document["structure"]["layout"]["accounted_byte_count"] == len(payload)
    assert document["structure"]["layout"]["spans"][0]["start"] == 0
    assert document["editable"]["resource_references"][0]["value"] == "character/model/test_a.pac"
    assert document["editable"]["resource_references"][0]["resize_impact"]["length_change_supported"] is False
    assert document["editable"]["resource_references"][0]["resize_impact"]["length_change_plan"] == {
        "enabled": False,
        "kind": "tail_length_prefix_only",
        "tail_only": True,
        "downstream_byte_count": 0,
        "affected_offset_candidate_count": 0,
    }
    assert rebuild_prefab_no_edit_from_edit_document(payload, document, virtual_path="character/prefab/test.prefab") == payload
    assert patched == payload


def test_prefab_edit_json_applies_same_length_resource_path_patch() -> None:
    old_path = "character/model/test_a.pac"
    new_path = "character/model/test_b.pac"
    payload = b"\xff\xff\x04\x00" + _lp(old_path)
    document = build_prefab_edit_document(payload, "character/prefab/test.prefab")
    document["editable"]["resource_references"][0]["value"] = new_path

    patched = apply_prefab_edit_document(payload, document, virtual_path="character/prefab/test.prefab")

    assert len(patched) == len(payload)
    assert new_path.encode("utf-8") in patched
    assert old_path.encode("utf-8") not in patched


def test_prefab_edit_json_excludes_overlapping_recovered_resource_reference() -> None:
    nested_path = "object/texture/cd_common_decals_mud_15_grass_dec.dds"
    payload = b"\xff\xff\x04\x00" + _lp("4") + b"\x00\x00\x00" + nested_path.encode("ascii")

    assert any(reference.text == nested_path for reference in decode_prefab(payload).references)

    document = build_prefab_edit_document(payload, "character/prefab/test.prefab")
    patched = apply_prefab_edit_document(payload, document, virtual_path="character/prefab/test.prefab")

    assert document["editable"]["resource_references"] == []
    assert document["policy"]["same_length_resource_reference_edits"] is False
    assert patched == payload


def test_prefab_edit_json_applies_same_length_companion_metadata_patch() -> None:
    old_path = "character/descriptors/socketbonedata/test_a.sockets.xml"
    new_path = "character/descriptors/socketbonedata/test_b.sockets.xml"
    payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac") + _lp(old_path)
    document = build_prefab_edit_document(payload, "character/prefab/test.prefab")
    rows = document["editable"]["resource_references"]
    rows_by_role = {row["role"]: row for row in rows}
    rows_by_role["companion_metadata"]["value"] = new_path

    patched = apply_prefab_edit_document(payload, document, virtual_path="character/prefab/test.prefab")

    assert len(patched) == len(payload)
    assert new_path.encode("utf-8") in patched
    assert old_path.encode("utf-8") not in patched


def test_prefab_edit_json_applies_same_length_placement_field_patch() -> None:
    payload = _prefab_profile_payload()
    document = build_prefab_edit_document(payload, "character/prefab/test.prefab")
    fields = {row["field_name"]: row for row in document["editable"]["placement_fields"]}
    assert set(fields) == {"_attachedSocketName", "_pivotSocketName", "_partName"}
    fields["_attachedSocketName"]["value"] = "Pelvis_L_Socket"
    fields["_pivotSocketName"]["value"] = "Pelvis_L_ChildSocket"

    patched = apply_prefab_edit_document(payload, document, virtual_path="character/prefab/test.prefab")

    assert len(patched) == len(payload)
    assert b"Pelvis_L_Socket" in patched
    assert b"Pelvis_L_ChildSocket" in patched
    assert b"Spine2_B_Socket" not in patched


def test_prefab_edit_json_text_applies_same_length_placement_field_patch() -> None:
    payload = _prefab_profile_payload()
    document = build_prefab_edit_document(payload, "character/prefab/test.prefab")
    document["editable"]["placement_fields"][0]["value"] = "Pelvis_L_Socket"

    patched = apply_prefab_edit_json(payload, json.dumps(document), virtual_path="character/prefab/test.prefab")

    assert len(patched) == len(payload)
    assert b"Pelvis_L_Socket" in patched
    assert b"Spine2_B_Socket" not in patched


def test_prefab_edit_json_rejects_length_changing_patch() -> None:
    payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")
    document = build_prefab_edit_document(payload)
    document["editable"]["resource_references"][0]["value"] = "character/model/much_longer_name.pac"

    with pytest.raises(PrefabEditJsonError, match="same byte length.*count/padding rebuild"):
        apply_prefab_edit_document(payload, document)


def test_prefab_edit_json_text_rejects_length_changing_patch_by_default() -> None:
    payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")
    document = build_prefab_edit_document(payload)
    document["editable"]["resource_references"][0]["value"] = "character/model/much_longer_name.pac"

    with pytest.raises(PrefabEditJsonError, match="same byte length.*count/padding rebuild"):
        apply_prefab_edit_json(payload, json.dumps(document))


def test_prefab_edit_json_text_rejects_length_changing_placement_patch() -> None:
    payload = _prefab_profile_payload()
    document = build_prefab_edit_document(payload)
    document["editable"]["placement_fields"][0]["value"] = "RHand_Socket"

    with pytest.raises(PrefabEditJsonError, match="placement replacement must keep the same byte length"):
        apply_prefab_edit_json(payload, json.dumps(document))


def test_prefab_edit_json_text_api_does_not_expose_experimental_resize_flag() -> None:
    assert "allow_experimental_length_change" not in inspect.signature(apply_prefab_edit_json).parameters


def test_prefab_edit_json_length_change_needs_a_readable_prefab() -> None:
    """Length-changing edits go through the exact pointer-relocation path now.

    They used to go through the offset-candidate scanner in crimson_formats,
    which finds pointers by looking for u32s that happen to equal a known
    string offset and rewrites any coincidental match. The exact rewriter
    reproduces the game's own output on 10,124 of 10,124 length-changing
    prefabs in the archives, but it needs a prefab that decodes all the way
    through -- and this fixture is a hand-assembled header with no real type
    table, so the edit is refused. The old path would have rewritten it.
    """
    prefix = b"\xff\xff\x04\x00" + _lp("_target") + _lp("IndexedStringA")
    old_path = "character/model/test_a.pac"
    new_path = "character/model/much_longer_name.pac"
    target_offset = len(prefix) + 4
    payload = prefix + target_offset.to_bytes(4, "little") + _lp(old_path)
    document = build_prefab_edit_document(payload, "character/prefab/test.prefab")
    document["editable"]["resource_references"][0]["value"] = new_path

    with pytest.raises(PrefabEditJsonError) as caught:
        apply_prefab_edit_document(
            payload,
            document,
            virtual_path="character/prefab/test.prefab",
            allow_experimental_length_change=True,
        )
    assert "read all the way through" in str(caught.value)

    # Same-length edits are unaffected: they move nothing and need no structure.
    same_length = old_path[:-5] + "z" + old_path[-4:]
    assert len(same_length) == len(old_path)
    document["editable"]["resource_references"][0]["value"] = same_length
    patched = apply_prefab_edit_document(
        payload, document, virtual_path="character/prefab/test.prefab"
    )
    assert len(patched) == len(payload)
    assert same_length.encode("utf-8") in patched


def test_prefab_edit_json_rejects_stale_resource_resize_impact() -> None:
    prefix = b"\xff\xff\x04\x00" + _lp("_target") + _lp("IndexedStringA")
    target_offset = len(prefix) + 4
    payload = prefix + target_offset.to_bytes(4, "little") + _lp("character/model/test_a.pac")
    document = build_prefab_edit_document(payload)
    impact = document["editable"]["resource_references"][0]["resize_impact"]
    assert impact["affected_offset_candidate_count"] >= 0
    impact["affected_offset_candidate_count"] = 999

    with pytest.raises(PrefabEditJsonError, match="resize impact"):
        apply_prefab_edit_document(payload, document)


def test_prefab_edit_json_rejects_stale_length_change_plan() -> None:
    payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")
    document = build_prefab_edit_document(payload)
    document["editable"]["resource_references"][0]["resize_impact"]["length_change_plan"]["tail_only"] = False

    with pytest.raises(PrefabEditJsonError, match="resize impact"):
        apply_prefab_edit_document(payload, document)


def test_prefab_edit_json_rejects_invalid_replacement_path() -> None:
    payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")
    document = build_prefab_edit_document(payload)
    document["editable"]["resource_references"][0]["value"] = "character/model/../abc.pac"

    with pytest.raises(PrefabEditJsonError, match="path is invalid"):
        apply_prefab_edit_document(payload, document)


def test_prefab_edit_json_rejects_replacement_extension_change() -> None:
    payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")
    document = build_prefab_edit_document(payload)
    document["editable"]["resource_references"][0]["value"] = "character/model/test_a.dds"

    with pytest.raises(PrefabEditJsonError, match="same extension"):
        apply_prefab_edit_document(payload, document)


def test_prefab_edit_json_rejects_length_changing_placement_field_patch() -> None:
    payload = _prefab_profile_payload()
    document = build_prefab_edit_document(payload)
    document["editable"]["placement_fields"][0]["value"] = "RHand_Socket"

    with pytest.raises(PrefabEditJsonError, match="placement replacement must keep the same byte length.*offset candidate"):
        apply_prefab_edit_document(payload, document)


def test_prefab_edit_json_experimental_resize_does_not_enable_placement_resize() -> None:
    payload = _prefab_profile_payload()
    document = build_prefab_edit_document(payload)
    document["editable"]["placement_fields"][0]["value"] = "RHand_Socket"

    with pytest.raises(PrefabEditJsonError, match="placement replacement must keep the same byte length"):
        apply_prefab_edit_document(payload, document, allow_experimental_length_change=True)


def test_prefab_edit_json_rejects_stale_placement_resize_impact() -> None:
    payload = _prefab_profile_payload()
    document = build_prefab_edit_document(payload)
    document["editable"]["placement_fields"][0]["resize_impact"]["reason"] = "stale"

    with pytest.raises(PrefabEditJsonError, match="resize impact"):
        apply_prefab_edit_document(payload, document)


def test_prefab_edit_json_rejects_stale_source_hash() -> None:
    payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")
    document = build_prefab_edit_document(payload)
    stale_payload = payload.replace(b"test_a", b"test_b")

    with pytest.raises(PrefabEditJsonError, match="SHA-256"):
        apply_prefab_edit_document(stale_payload, document)


def test_prefab_edit_json_text_rejects_stale_source_hash() -> None:
    payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")
    document = build_prefab_edit_document(payload)
    stale_payload = payload.replace(b"test_a", b"test_b")

    with pytest.raises(PrefabEditJsonError, match="SHA-256"):
        apply_prefab_edit_json(stale_payload, json.dumps(document))


def test_prefab_edit_json_text_rejects_source_byte_length_mismatch() -> None:
    payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")
    document = build_prefab_edit_document(payload)

    with pytest.raises(PrefabEditJsonError, match="byte length"):
        apply_prefab_edit_json(payload + b"\x00", json.dumps(document))


def test_prefab_edit_json_text_rejects_source_path_mismatch() -> None:
    payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")
    document = build_prefab_edit_document(payload, "character/prefab/source.prefab")

    with pytest.raises(PrefabEditJsonError, match="source path"):
        apply_prefab_edit_json(payload, json.dumps(document), virtual_path="character/prefab/selected.prefab")


def test_prefab_edit_json_rejects_diagnostic_decode_json_shape() -> None:
    payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")

    with pytest.raises(PrefabEditJsonError, match="cdmw.prefab.edit.v1"):
        apply_prefab_edit_document(payload, {"editing": {"supported": False}})


def test_prefab_edit_json_text_rejects_diagnostic_decode_json_shape() -> None:
    payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")

    with pytest.raises(PrefabEditJsonError, match="cdmw.prefab.edit.v1"):
        apply_prefab_edit_json(payload, json.dumps({"editing": {"supported": False}}))


def test_prefab_edit_json_rejects_unsupported_document_fields() -> None:
    payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")
    document = build_prefab_edit_document(payload)
    document["surprise"] = True

    with pytest.raises(PrefabEditJsonError, match="unsupported field"):
        apply_prefab_edit_document(payload, document)


def test_prefab_edit_json_text_rejects_unsupported_document_fields() -> None:
    payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")
    document = build_prefab_edit_document(payload)
    document["surprise"] = True

    with pytest.raises(PrefabEditJsonError, match="unsupported field"):
        apply_prefab_edit_json(payload, json.dumps(document))


def test_prefab_edit_json_rejects_unsupported_transform_edit_surface() -> None:
    payload = _prefab_profile_payload()
    document = build_prefab_edit_document(payload)
    document["editable"]["transform_fields"] = []

    with pytest.raises(PrefabEditJsonError, match="unsupported field"):
        apply_prefab_edit_document(payload, document)


def test_prefab_edit_json_rejects_unsupported_array_edit_surface() -> None:
    payload = _prefab_profile_payload()
    document = build_prefab_edit_document(payload)
    document["editable"]["array_fields"] = []

    with pytest.raises(PrefabEditJsonError, match="unsupported field"):
        apply_prefab_edit_document(payload, document)


def test_prefab_edit_json_rejects_unsupported_descriptor_word_edit_surface() -> None:
    payload = _prefab_profile_payload()
    document = build_prefab_edit_document(payload)
    document["editable"]["descriptor_words"] = []

    with pytest.raises(PrefabEditJsonError, match="unsupported field"):
        apply_prefab_edit_document(payload, document)


def test_prefab_edit_json_rejects_unsupported_unknown_block_edit_surface() -> None:
    payload = _prefab_profile_payload()
    document = build_prefab_edit_document(payload)
    document["editable"]["unknown_blocks"] = []

    with pytest.raises(PrefabEditJsonError, match="unsupported field"):
        apply_prefab_edit_document(payload, document)


@pytest.mark.parametrize("surface", ("transform_fields", "array_fields", "descriptor_words", "unknown_blocks"))
def test_prefab_edit_json_text_rejects_unsupported_edit_surfaces(surface: str) -> None:
    payload = _prefab_profile_payload()
    document = build_prefab_edit_document(payload)
    document["editable"][surface] = []

    with pytest.raises(PrefabEditJsonError, match="unsupported field"):
        apply_prefab_edit_json(payload, json.dumps(document))


def test_prefab_edit_json_no_edit_rebuild_rejects_unsupported_edit_surface() -> None:
    payload = _prefab_profile_payload()
    document = build_prefab_edit_document(payload)
    document["editable"]["unknown_blocks"] = []

    with pytest.raises(PrefabEditJsonError, match="unsupported field"):
        rebuild_prefab_no_edit_from_edit_document(payload, document)


def test_prefab_edit_json_no_edit_rebuild_rejects_edit_value_changes() -> None:
    old_path = "character/model/test_a.pac"
    new_path = "character/model/test_b.pac"
    payload = b"\xff\xff\x04\x00" + _lp(old_path)
    document = build_prefab_edit_document(payload)
    document["editable"]["resource_references"][0]["value"] = new_path

    with pytest.raises(PrefabEditJsonError, match="no-edit rebuild cannot contain editable value changes"):
        rebuild_prefab_no_edit_from_edit_document(payload, document)


def test_prefab_edit_json_no_edit_rebuild_rejects_placement_value_changes() -> None:
    payload = _prefab_profile_payload()
    document = build_prefab_edit_document(payload)
    document["editable"]["placement_fields"][0]["value"] = "Pelvis_L_Socket"

    with pytest.raises(PrefabEditJsonError, match="no-edit rebuild cannot contain editable value changes"):
        rebuild_prefab_no_edit_from_edit_document(payload, document)


def test_prefab_edit_json_no_edit_rebuild_rejects_length_changing_ready_policy_claim() -> None:
    payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")
    document = build_prefab_edit_document(payload)
    document["policy"]["resize_readiness"]["length_changing_import_ready"] = True

    with pytest.raises(PrefabEditJsonError, match="policy evidence"):
        rebuild_prefab_no_edit_from_edit_document(payload, document)


def test_prefab_edit_json_rejects_resizing_policy_claim() -> None:
    payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")
    document = build_prefab_edit_document(payload)
    document["policy"]["resizing_supported"] = True

    with pytest.raises(PrefabEditJsonError, match="resizing is not supported"):
        apply_prefab_edit_document(payload, document)


def test_prefab_edit_json_rejects_length_changing_rebuild_policy_claim() -> None:
    payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")
    document = build_prefab_edit_document(payload)
    document["policy"]["length_changing_rebuild_supported"] = True

    with pytest.raises(PrefabEditJsonError, match="length-changing rebuild is not supported"):
        apply_prefab_edit_document(payload, document, allow_experimental_length_change=True)


def test_prefab_edit_json_rejects_stale_policy_evidence() -> None:
    payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")
    document = build_prefab_edit_document(payload)
    document["policy"]["same_length_resource_reference_edits"] = False

    with pytest.raises(PrefabEditJsonError, match="policy evidence"):
        apply_prefab_edit_document(payload, document)


def test_prefab_edit_json_rejects_stale_placement_policy_evidence() -> None:
    payload = _prefab_profile_payload()
    document = build_prefab_edit_document(payload)
    document["policy"]["same_length_placement_field_edits"] = False

    with pytest.raises(PrefabEditJsonError, match="policy evidence"):
        apply_prefab_edit_document(payload, document)


def test_prefab_edit_json_rejects_stale_resize_readiness_policy() -> None:
    payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")
    document = build_prefab_edit_document(payload)
    document["policy"]["resize_readiness"]["affected_offset_candidate_rows"] = 999

    with pytest.raises(PrefabEditJsonError, match="policy evidence"):
        apply_prefab_edit_document(payload, document)


def test_prefab_edit_json_rejects_stale_resize_readiness_reason() -> None:
    payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")
    document = build_prefab_edit_document(payload)
    document["policy"]["resize_readiness"]["reason"] = "Length-changing import is ready."

    with pytest.raises(PrefabEditJsonError, match="policy evidence"):
        apply_prefab_edit_document(payload, document, allow_experimental_length_change=True)


def test_prefab_edit_json_rejects_resize_readiness_ready_claim() -> None:
    payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")
    document = build_prefab_edit_document(payload)
    document["policy"]["resize_readiness"]["length_changing_import_ready"] = True

    with pytest.raises(PrefabEditJsonError, match="policy evidence"):
        apply_prefab_edit_document(payload, document, allow_experimental_length_change=True)


def test_prefab_edit_json_rejects_transform_editing_policy_claim() -> None:
    payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")
    document = build_prefab_edit_document(payload)
    document["policy"]["transform_value_editing_supported"] = True

    with pytest.raises(PrefabEditJsonError, match="transform value editing is not supported"):
        apply_prefab_edit_document(payload, document, allow_experimental_length_change=True)


def test_prefab_edit_json_rejects_array_resizing_policy_claim() -> None:
    payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")
    document = build_prefab_edit_document(payload)
    document["policy"]["array_resizing_supported"] = True

    with pytest.raises(PrefabEditJsonError, match="array resizing is not supported"):
        apply_prefab_edit_document(payload, document, allow_experimental_length_change=True)


@pytest.mark.parametrize(
    "claim",
    (
        "resize_offset_validator_ready",
        "placement_resize_offset_gate_ready",
        "resource_resize_offset_gate_ready",
        "descriptor_count_mutation_supported",
        "descriptor_value_editing_supported",
        "reference_descriptor_editing_supported",
        "unknown_reference_preservation_supported",
    ),
)
def test_prefab_edit_json_rejects_unsupported_policy_gate_claims(claim: str) -> None:
    payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")
    document = build_prefab_edit_document(payload)
    document["policy"][claim] = True

    with pytest.raises(PrefabEditJsonError, match="unsupported field"):
        apply_prefab_edit_document(payload, document, allow_experimental_length_change=True)


@pytest.mark.parametrize(
    "claim",
    (
        "resize_offset_validator_ready",
        "placement_resize_offset_gate_ready",
        "resource_resize_offset_gate_ready",
        "descriptor_count_mutation_supported",
        "descriptor_value_editing_supported",
        "reference_descriptor_editing_supported",
        "unknown_reference_preservation_supported",
    ),
)
def test_prefab_edit_json_text_rejects_unsupported_policy_gate_claims(claim: str) -> None:
    payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")
    document = build_prefab_edit_document(payload)
    document["policy"][claim] = True

    with pytest.raises(PrefabEditJsonError, match="unsupported field"):
        apply_prefab_edit_json(payload, json.dumps(document))


def test_prefab_edit_json_rejects_partial_reference_rows() -> None:
    payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac") + _lp("character/model/test_b.pac")
    document = build_prefab_edit_document(payload)
    document["editable"]["resource_references"].pop()

    with pytest.raises(PrefabEditJsonError, match="reference rows do not match"):
        apply_prefab_edit_document(payload, document)


def test_prefab_edit_json_rejects_stale_declared_fields() -> None:
    payload = b"\xff\xff\x04\x00" + _lp("_materialInstanceParameters") + _lp("character/model/test_a.pac")
    document = build_prefab_edit_document(payload)
    document["declared_fields"] = []

    with pytest.raises(PrefabEditJsonError, match="declared fields"):
        apply_prefab_edit_document(payload, document)


def test_prefab_edit_json_rejects_stale_header_evidence() -> None:
    payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")
    document = build_prefab_edit_document(payload)
    document["structure"]["header"]["version"] = 99

    with pytest.raises(PrefabEditJsonError, match="header evidence"):
        apply_prefab_edit_document(payload, document)


def test_prefab_edit_json_validates_member_declaration_evidence() -> None:
    payload = (
        b"\xff\xff\x04\x00"
        + _lp("_skinnedMeshFile")
        + _lp("ResourceReferencePath_SkinnedMesh")
        + _lp("character/model/test_a.pac")
    )
    document = build_prefab_edit_document(payload)
    member = document["structure"]["member_declarations"][0]
    assert member["name"] == "_skinnedMeshFile"
    assert member["type"] == "ResourceReferencePath_SkinnedMesh"
    assert "descriptor_sha256" in member
    member["name"] = "_otherField"

    with pytest.raises(PrefabEditJsonError, match="member declarations"):
        apply_prefab_edit_document(payload, document)


def test_prefab_edit_json_validates_member_descriptor_evidence() -> None:
    payload = _prefab_profile_payload()
    document = build_prefab_edit_document(payload)
    member = document["structure"]["member_declarations"][0]
    assert member["descriptor_byte_length"] == 8
    assert member["descriptor_words_le_u16"] == [1, 1, 16, 0]
    assert member["descriptor_kind"] == "string"
    assert member["is_array"] is False
    assert member["is_reference"] is False
    assert member["is_transform"] is False
    assert member["array_stride_hint"] == 0
    assert member["array_count_hint"] == 0
    member["descriptor_sha256"] = "0" * 64

    with pytest.raises(PrefabEditJsonError, match="member declarations"):
        apply_prefab_edit_document(payload, document)


def test_prefab_edit_json_validates_member_descriptor_kind_evidence() -> None:
    payload = _prefab_profile_payload()
    document = build_prefab_edit_document(payload)
    document["structure"]["member_declarations"][0]["descriptor_kind"] = "transform"

    with pytest.raises(PrefabEditJsonError, match="member declarations"):
        apply_prefab_edit_document(payload, document)


def test_prefab_edit_json_validates_offset_candidate_evidence() -> None:
    prefix = b"\xff\xff\x04\x00" + _lp("_target") + _lp("IndexedStringA")
    target_offset = len(prefix) + 4
    payload = prefix + target_offset.to_bytes(4, "little") + _lp("character/model/test_a.pac")
    document = build_prefab_edit_document(payload)
    candidate = document["structure"]["offset_candidates"][0]
    assert candidate["value"] == target_offset
    assert candidate["target_kind"] == "string_length_prefix"
    assert candidate["candidate_offset_mod4"] == candidate["offset"] % 4
    assert candidate["target_value_mod4"] == candidate["value"] % 4
    candidate["value"] = 0

    with pytest.raises(PrefabEditJsonError, match="offset candidates"):
        apply_prefab_edit_document(payload, document)


def test_prefab_edit_json_rejects_stale_layout_evidence() -> None:
    payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")
    document = build_prefab_edit_document(payload)
    document["structure"]["layout"]["preserved_byte_count"] = 0

    with pytest.raises(PrefabEditJsonError, match="layout evidence"):
        apply_prefab_edit_document(payload, document)


def test_prefab_edit_json_rejects_stale_layout_span_evidence() -> None:
    payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")
    document = build_prefab_edit_document(payload)
    document["structure"]["layout"]["spans"][0]["end"] = 3

    with pytest.raises(PrefabEditJsonError, match="layout evidence"):
        apply_prefab_edit_document(payload, document)


def test_prefab_edit_json_rejects_partial_placement_rows() -> None:
    payload = _prefab_profile_payload()
    document = build_prefab_edit_document(payload)
    document["editable"]["placement_fields"].pop()

    with pytest.raises(PrefabEditJsonError, match="placement rows do not match"):
        apply_prefab_edit_document(payload, document)


def test_prefab_edit_json_rejects_invalid_json_text() -> None:
    payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")

    with pytest.raises(PrefabEditJsonError, match="not valid JSON"):
        apply_prefab_edit_json(payload, "{")


def test_prefab_edit_json_requires_duplicate_refs_to_change_together() -> None:
    old_path = "character/model/test_a.pac"
    new_path = "character/model/test_b.pac"
    payload = b"\xff\xff\x04\x00" + _lp(old_path) + _lp(old_path)
    document = build_prefab_edit_document(payload)
    rows = document["editable"]["resource_references"]
    assert len(rows) == 2
    rows[0]["value"] = new_path

    with pytest.raises(PrefabEditJsonError, match="edited consistently"):
        apply_prefab_edit_document(payload, document)


def test_prefab_edit_json_roundtrips_through_text() -> None:
    payload = b"\xff\xff\x04\x00" + _lp("character/model/test_a.pac")

    patched = apply_prefab_edit_json(payload, dumps_prefab_edit_json(payload))

    assert patched == payload


def test_prefab_edit_json_payload_writes_loose_mod_package(tmp_path) -> None:
    old_path = "character/model/test_a.pac"
    new_path = "character/model/test_b.pac"
    payload = b"\xff\xff\x04\x00" + _lp(old_path)
    document = build_prefab_edit_document(payload, "character/prefab/test.prefab")
    document["editable"]["resource_references"][0]["value"] = new_path
    patched = apply_prefab_edit_document(payload, document, virtual_path="character/prefab/test.prefab")
    entry = ArchiveEntry(
        path="character/prefab/test.prefab",
        pamt_path=tmp_path / "0.pamt",
        paz_file=tmp_path / "0.paz",
        offset=0,
        comp_size=len(payload),
        orig_size=len(payload),
        flags=0,
        paz_index=0,
    )

    result = export_archive_payloads_to_mod_ready_loose(
        [ArchivePatchRequest(entry, patched)],
        parent_root=tmp_path / "mods",
        package_info=ModPackageInfo(title="Prefab Edit"),
        create_no_encrypt_file=False,
    )

    output_path = result.package_root / "character" / "prefab" / "test.prefab"
    assert output_path.read_bytes() == patched
    assert new_path.encode("utf-8") in output_path.read_bytes()


def test_prefab_edit_json_placement_payload_writes_loose_mod_package(tmp_path) -> None:
    payload = _prefab_profile_payload()
    document = build_prefab_edit_document(payload, "character/prefab/test.prefab")
    document["editable"]["placement_fields"][0]["value"] = "Pelvis_L_Socket"
    patched = apply_prefab_edit_json(payload, json.dumps(document), virtual_path="character/prefab/test.prefab")
    entry = ArchiveEntry(
        path="character/prefab/test.prefab",
        pamt_path=tmp_path / "0.pamt",
        paz_file=tmp_path / "0.paz",
        offset=0,
        comp_size=len(payload),
        orig_size=len(payload),
        flags=0,
        paz_index=0,
    )

    result = export_archive_payloads_to_mod_ready_loose(
        [ArchivePatchRequest(entry, patched)],
        parent_root=tmp_path / "mods",
        package_info=ModPackageInfo(title="Prefab Edit"),
        create_no_encrypt_file=False,
    )

    output_path = result.package_root / "character" / "prefab" / "test.prefab"
    assert output_path.read_bytes() == patched
    assert b"Pelvis_L_Socket" in output_path.read_bytes()
