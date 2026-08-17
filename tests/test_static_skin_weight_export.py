from __future__ import annotations

import copy
import struct
from unittest.mock import patch

import pytest

from cdmw.modding.mesh_native_rigging import find_native_mesh_core_binary
from cdmw.modding.mesh_importer import build_mesh
from cdmw.modding.mesh_pac_builder import _choose_pac_donor_indices, build_pac
from cdmw.modding.mesh_pam_builder import build_pam
from cdmw.modding.mesh_parser import (
    PAC_SKIN_INFLUENCES,
    PAC_SKIN_PALETTE_SLOTS,
    PAC_SKIN_MAX_BONE_INDEX,
    PAC_SKIN_SLOT_GROUPS,
    PAC_SKIN_WEIGHT_OFFSET,
    ParsedMesh,
    SubMesh,
    parse_pac,
)
from cdmw.modding.mesh_skinning import pack_pac_skin_weights
from cdmw.modding.static_mesh_build import build_static_mesh_replacement
from cdmw.modding.static_mesh_types import (
    StaticMeshReplacementOptions,
    StaticReplacementTransform,
    StaticSubmeshMapping,
)
from tests.test_static_mesh_replacer_preview import _minimal_pac_original


def _skinned_pac() -> tuple[bytes, ParsedMesh]:
    """A PAC whose every vertex is rigidly bound to one slot, in the packed layout.

    Slots live in two u32 of three 10-bit fields; an unused influence is a zero
    weight, not a reserved slot value.
    """

    raw, _original = _minimal_pac_original()
    parsed = parse_pac(raw, "target.pac")
    patched = bytearray(raw)
    for bone, offset in enumerate(parsed.submeshes[0].source_vertex_offsets):
        struct.pack_into("<I", patched, offset + PAC_SKIN_SLOT_GROUPS[0], bone)
        struct.pack_into("<I", patched, offset + PAC_SKIN_SLOT_GROUPS[1], 0)
        patched[offset + PAC_SKIN_WEIGHT_OFFSET:offset + PAC_SKIN_WEIGHT_OFFSET + PAC_SKIN_INFLUENCES] = bytes(
            (255,) + (0,) * (PAC_SKIN_INFLUENCES - 1)
        )
    result = bytes(patched)
    return result, parse_pac(result, "target.pac")


def _weight_map(submesh: SubMesh, vertex: int) -> dict[int, float]:
    return dict(zip(submesh.bone_indices[vertex], submesh.bone_weights[vertex]))


def _replacement(vertices: list[tuple[float, float, float]]) -> ParsedMesh:
    return ParsedMesh(
        path="replacement.glb",
        format="glb",
        submeshes=[SubMesh(
            name="replacement",
            vertices=vertices,
            uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
            faces=[(0, 1, 2)],
        )],
        total_vertices=3,
        total_faces=1,
        has_uvs=True,
    )


def _static_options() -> StaticMeshReplacementOptions:
    return StaticMeshReplacementOptions(
        transform=StaticReplacementTransform(alignment_mode="manual", scale_to_original_length=False),
        submesh_mappings=[StaticSubmeshMapping(0, "target", [0], 0)],
    )


def test_topology_source_map_cannot_select_target_donor_records() -> None:
    original = SubMesh(
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)],
        source_descriptor_offset=100,
        source_vertex_stride=40,
    )
    candidate = SubMesh(
        vertices=[(0.01, 0.0, 0.0)],
        source_vertex_map=[2],
        source_vertex_map_authority="topology",
        source_descriptor_offset=100,
        source_vertex_stride=40,
    )
    assert _choose_pac_donor_indices(original, candidate) == [0]

    candidate.source_vertex_map_authority = "target_donor_record"
    assert _choose_pac_donor_indices(original, candidate) == [2]


def test_pac_skin_weights_encode_and_reparse_with_exact_unorm_sum() -> None:
    raw, original = _skinned_pac()
    updated = copy.deepcopy(original)
    updated.submeshes[0].bone_indices[0] = (0, 1)
    updated.submeshes[0].bone_weights[0] = (0.25, 0.75)

    reparsed = parse_pac(build_pac(updated, raw), "target.pac")
    weights = _weight_map(reparsed.submeshes[0], 0)

    assert reparsed.submeshes[0].source_bone_palette == (0, 1, 2, 3)
    assert weights[0] == pytest.approx(64 / 255.0)
    assert weights[1] == pytest.approx(191 / 255.0)
    assert sum(weights.values()) == pytest.approx(1.0)


def test_pac_skin_weight_export_round_trips_a_high_bone_index() -> None:
    # Slots are per-mesh palette tokens in a 10-bit field, so they reach 1023 --
    # well past anything the old u8 lane could hold. They must survive verbatim.
    raw, original = _skinned_pac()
    updated = copy.deepcopy(original)
    updated.submeshes[0].bone_indices[0] = (PAC_SKIN_MAX_BONE_INDEX,)
    updated.submeshes[0].bone_weights[0] = (1.0,)

    reparsed = parse_pac(build_pac(updated, raw), "target.pac")

    assert _weight_map(reparsed.submeshes[0], 0) == {PAC_SKIN_MAX_BONE_INDEX: pytest.approx(1.0)}


def test_pac_skin_weight_export_writes_six_influences() -> None:
    """All six palette lanes encode and decode; the fifth and sixth are not dropped.

    Six, not eight: the writer authors the palette slots only. The record's two
    further influences live in lanes the exact serializer protects, so nothing
    here writes them.
    """

    raw, original = _skinned_pac()
    updated = copy.deepcopy(original)
    updated.submeshes[0].bone_indices[0] = (10, 20, 30, 40, 50, 60)
    updated.submeshes[0].bone_weights[0] = (0.3, 0.25, 0.2, 0.1, 0.1, 0.05)

    reparsed = parse_pac(build_pac(updated, raw), "target.pac")
    row = reparsed.submeshes[0]

    assert len(row.bone_indices[0]) == PAC_SKIN_PALETTE_SLOTS
    assert set(row.bone_indices[0]) == {10, 20, 30, 40, 50, 60}
    assert sum(row.bone_weights[0]) == pytest.approx(1.0)
    # The format stores weights descending; the reader relies on it.
    assert list(row.bone_weights[0]) == sorted(row.bone_weights[0], reverse=True)


def test_pac_skin_weight_export_blocks_a_slot_wider_than_the_field() -> None:
    with pytest.raises(ValueError, match="exceed the PAC limit"):
        pack_pac_skin_weights(
            bytearray(40), (PAC_SKIN_MAX_BONE_INDEX + 1,), (1.0,), context="test vertex"
        )


def test_static_replacement_transfers_after_alignment_and_reparses() -> None:
    if find_native_mesh_core_binary() is None:
        pytest.skip("cdmw_mesh_core is not built")
    raw, original = _skinned_pac()
    replacement = _replacement([(0.25, 0.25, 0.0), (0.5, 0.25, 0.0), (0.25, 0.5, 0.0)])

    rebuilt, report = build_static_mesh_replacement(raw, original, replacement, _static_options())
    reparsed = parse_pac(rebuilt, "target.pac")

    assert any("transferred 3 vertices" in line for line in report.alignment_summary)
    first = _weight_map(reparsed.submeshes[0], 0)
    assert first[0] == pytest.approx(127 / 255.0)
    assert first[1] == pytest.approx(64 / 255.0)
    assert first[2] == pytest.approx(64 / 255.0)
    assert sum(first.values()) == pytest.approx(1.0)


def test_static_replacement_preserves_exact_target_rows_from_roundtrip_map() -> None:
    if find_native_mesh_core_binary() is None:
        pytest.skip("cdmw_mesh_core is not built")
    raw, original = _skinned_pac()
    replacement = _replacement([(0.25, 0.25, 0.0), (0.5, 0.25, 0.0), (0.25, 0.5, 0.0)])
    replacement.submeshes[0].source_vertex_map = [0, 1, 2]
    replacement.submeshes[0].source_vertex_map_authority = "target_donor_record"

    rebuilt, report = build_static_mesh_replacement(raw, original, replacement, _static_options())
    reparsed = parse_pac(rebuilt, "target.pac")

    assert [_weight_map(reparsed.submeshes[0], index) for index in range(3)] == [
        {0: pytest.approx(1.0)},
        {1: pytest.approx(1.0)},
        {2: pytest.approx(1.0)},
    ]
    assert any("preserved 3 exact donor rows" in line for line in report.alignment_summary)


def test_single_submesh_skinned_pac_roundtrip_requires_matching_sidecar() -> None:
    raw, _original = _skinned_pac()
    imported = _replacement([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)])
    imported.path = "target.pac"
    imported.format = "pac"
    setattr(imported, "_cdmw_imported_from_obj", True)
    setattr(imported, "_cdmw_obj_sidecar_present", False)

    with pytest.raises(ValueError, match=r"Skinned PAC OBJ round-trip requires .*\.obj\.meta\.json"):
        build_mesh(imported, raw)


def test_obj_roundtrip_rejects_rebuilt_pac_that_changes_protected_vertex_bytes() -> None:
    raw, original = _skinned_pac()
    imported = copy.deepcopy(original)
    imported.submeshes[0].vertices[0] = (0.25, 0.0, 0.0)
    setattr(imported, "_cdmw_imported_from_obj", True)
    setattr(imported, "_cdmw_obj_sidecar_present", True)
    setattr(
        imported,
        "_cdmw_edit_operations",
        (
            {
                "operation": "replace_positions_same_count",
                "lod_index": 0,
                "submesh_index": 0,
                "vertex_count": len(imported.submeshes[0].vertices),
                "source": "target.obj",
            },
        ),
    )
    corrupted = bytearray(raw)
    protected_offset = original.submeshes[0].source_vertex_offsets[0] + PAC_SKIN_SLOT_GROUPS[0]
    corrupted[protected_offset] ^= 0x01

    with (
        patch("cdmw.core.mesh_native.build_mesh_native", return_value=bytes(corrupted)),
        pytest.raises(ValueError, match="changed protected PAC vertex bytes"),
    ):
        build_mesh(imported, raw)


def test_static_replacement_warns_on_far_skin_transfer_and_still_builds() -> None:
    """A far transfer is reported, not refused.

    This pinned the refusal until the owner hit it on a real weapon swap: an
    imported blade never sits on the target handle's surface, so every such
    build was blocked by a quality warning dressed as an error. The build now
    completes with the nearest-surface weights and says, in its summary, that
    the rig was matched from a distance.
    """
    if find_native_mesh_core_binary() is None:
        pytest.skip("cdmw_mesh_core is not built")
    raw, original = _skinned_pac()
    replacement = _replacement([(10.25, 10.25, 0.0), (10.5, 10.25, 0.0), (10.25, 10.5, 0.0)])

    rebuilt, report = build_static_mesh_replacement(raw, original, replacement, _static_options())

    assert report.ok
    assert rebuilt
    joined = "\n".join(report.alignment_summary)
    assert "matched from far off the source surface" in joined
    assert "more than 5% of the source bounds" in joined


def test_static_replacement_blocks_proven_skin_layout_without_donor_rows() -> None:
    raw, _original = _minimal_pac_original()
    original = parse_pac(raw, "target.pac")
    replacement = _replacement([(0.25, 0.25, 0.0), (0.5, 0.25, 0.0), (0.25, 0.5, 0.0)])

    with pytest.raises(ValueError, match="no decoded donor influence rows"):
        build_static_mesh_replacement(raw, original, replacement, _static_options())


def test_pam_skin_weight_changes_block_without_proven_layout() -> None:
    original = ParsedMesh(format="pam", submeshes=[SubMesh(vertices=[(0.0, 0.0, 0.0)])])
    updated = copy.deepcopy(original)
    updated.submeshes[0].bone_indices = [(0,)]
    updated.submeshes[0].bone_weights = [(1.0,)]
    data = b"PAR " + bytes(96)

    with (
        patch("cdmw.modding.mesh_pam_builder.parse_pam", return_value=original),
        patch("cdmw.modding.mesh_pam_builder._merge_partial_static_import", return_value=updated),
        patch("cdmw.modding.mesh_pam_builder._align_submesh_order_like_original"),
        pytest.raises(ValueError, match="PAM skin-weight edits are blocked"),
    ):
        build_pam(updated, data)
