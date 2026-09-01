from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from cdmw.domain.mesh.operations import (
    MeshEditOperation,
    mesh_edit_operations_from_dicts,
    mesh_edit_operations_to_dicts,
    validate_mesh_edit_operation_coverage,
    validate_mesh_edit_operations,
)
from cdmw.domain.mesh.export_validation import validate_mesh_export
from cdmw.modding.mesh_importer import (
    _build_prepared_mesh_bytes,
    _validate_exact_pac_skin_weight_byte_ownership,
    apply_operation_channels_to_original,
)
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh


def _mesh(vertex_count: int = 3, *, source_map: object = "default") -> ParsedMesh:
    source_vertex_map = list(range(vertex_count)) if source_map == "default" else source_map
    return ParsedMesh(
        path="part.pac",
        format="pac",
        submeshes=[
            SubMesh(
                name="part",
                vertices=[(0.0, 0.0, 0.0)] * vertex_count,
                faces=[(0, 1, 2)] if vertex_count >= 3 else [],
                source_vertex_map=source_vertex_map,  # type: ignore[arg-type]
                vertex_count=vertex_count,
                face_count=1 if vertex_count >= 3 else 0,
            )
        ],
        total_vertices=vertex_count,
        total_faces=1 if vertex_count >= 3 else 0,
    )


def test_mesh_edit_operation_serializes_as_sidecar_json_shape() -> None:
    operation = MeshEditOperation(
        "replace_positions_same_count",
        lod_index=0,
        submesh_index=2,
        vertex_count=1842,
        source="mesh.obj",
        metadata={"channel": "positions"},
    )

    payload = json.loads(json.dumps(operation.to_dict()))
    restored = mesh_edit_operations_from_dicts([payload])[0]

    assert payload["operation"] == "replace_positions_same_count"
    assert restored == operation
    assert mesh_edit_operations_to_dicts([restored]) == (payload,)


def test_mesh_edit_operation_validator_accepts_allowed_same_count_operation() -> None:
    issues = validate_mesh_edit_operations(
        [MeshEditOperation("replace_positions_same_count", submesh_index=0, vertex_count=3)],
        mesh=_mesh(),
        allowed_operations=("replace_positions_same_count",),
    )

    assert issues == ()


def test_mesh_edit_operation_validator_requires_source_map_for_same_count_operations() -> None:
    issues = validate_mesh_edit_operations(
        [MeshEditOperation("replace_positions_same_count", submesh_index=0, vertex_count=3)],
        mesh=_mesh(source_map=[]),
        allowed_operations=("replace_positions_same_count",),
    )

    assert "operation_source_map_missing" in {issue.code for issue in issues}


def test_mesh_edit_operation_validator_requires_source_map_for_transform_operations() -> None:
    issues = validate_mesh_edit_operations(
        [MeshEditOperation("translate_vertices", submesh_index=0, vertex_count=3)],
        mesh=_mesh(source_map=[]),
        allowed_operations=("translate_vertices",),
    )

    assert "operation_source_map_missing" in {issue.code for issue in issues}


def test_mesh_edit_operation_validator_blocks_unsafe_or_mismatched_operations() -> None:
    issues = validate_mesh_edit_operations(
        [
            MeshEditOperation("topology_replacement", submesh_index=0, vertex_count=3),
            MeshEditOperation("replace_positions_same_count", submesh_index=0, vertex_count=4),
        ],
        mesh=_mesh(),
        allowed_operations=("replace_positions_same_count",),
    )

    assert {issue.code for issue in issues} >= {
        "blocked_edit_operation",
        "disallowed_edit_operation",
        "operation_vertex_count_mismatch",
    }


def test_mesh_edit_operation_coverage_blocks_unlisted_channel_changes() -> None:
    original = _mesh()
    edited = _mesh()
    original.submeshes[0].uvs = [(0.0, 0.0)] * 3
    edited.submeshes[0].uvs = [(1.0, 0.0)] * 3

    issues = validate_mesh_edit_operation_coverage(
        [MeshEditOperation("replace_positions_same_count", submesh_index=0, vertex_count=3)],
        mesh=edited,
        original_mesh=original,
    )

    assert "untracked_edit_channel" in {issue.code for issue in issues}


def _skinned_mesh() -> ParsedMesh:
    mesh = _mesh()
    submesh = mesh.submeshes[0]
    submesh.bone_indices = [(3, 7), (3,), (3,)]
    submesh.bone_weights = [(200.0 / 255.0, 55.0 / 255.0), (1.0,), (1.0,)]
    submesh.source_skin_weight_layout = "pac_slot_u10x6"
    submesh.source_vertex_stride = 40
    submesh.source_vertex_offsets = [100, 140, 180]
    mesh.has_bones = True
    return mesh


def test_skin_weight_operation_owns_both_rows_and_is_source_mapped() -> None:
    original = _skinned_mesh()
    edited = _skinned_mesh()
    edited.submeshes[0].bone_weights[0] = (0.7, 0.3)
    operation = MeshEditOperation(
        "replace_skin_weights_same_count",
        submesh_index=0,
        vertex_count=3,
        metadata={"palette_size": 8},
    )

    assert validate_mesh_edit_operations([operation], mesh=edited) == ()
    assert validate_mesh_edit_operation_coverage(
        [operation],
        mesh=edited,
        original_mesh=original,
    ) == ()


def test_operation_channel_merge_copies_skin_indices_and_weights_atomically() -> None:
    original = _skinned_mesh()
    edited = _skinned_mesh()
    edited.submeshes[0].bone_indices[0] = (3, 4, 7)
    edited.submeshes[0].bone_weights[0] = (0.6, 0.1, 0.3)
    setattr(
        edited,
        "_cdmw_edit_operations",
        (
            MeshEditOperation(
                "replace_skin_weights_same_count",
                submesh_index=0,
                vertex_count=3,
            ),
        ),
    )

    merged = apply_operation_channels_to_original(original, edited)

    assert merged.submeshes[0].bone_indices[0] == (3, 4, 7)
    assert merged.submeshes[0].bone_weights[0] == (0.6, 0.1, 0.3)


def test_untracked_or_free_edit_skin_weight_changes_remain_blocked() -> None:
    original = _skinned_mesh()
    edited = _skinned_mesh()
    edited.submeshes[0].bone_weights[0] = (0.7, 0.3)
    operation = MeshEditOperation(
        "replace_skin_weights_same_count",
        submesh_index=0,
        vertex_count=3,
    )

    untracked = validate_mesh_export(
        edited,
        original_mesh=original,
        skeleton_bone_count=16,
    )
    free_edit = validate_mesh_export(
        edited,
        original_mesh=original,
        skeleton_bone_count=16,
        edit_operations=(operation,),
        exact_output=False,
    )

    assert "skinning_data_changed" in {issue.code for issue in untracked.blockers}
    assert "skin_weight_operation_requires_exact_pac" in {
        issue.code for issue in free_edit.blockers
    }


def test_exact_skin_weight_operation_rejects_protected_or_invalid_rows() -> None:
    original = _skinned_mesh()
    original.submeshes[0].bone_indices[0] = tuple(range(7))
    original.submeshes[0].bone_weights[0] = tuple([1.0 / 7.0] * 7)
    edited = _skinned_mesh()
    edited.submeshes[0].bone_indices[0] = (3, 1024)
    edited.submeshes[0].bone_weights[0] = (0.5, 0.5)
    operation = MeshEditOperation(
        "replace_skin_weights_same_count",
        submesh_index=0,
        vertex_count=3,
    )

    report = validate_mesh_export(
        edited,
        original_mesh=original,
        skeleton_bone_count=2048,
        edit_operations=(operation,),
    )
    codes = {issue.code for issue in report.blockers}

    assert "skin_weight_protected_influences_present" in codes
    assert "invalid_safe_skin_weight_row" in codes


def test_exact_skin_weight_operation_requires_lod0_and_unchanged_palette_metadata() -> None:
    original = _skinned_mesh()
    edited = _skinned_mesh()
    original.submeshes[0].source_bone_palette = (0, 1, 2, 3)
    edited.submeshes[0].source_bone_palette = (0, 1, 2, 4)
    edited.submeshes[0].bone_weights[0] = (0.7, 0.3)
    operation = MeshEditOperation(
        "replace_skin_weights_same_count",
        submesh_index=0,
        vertex_count=3,
    )

    palette_report = validate_mesh_export(
        edited,
        original_mesh=original,
        skeleton_bone_count=16,
        edit_operations=(operation,),
    )
    edited.submeshes[0].source_bone_palette = original.submeshes[0].source_bone_palette
    edited.active_lod_index = 1
    lod_report = validate_mesh_export(
        edited,
        original_mesh=original,
        skeleton_bone_count=16,
        edit_operations=(operation,),
    )

    assert "skin_weight_palette_changed" in {
        issue.code for issue in palette_report.blockers
    }
    assert "skinning_data_changed" in {issue.code for issue in lod_report.blockers}


def test_exact_skin_weight_operation_rejects_a_slot_outside_the_original_palette() -> None:
    original = _skinned_mesh()
    edited = _skinned_mesh()
    original.submeshes[0].source_bone_palette = tuple(range(8))
    edited.submeshes[0].source_bone_palette = tuple(range(8))
    edited.submeshes[0].bone_indices[0] = (3, 8)
    edited.submeshes[0].bone_weights[0] = (0.5, 0.5)
    operation = MeshEditOperation(
        "replace_skin_weights_same_count",
        submesh_index=0,
        vertex_count=3,
        metadata={"palette_size": 8},
    )

    report = validate_mesh_export(
        edited,
        original_mesh=original,
        skeleton_bone_count=64,
        edit_operations=(operation,),
    )

    assert "invalid_safe_skin_weight_row" in {
        issue.code for issue in report.blockers
    }


def test_skin_weight_only_rebuild_rejects_every_byte_outside_owned_record_lanes() -> None:
    mesh = _skinned_mesh()
    setattr(
        mesh,
        "_cdmw_edit_operations",
        (
            MeshEditOperation(
                "replace_skin_weights_same_count",
                submesh_index=0,
                vertex_count=3,
            ),
        ),
    )
    original = bytes(240)
    allowed = bytearray(original)
    allowed[120] = 1
    allowed[133] = 2

    _validate_exact_pac_skin_weight_byte_ownership(
        "pac",
        mesh,
        original,
        bytes(allowed),
    )

    contaminated = bytearray(allowed)
    contaminated[119] = 3
    with pytest.raises(ValueError, match="unowned byte.*119"):
        _validate_exact_pac_skin_weight_byte_ownership(
            "pac",
            mesh,
            original,
            bytes(contaminated),
        )


def test_explicit_pac_skin_weight_operation_bypasses_the_native_writer() -> None:
    mesh = _skinned_mesh()
    setattr(
        mesh,
        "_cdmw_edit_operations",
        (
            MeshEditOperation(
                "replace_skin_weights_same_count",
                submesh_index=0,
                vertex_count=3,
            ),
        ),
    )
    original = bytes(240)

    with (
        patch("cdmw.core.mesh_native.build_mesh_native") as native_writer,
        patch(
            "cdmw.modding.mesh_importer.build_pac",
            return_value=original,
        ) as python_writer,
    ):
        rebuilt = _build_prepared_mesh_bytes("pac", mesh, original)

    assert rebuilt == original
    native_writer.assert_not_called()
    python_writer.assert_called_once_with(mesh, original)
