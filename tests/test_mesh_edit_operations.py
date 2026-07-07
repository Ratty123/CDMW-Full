from __future__ import annotations

import json

from cdmw.domain.mesh.operations import (
    MeshEditOperation,
    mesh_edit_operations_from_dicts,
    mesh_edit_operations_to_dicts,
    validate_mesh_edit_operation_coverage,
    validate_mesh_edit_operations,
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
