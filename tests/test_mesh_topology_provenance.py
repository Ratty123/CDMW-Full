"""Contract tests for the pure topology provenance owner."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from cdmw.domain.mesh import validate_mesh_asset_rebuild, validate_mesh_export
from cdmw.domain.mesh.topology import (
    SubmeshTopologyProvenance,
    TOPOLOGY_CONTRACT_UNSUPPORTED,
    TOPOLOGY_DERIVED_SOURCE_SENTINEL,
    TOPOLOGY_EMPTY_SUBMESH_UNSUPPORTED,
    TOPOLOGY_FACE_ORIGIN_INVALID,
    TOPOLOGY_MAX_PAC_VERTEX_COUNT,
    TOPOLOGY_METADATA_KEYS,
    TOPOLOGY_OPERATION_DELETE_FACES,
    TOPOLOGY_OPERATION_LOOP_CUT,
    TOPOLOGY_OPERATION_SUBDIVIDE_MIDPOINT,
    TOPOLOGY_PAC_INDEX_LIMIT_EXCEEDED,
    TOPOLOGY_PROVENANCE_REQUIRED,
    TOPOLOGY_PROVENANCE_VERSION,
    TOPOLOGY_REVISION_DISCONTINUOUS,
    TOPOLOGY_VERTEX_ORIGIN_INVALID,
    TopologyProvenanceError,
    VertexOrigin,
    canonical_vertex_origin,
    compose_topology_provenance,
    identity_topology_provenance,
    removed_original_faces,
    removed_original_vertices,
    topology_operation_for_native_action,
    topology_operation_metadata,
    topology_source_face_indices,
    topology_source_vertex_map,
    validate_topology_operation_history,
    validate_topology_provenance,
)
from cdmw.domain.mesh.operations import MeshEditOperation, validate_mesh_edit_operations
from cdmw.modding.mesh_asset import mesh_asset_from_parsed_mesh, mesh_asset_to_inspect_dict
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh


# ── canonical form ───────────────────────────────────────────────────


def test_identity_provenance_is_one_direct_origin_per_vertex_and_face() -> None:
    provenance = identity_topology_provenance(4, 2)

    assert provenance.version == TOPOLOGY_PROVENANCE_VERSION
    assert provenance.output_vertex_count == 4
    assert provenance.output_face_count == 2
    assert topology_source_vertex_map(provenance) == (0, 1, 2, 3)
    assert topology_source_face_indices(provenance) == (0, 1)
    assert provenance.derived_vertex_count == 0
    assert validate_topology_provenance(provenance, output_vertex_count=4, output_face_count=2) == ()


def test_canonical_origin_merges_duplicate_parents_and_normalizes_exactly() -> None:
    origin = canonical_vertex_origin((3, 1, 3), (0.25, 0.5, 0.25), original_vertex_count=8)

    assert origin.parents == (1, 3)
    assert origin.weights == (0.5, 0.5)
    assert math.fsum(origin.weights) == 1.0
    assert origin.derived is True
    assert origin.direct_parent == TOPOLOGY_DERIVED_SOURCE_SENTINEL


def test_canonical_origin_rejects_out_of_range_and_non_positive_weights() -> None:
    with pytest.raises(TopologyProvenanceError) as out_of_range:
        canonical_vertex_origin((9,), (1.0,), original_vertex_count=4)
    assert out_of_range.value.code == TOPOLOGY_VERTEX_ORIGIN_INVALID

    with pytest.raises(TopologyProvenanceError):
        canonical_vertex_origin((0,), (0.0,), original_vertex_count=4)
    with pytest.raises(TopologyProvenanceError):
        canonical_vertex_origin((0,), (float("nan"),), original_vertex_count=4)
    with pytest.raises(TopologyProvenanceError):
        canonical_vertex_origin((0, 1), (0.5,), original_vertex_count=4)


# ── composition for the three admitted operations ────────────────────


def _quad() -> SubmeshTopologyProvenance:
    """Two triangles over four vertices."""
    return identity_topology_provenance(4, 2)


def test_face_delete_keeps_surviving_face_origins_and_compacts_vertices() -> None:
    # Drop triangle 1, keeping vertices 0,1,2 which become outputs 0,1,2.
    composed = compose_topology_provenance(
        _quad(),
        copy_vertex_indices=(0, 1, 2),
        face_origins=(0,),
    )

    assert topology_source_vertex_map(composed) == (0, 1, 2)
    assert topology_source_face_indices(composed) == (0,)
    assert removed_original_vertices(composed) == (3,)
    assert removed_original_faces(composed) == (1,)
    assert validate_topology_provenance(composed, output_vertex_count=3, output_face_count=1) == ()


def test_midpoint_subdivide_derives_two_parent_origins_and_inherits_face_identity() -> None:
    composed = compose_topology_provenance(
        _quad(),
        copy_vertex_indices=(0, 1, 2, 3, -1, -1, -1),
        vertex_blends=(
            {"index": 4, "left": 0, "right": 1, "factor": 0.5},
            {"index": 5, "left": 1, "right": 2, "factor": 0.5},
            {"index": 6, "left": 2, "right": 0, "factor": 0.5},
        ),
        # Face 0 split into four children; face 1 untouched.
        face_origins=(0, 0, 0, 0, 1),
    )

    assert topology_source_vertex_map(composed) == (0, 1, 2, 3, -1, -1, -1)
    assert composed.vertex_origins[4] == VertexOrigin((0, 1), (0.5, 0.5))
    assert topology_source_face_indices(composed) == (0, 0, 0, 0, 1)
    assert composed.derived_vertex_count == 3
    assert validate_topology_provenance(composed, output_vertex_count=7, output_face_count=5) == ()


def test_loop_cut_at_a_non_midpoint_fraction_uses_the_native_factor() -> None:
    composed = compose_topology_provenance(
        _quad(),
        copy_vertex_indices=(0, 1, 2, 3, -1),
        vertex_blends=({"index": 4, "left": 0, "right": 1, "factor": 0.25},),
        face_origins=(0, 0, 1),
    )

    origin = composed.vertex_origins[4]
    assert origin.parents == (0, 1)
    assert origin.weights == pytest.approx((0.75, 0.25), abs=1e-15)
    assert math.fsum(origin.weights) == 1.0


def test_chained_subdivision_stays_one_level_deep_against_original_parents() -> None:
    first = compose_topology_provenance(
        _quad(),
        copy_vertex_indices=(0, 1, 2, 3, -1),
        vertex_blends=({"index": 4, "left": 0, "right": 1, "factor": 0.5},),
        face_origins=(0, 0, 1),
    )
    # Now split the edge between original vertex 0 and the derived midpoint.
    second = compose_topology_provenance(
        first,
        copy_vertex_indices=(0, 1, 2, 3, 4, -1),
        vertex_blends=({"index": 5, "left": 0, "right": 4, "factor": 0.5},),
        face_origins=(0, 1, 2, 2),
    )

    assert second.original_vertex_count == 4
    assert second.vertex_origins[5].parents == (0, 1)
    assert second.vertex_origins[5].weights == pytest.approx((0.75, 0.25), abs=1e-15)
    assert math.fsum(second.vertex_origins[5].weights) == 1.0
    assert topology_source_face_indices(second) == (0, 0, 1, 1)
    assert validate_topology_provenance(second, output_vertex_count=6, output_face_count=4) == ()


def test_later_sculpt_does_not_change_provenance() -> None:
    composed = compose_topology_provenance(
        _quad(),
        copy_vertex_indices=(0, 1, 2, 3, -1),
        vertex_blends=({"index": 4, "left": 0, "right": 1, "factor": 0.5},),
        face_origins=(0, 0, 1),
    )
    # A sculpt is a same-count edit: identity copies, unchanged faces.
    sculpted = compose_topology_provenance(
        composed,
        copy_vertex_indices=(0, 1, 2, 3, 4),
        face_origins=(0, 1, 2),
    )

    assert sculpted.vertex_origins == composed.vertex_origins
    assert sculpted.face_origins == composed.face_origins


# ── rejection ────────────────────────────────────────────────────────


def test_composition_rejects_missing_derivations_and_stale_references() -> None:
    with pytest.raises(TopologyProvenanceError) as missing:
        compose_topology_provenance(_quad(), copy_vertex_indices=(0, 1, -1), face_origins=(0,))
    assert missing.value.code == TOPOLOGY_VERTEX_ORIGIN_INVALID

    with pytest.raises(TopologyProvenanceError) as out_of_range:
        compose_topology_provenance(_quad(), copy_vertex_indices=(0, 1, 9), face_origins=(0,))
    assert out_of_range.value.code == TOPOLOGY_VERTEX_ORIGIN_INVALID

    with pytest.raises(TopologyProvenanceError) as bad_blend:
        compose_topology_provenance(
            _quad(),
            copy_vertex_indices=(0, 1, 2, -1),
            vertex_blends=({"index": 3, "left": 0, "right": 99, "factor": 0.5},),
            face_origins=(0,),
        )
    assert bad_blend.value.code == TOPOLOGY_VERTEX_ORIGIN_INVALID

    with pytest.raises(TopologyProvenanceError) as duplicate_blend:
        compose_topology_provenance(
            _quad(),
            copy_vertex_indices=(0, 1, 2, -1),
            vertex_blends=(
                {"index": 3, "left": 0, "right": 1, "factor": 0.5},
                {"index": 3, "left": 1, "right": 2, "factor": 0.5},
            ),
            face_origins=(0,),
        )
    assert duplicate_blend.value.code == TOPOLOGY_VERTEX_ORIGIN_INVALID


def test_composition_rejects_a_degenerate_blend_factor() -> None:
    for factor in (0.0, 1.0, -0.5, 1.5, float("nan")):
        with pytest.raises(TopologyProvenanceError):
            compose_topology_provenance(
                _quad(),
                copy_vertex_indices=(0, 1, 2, -1),
                vertex_blends=({"index": 3, "left": 0, "right": 1, "factor": factor},),
                face_origins=(0,),
            )


def test_composition_rejects_incomplete_and_out_of_range_face_origins() -> None:
    with pytest.raises(TopologyProvenanceError) as empty:
        compose_topology_provenance(_quad(), copy_vertex_indices=(0, 1, 2), face_origins=())
    assert empty.value.code == TOPOLOGY_EMPTY_SUBMESH_UNSUPPORTED

    with pytest.raises(TopologyProvenanceError) as stale:
        compose_topology_provenance(_quad(), copy_vertex_indices=(0, 1, 2), face_origins=(7,))
    assert stale.value.code == TOPOLOGY_FACE_ORIGIN_INVALID


def test_composition_rejects_an_empty_output_submesh() -> None:
    with pytest.raises(TopologyProvenanceError) as empty:
        compose_topology_provenance(_quad(), copy_vertex_indices=(), face_origins=(0,))
    assert empty.value.code == TOPOLOGY_EMPTY_SUBMESH_UNSUPPORTED


def test_validation_rejects_non_canonical_and_mismatched_contracts() -> None:
    provenance = identity_topology_provenance(3, 1)

    assert validate_topology_provenance(None, output_vertex_count=3, output_face_count=1) == (
        TOPOLOGY_PROVENANCE_REQUIRED,
    )
    assert TOPOLOGY_VERTEX_ORIGIN_INVALID in validate_topology_provenance(
        provenance, output_vertex_count=2, output_face_count=1
    )
    assert TOPOLOGY_FACE_ORIGIN_INVALID in validate_topology_provenance(
        provenance, output_vertex_count=3, output_face_count=2
    )
    assert TOPOLOGY_CONTRACT_UNSUPPORTED in validate_topology_provenance(
        replace(provenance, version="cdmw_mesh_topology_provenance_v9"),
        output_vertex_count=3,
        output_face_count=1,
    )
    descending = replace(
        provenance,
        vertex_origins=(VertexOrigin((2, 0), (0.5, 0.5)), VertexOrigin((1,), (1.0,)), VertexOrigin((2,), (1.0,))),
    )
    assert TOPOLOGY_VERTEX_ORIGIN_INVALID in validate_topology_provenance(
        descending, output_vertex_count=3, output_face_count=1
    )
    unnormalized = replace(
        provenance,
        vertex_origins=(VertexOrigin((0, 1), (0.5, 0.4)), VertexOrigin((1,), (1.0,)), VertexOrigin((2,), (1.0,))),
    )
    assert TOPOLOGY_VERTEX_ORIGIN_INVALID in validate_topology_provenance(
        unnormalized, output_vertex_count=3, output_face_count=1
    )


def test_validation_rejects_more_vertices_than_a_pac_u16_index_can_address() -> None:
    huge = SubmeshTopologyProvenance(
        version=TOPOLOGY_PROVENANCE_VERSION,
        original_vertex_count=1,
        original_face_count=1,
        vertex_origins=(VertexOrigin((0,), (1.0,)),),
        face_origins=(0,),
    )

    blockers = validate_topology_provenance(
        huge,
        output_vertex_count=TOPOLOGY_MAX_PAC_VERTEX_COUNT + 1,
        output_face_count=1,
    )

    assert TOPOLOGY_PAC_INDEX_LIMIT_EXCEEDED in blockers


# ── operation identity and history ───────────────────────────────────


def test_native_actions_map_to_the_three_stable_operation_names() -> None:
    assert topology_operation_for_native_action("delete") == TOPOLOGY_OPERATION_DELETE_FACES
    assert topology_operation_for_native_action("loop_cut") == TOPOLOGY_OPERATION_LOOP_CUT
    assert topology_operation_for_native_action("subdivide") == TOPOLOGY_OPERATION_SUBDIVIDE_MIDPOINT
    assert topology_operation_for_native_action("refine_smooth") == ""
    assert topology_operation_for_native_action("split") == ""


def _topology_operation(source_revision: int, result_revision: int, *, vertices: int = 3) -> MeshEditOperation:
    return MeshEditOperation(
        operation=TOPOLOGY_OPERATION_SUBDIVIDE_MIDPOINT,
        lod_index=0,
        submesh_index=0,
        vertex_count=vertices,
        source="resident_native",
        metadata=topology_operation_metadata(
            input_vertex_count=3,
            input_face_count=1,
            output_vertex_count=vertices,
            output_face_count=4,
            source_revision=source_revision,
            result_revision=result_revision,
        ),
    )


def test_operation_metadata_carries_every_stable_key() -> None:
    metadata = _topology_operation(1, 2).metadata

    assert set(TOPOLOGY_METADATA_KEYS) <= set(metadata)
    assert metadata["topology_contract"] == TOPOLOGY_PROVENANCE_VERSION


def test_revision_continuity_is_proven_not_inferred_from_names() -> None:
    assert validate_topology_operation_history(()) == ()
    assert validate_topology_operation_history((_topology_operation(0, 1), _topology_operation(1, 2))) == ()

    gapped = (_topology_operation(0, 1), _topology_operation(4, 5))
    assert TOPOLOGY_REVISION_DISCONTINUOUS in validate_topology_operation_history(gapped)

    backwards = (_topology_operation(3, 3),)
    assert TOPOLOGY_REVISION_DISCONTINUOUS in validate_topology_operation_history(backwards)


def _contract_submesh() -> SubMesh:
    provenance = compose_topology_provenance(
        identity_topology_provenance(3, 2),
        copy_vertex_indices=(0, 1, -1),
        vertex_blends=({"index": 2, "left": 0, "right": 1, "factor": 0.5},),
        face_origins=(0,),
    )
    return SubMesh(
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.5, 0.0, 0.0)],
        faces=[(0, 1, 2)],
        source_vertex_map=list(topology_source_vertex_map(provenance)),
        source_vertex_map_authority="topology",
        topology_provenance=provenance,
    )


def test_topology_operation_validation_accepts_the_derived_sentinel() -> None:
    mesh = ParsedMesh(format="pac", submeshes=[_contract_submesh()])

    issues = validate_mesh_edit_operations((_topology_operation(0, 1),), mesh=mesh)

    assert issues == ()
    assert mesh.submeshes[0].source_vertex_map[2] == TOPOLOGY_DERIVED_SOURCE_SENTINEL


def test_a_topology_operation_without_a_contract_on_its_submesh_is_blocked() -> None:
    bare = _contract_submesh()
    bare.topology_provenance = None
    mesh = ParsedMesh(format="pac", submeshes=[bare])

    codes = {issue.code for issue in validate_mesh_edit_operations((_topology_operation(0, 1),), mesh=mesh)}

    assert "topology_operation_provenance_missing" in codes


def test_topology_operation_without_its_metadata_is_blocked() -> None:
    mesh = ParsedMesh(format="pac", submeshes=[_contract_submesh()])
    bare = MeshEditOperation(
        operation=TOPOLOGY_OPERATION_SUBDIVIDE_MIDPOINT,
        submesh_index=0,
        vertex_count=3,
    )

    codes = {issue.code for issue in validate_mesh_edit_operations((bare,), mesh=mesh)}

    assert "topology_operation_metadata_missing" in codes


# ── MeshAsset adapter and rebuild validator branching ────────────────


def _topology_parsed_mesh() -> tuple[ParsedMesh, ParsedMesh, bytes]:
    """An original quad and its Face Delete result, sharing the same source bytes."""
    data = b"0000aaaabbbbccccddddiiii"
    original = SubMesh(
        name="body",
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0)],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)],
        normals=[(0.0, 0.0, 1.0)] * 4,
        faces=[(0, 1, 2), (1, 3, 2)],
        bone_indices=[(0,), (0,), (1,), (1,)],
        bone_weights=[(1.0,), (1.0,), (1.0,), (1.0,)],
        source_vertex_map=[0, 1, 2, 3],
        source_vertex_offsets=[4, 8, 12, 16],
        source_index_offset=20,
        source_index_count=6,
        source_vertex_stride=4,
        source_descriptor_offset=2,
        vertex_count=4,
        face_count=2,
    )
    provenance = compose_topology_provenance(
        identity_topology_provenance(4, 2),
        copy_vertex_indices=(0, 1, 2),
        face_origins=(0,),
    )
    edited = SubMesh(
        name="body",
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
        normals=[(0.0, 0.0, 1.0)] * 3,
        faces=[(0, 1, 2)],
        bone_indices=[(0,), (0,), (1,)],
        bone_weights=[(1.0,), (1.0,), (1.0,)],
        source_vertex_map=[0, 1, 2],
        source_vertex_map_authority="topology",
        source_vertex_offsets=[4, 8, 12],
        source_index_offset=20,
        source_index_count=6,
        source_vertex_stride=4,
        source_descriptor_offset=2,
        vertex_count=3,
        face_count=1,
        topology_provenance=provenance,
    )
    return (
        ParsedMesh(path="body.pac", format="pac", submeshes=[original], has_uvs=True, has_bones=True),
        ParsedMesh(path="body.pac", format="pac", submeshes=[edited], has_uvs=True, has_bones=True),
        data,
    )


def test_mesh_asset_adapter_carries_the_contract_and_its_compatibility_sentinels() -> None:
    _original_mesh, edited_mesh, data = _topology_parsed_mesh()

    asset = mesh_asset_from_parsed_mesh(edited_mesh, data)
    submesh = asset.lods[0].submeshes[0]

    assert submesh.topology_provenance is not None
    assert submesh.source_vertex_map_authority == "topology"
    assert submesh.source_index_map == ()
    assert submesh.index_buffer.original_count == 6
    assert submesh.source_vertex_map == (0, 1, 2)
    summary = mesh_asset_to_inspect_dict(asset)["lods"][0]["submeshes"][0]["topology_provenance"]
    assert summary["direct_vertex_count"] == 3
    assert summary["removed_face_count"] == 1


def test_rebuild_validator_accepts_an_exact_face_delete_contract() -> None:
    original_mesh, edited_mesh, data = _topology_parsed_mesh()
    original = mesh_asset_from_parsed_mesh(original_mesh, data)
    edited = mesh_asset_from_parsed_mesh(edited_mesh, data)

    result = validate_mesh_asset_rebuild(original, edited, allow_topology_change=True)

    assert result.ok is True, {issue.code for issue in result.blocking_issues}


def test_rebuild_validator_still_blocks_a_topology_contract_without_authorization() -> None:
    original_mesh, edited_mesh, data = _topology_parsed_mesh()
    original = mesh_asset_from_parsed_mesh(original_mesh, data)
    edited = mesh_asset_from_parsed_mesh(edited_mesh, data)

    codes = {issue.code for issue in validate_mesh_asset_rebuild(original, edited).issues}

    assert "TOPOLOGY_OPERATION_NOT_REBUILDABLE" in codes
    assert "SUBMESH_VERTEX_COUNT_CHANGED" in codes


def test_rebuild_validator_blocks_a_derived_vertex_carrying_a_synthesized_record() -> None:
    original_mesh, edited_mesh, data = _topology_parsed_mesh()
    edited_submesh = edited_mesh.submeshes[0]
    edited_submesh.vertices.append((0.5, 0.0, 0.0))
    edited_submesh.uvs.append((0.5, 0.0))
    edited_submesh.normals.append((0.0, 0.0, 1.0))
    edited_submesh.bone_indices.append((0,))
    edited_submesh.bone_weights.append((1.0,))
    edited_submesh.source_vertex_map.append(-1)
    # A derived vertex must not name an original record; point it at one anyway.
    edited_submesh.source_vertex_offsets.append(8)
    edited_submesh.faces = [(0, 3, 2), (3, 1, 2)]
    edited_submesh.topology_provenance = compose_topology_provenance(
        identity_topology_provenance(4, 2),
        copy_vertex_indices=(0, 1, 2, -1),
        vertex_blends=({"index": 3, "left": 0, "right": 1, "factor": 0.5},),
        face_origins=(0, 0),
    )

    original = mesh_asset_from_parsed_mesh(original_mesh, data)
    edited = mesh_asset_from_parsed_mesh(edited_mesh, data)
    codes = {issue.code for issue in validate_mesh_asset_rebuild(original, edited, allow_topology_change=True).issues}

    assert "RAW_VERTEX_RECORDS_CHANGED" in codes


def test_rebuild_validator_blocks_a_direct_vertex_that_lost_its_original_skin_row() -> None:
    original_mesh, edited_mesh, data = _topology_parsed_mesh()
    edited_mesh.submeshes[0].bone_indices[2] = (7,)

    original = mesh_asset_from_parsed_mesh(original_mesh, data)
    edited = mesh_asset_from_parsed_mesh(edited_mesh, data)
    codes = {issue.code for issue in validate_mesh_asset_rebuild(original, edited, allow_topology_change=True).issues}

    assert "BONE_DATA_CHANGED" in codes


def test_rebuild_validator_blocks_a_contract_whose_authority_was_not_declared() -> None:
    original_mesh, edited_mesh, data = _topology_parsed_mesh()
    edited_mesh.submeshes[0].source_vertex_map_authority = "target_donor_record"

    original = mesh_asset_from_parsed_mesh(original_mesh, data)
    edited = mesh_asset_from_parsed_mesh(edited_mesh, data)
    codes = {issue.code for issue in validate_mesh_asset_rebuild(original, edited, allow_topology_change=True).issues}

    assert TOPOLOGY_PROVENANCE_REQUIRED in codes


def test_domain_and_modding_topology_authority_strings_agree() -> None:
    from cdmw.domain.mesh.asset import SOURCE_VERTEX_MAP_TOPOLOGY as domain_value
    from cdmw.modding.mesh_skinning import SOURCE_VERTEX_MAP_TOPOLOGY as modding_value

    assert domain_value == modding_value == "topology"


# ── export readiness (Checks panel authority) ────────────────────────


def test_export_validation_admits_an_exact_topology_contract() -> None:
    original_mesh, edited_mesh, _data = _topology_parsed_mesh()

    report = validate_mesh_export(edited_mesh, original_mesh=original_mesh, skeleton_bone_count=8)
    codes = {issue.code for issue in report.issues if issue.severity == "blocker"}

    assert "submesh_vertex_count_changed" not in codes
    assert "submesh_index_count_changed" not in codes
    assert "source_vertex_map_invalid" not in codes
    assert "source_vertex_offsets_changed" not in codes
    assert "skinning_data_changed" not in codes


def test_export_validation_still_blocks_a_count_change_without_a_contract() -> None:
    original_mesh, edited_mesh, _data = _topology_parsed_mesh()
    edited_mesh.submeshes[0].topology_provenance = None

    report = validate_mesh_export(edited_mesh, original_mesh=original_mesh, skeleton_bone_count=8)
    codes = {issue.code for issue in report.issues if issue.severity == "blocker"}

    assert "submesh_vertex_count_changed" in codes
    assert "submesh_index_count_changed" in codes


def test_export_validation_reports_a_malformed_contract_and_keeps_legacy_blockers() -> None:
    original_mesh, edited_mesh, _data = _topology_parsed_mesh()
    # Claim a contract that describes a different original submesh.
    edited_mesh.submeshes[0].topology_provenance = compose_topology_provenance(
        identity_topology_provenance(9, 5),
        copy_vertex_indices=(0, 1, 2),
        face_origins=(0,),
    )

    report = validate_mesh_export(edited_mesh, original_mesh=original_mesh, skeleton_bone_count=8)
    codes = {issue.code for issue in report.issues if issue.severity == "blocker"}

    assert "topology_contract_unsupported" in codes
    assert "submesh_vertex_count_changed" in codes


def test_export_validation_blocks_a_derived_vertex_that_claims_an_original_record() -> None:
    original_mesh, edited_mesh, _data = _topology_parsed_mesh()
    edited = edited_mesh.submeshes[0]
    edited.vertices.append((0.5, 0.0, 0.0))
    edited.uvs.append((0.5, 0.0))
    edited.normals.append((0.0, 0.0, 1.0))
    edited.bone_indices.append((0,))
    edited.bone_weights.append((1.0,))
    edited.source_vertex_map.append(-1)
    edited.source_vertex_offsets.append(8)
    edited.faces = [(0, 3, 2), (3, 1, 2)]
    edited.topology_provenance = compose_topology_provenance(
        identity_topology_provenance(4, 2),
        copy_vertex_indices=(0, 1, 2, -1),
        vertex_blends=({"index": 3, "left": 0, "right": 1, "factor": 0.5},),
        face_origins=(0, 0),
    )

    report = validate_mesh_export(edited_mesh, original_mesh=original_mesh, skeleton_bone_count=8)
    codes = {issue.code for issue in report.issues if issue.severity == "blocker"}

    assert "source_vertex_offsets_changed" in codes


def test_same_count_workflows_keep_their_existing_source_index_map() -> None:
    original_mesh, _edited_mesh, data = _topology_parsed_mesh()

    asset = mesh_asset_from_parsed_mesh(original_mesh, data)
    submesh = asset.lods[0].submeshes[0]

    assert submesh.topology_provenance is None
    assert submesh.source_index_map == (0, 1, 2, 3, 4, 5)
    assert submesh.source_vertex_map == (0, 1, 2, 3)
