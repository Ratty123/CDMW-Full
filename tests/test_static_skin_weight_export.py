from __future__ import annotations

import copy
from unittest.mock import patch

import pytest

from cdmw.modding.mesh_native_rigging import find_native_mesh_core_binary
from cdmw.modding.mesh_pac_builder import _choose_pac_donor_indices, build_pac
from cdmw.modding.mesh_pam_builder import build_pam
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh, parse_pac
from cdmw.modding.mesh_skinning import pack_pac_skin_weights
from cdmw.modding.static_mesh_build import build_static_mesh_replacement
from cdmw.modding.static_mesh_types import (
    StaticMeshReplacementOptions,
    StaticReplacementTransform,
    StaticSubmeshMapping,
)
from tests.test_static_mesh_replacer_preview import _minimal_pac_original


def _skinned_pac() -> tuple[bytes, ParsedMesh]:
    raw, _original = _minimal_pac_original()
    parsed = parse_pac(raw, "target.pac")
    patched = bytearray(raw)
    for bone, offset in enumerate(parsed.submeshes[0].source_vertex_offsets):
        patched[offset + 28:offset + 32] = bytes((bone, 0xFF, 0xFF, 0xFF))
        patched[offset + 32:offset + 36] = bytes((255, 0, 0, 0))
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


def test_pac_skin_weight_export_blocks_bones_missing_from_target_palette() -> None:
    raw, original = _skinned_pac()
    updated = copy.deepcopy(original)
    updated.submeshes[0].bone_indices[0] = (99,)
    updated.submeshes[0].bone_weights[0] = (1.0,)

    with pytest.raises(ValueError, match="bone palette does not contain"):
        build_pac(updated, raw)


def test_pac_skin_weight_export_blocks_palette_slot_255() -> None:
    with pytest.raises(ValueError, match="exceeds slot 254"):
        pack_pac_skin_weights(bytearray(40), (255,), (1.0,), tuple(range(256)), context="test vertex")


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


def test_static_replacement_blocks_far_skin_transfer() -> None:
    if find_native_mesh_core_binary() is None:
        pytest.skip("cdmw_mesh_core is not built")
    raw, original = _skinned_pac()
    replacement = _replacement([(10.25, 10.25, 0.0), (10.5, 10.25, 0.0), (10.25, 10.5, 0.0)])

    with pytest.raises(ValueError, match=r"p95 .* exceeds 5% bounds limit"):
        build_static_mesh_replacement(raw, original, replacement, _static_options())


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
