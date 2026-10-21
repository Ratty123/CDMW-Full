"""Skinned cleanup must preserve donor rows without admitting weight edits."""

import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.domain.mesh.export_validation import validate_mesh_export
from cdmw.modding.mesh_parser import parse_pac
from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession
from tests.test_mesh_pac_topology_serializer import _pac_fixture
from tests.test_mesh_rust_authoring_exact_output import _open_exact_session, _request


def _compacted_mesh():
    original = parse_pac(_pac_fixture(skinned=True), "owned-cleanup.pac")
    edited = copy.deepcopy(original)
    part = edited.submeshes[0]
    for name in (
        "vertices", "normals", "tangents", "tangent_signs", "uvs",
        "bone_indices", "bone_weights", "source_vertex_map", "source_vertex_offsets",
    ):
        values = getattr(part, name, ())
        if len(values) == 4:
            setattr(part, name, list(values[1:]))
    part.faces = [(0, 2, 1)]
    part.vertex_count = edited.total_vertices = 3
    part.face_count = edited.total_faces = 1
    return original, edited


def test_free_edit_accepts_only_original_skin_rows_after_source_record_compaction():
    original, edited = _compacted_mesh()

    report = validate_mesh_export(edited, original_mesh=original, exact_output=False)

    assert report.ok, report.blockers
    exact = validate_mesh_export(edited, original_mesh=original)
    assert "skinning_data_changed" in {issue.code for issue in exact.blockers}


@pytest.mark.parametrize("retained_weights", [(0.5, 0.25), (0.125,) * 8])
def test_free_edit_compaction_retains_original_unnormalized_and_extra_influence_rows(retained_weights):
    original, edited = _compacted_mesh()
    indices = tuple(range(len(retained_weights)))
    original.submeshes[0].bone_indices[1] = indices
    original.submeshes[0].bone_weights[1] = retained_weights
    edited.submeshes[0].bone_indices[0] = indices
    edited.submeshes[0].bone_weights[0] = retained_weights

    report = validate_mesh_export(edited, original_mesh=original, exact_output=False)

    assert report.ok, report.blockers
    if sum(retained_weights) != 1.0:
        assert "preserved_unnormalized_bone_weights" in {issue.code for issue in report.warnings}


@pytest.mark.parametrize("damage", [
    "weights", "indices", "missing_map", "missing_original_map", "missing_offsets",
    "wrong_offset", "wrong_authority", "wrong_descriptor", "wrong_stride",
    "duplicate_record", "wrong_record", "out_of_range_record", "fractional_record",
])
def test_free_edit_compaction_rejects_changed_skin_rows_or_unproven_lineage(damage):
    original, edited = _compacted_mesh()
    part = edited.submeshes[0]
    if damage == "weights":
        part.bone_weights[0] = (0.25, 0.75)
    elif damage == "indices":
        part.bone_indices[0] = (7, 3)
    elif damage == "missing_map":
        part.source_vertex_map = []
    elif damage == "missing_original_map":
        original.submeshes[0].source_vertex_map = []
    elif damage == "missing_offsets":
        part.source_vertex_offsets = []
    elif damage == "wrong_offset":
        part.source_vertex_offsets[0] += part.source_vertex_stride
    elif damage == "wrong_authority":
        part.source_vertex_map_authority = "topology"
    elif damage == "wrong_descriptor":
        part.source_descriptor_offset += 64
    elif damage == "wrong_stride":
        part.source_vertex_stride += 4
    elif damage == "duplicate_record":
        part.source_vertex_map[1] = part.source_vertex_map[0]
        part.source_vertex_offsets[1] = part.source_vertex_offsets[0]
    elif damage == "wrong_record":
        part.source_vertex_map[0] = 2
    elif damage == "out_of_range_record":
        part.source_vertex_map[0] = 999
    elif damage == "fractional_record":
        part.source_vertex_map[0] = 1.5

    report = validate_mesh_export(edited, original_mesh=original, exact_output=False)

    assert "skinning_data_changed" in {issue.code for issue in report.blockers}


@pytest.mark.parametrize("indices, weights, blocker", [
    ((-1, 7), (0.5, 0.5), "invalid_bone_index"),
    ((3, 7), (float("nan"), 0.5), "invalid_bone_weight"),
    ((3, 7), (-0.5, 1.5), "invalid_bone_weight"),
    ((3, 7), (0.5,), "bone_weight_row_mismatch"),
])
def test_free_edit_compaction_still_validates_each_skin_row(indices, weights, blocker):
    original, edited = _compacted_mesh()
    edited.submeshes[0].bone_indices[0] = indices
    edited.submeshes[0].bone_weights[0] = weights

    report = validate_mesh_export(edited, original_mesh=original, exact_output=False)

    assert {"skinning_data_changed", blocker} <= {issue.code for issue in report.blockers}


def _command(session, request_id, command, **arguments):
    request = _request(session, "command_request", request_id)
    request.update(command=command, arguments=arguments)
    return session.run_command(request)


def test_remove_doubles_can_undo_redo_finish_reopen_and_publish_without_changing_source(tmp_path: Path):
    source, service, session = _open_exact_session(tmp_path / "session")
    sid = session.authoritative_session_id
    reopened = None
    try:
        _command(session, 1, "configure_output_policy",
                 policy="free_edit_rebuild", destination=str(tmp_path / "output"))
        _command(session, 2, "mesh_action", action="remove_doubles",
                 selection={"vertices_by_submesh": {"0": [0, 1]},
                            "edges_by_submesh": {}, "faces_by_submesh": {}, "source_indices": []},
                 params={"threshold": 1.01})
        cleaned = session.shadow_service.working_mesh(session.shadow_session_id, clone=True)
        assert len(cleaned.submeshes[0].vertices) == 3
        assert len(service.working_mesh(sid, clone=False).submeshes[0].vertices) == 4
        _command(session, 3, "undo")
        assert len(session.shadow_service.working_mesh(session.shadow_session_id, clone=False).submeshes[0].vertices) == 4
        _command(session, 4, "redo")
        restored = session.shadow_service.working_mesh(session.shadow_session_id, clone=True)
        assert restored.submeshes[0].bone_indices == cleaned.submeshes[0].bone_indices
        assert restored.submeshes[0].bone_weights == cleaned.submeshes[0].bone_weights
        assert restored.submeshes[0].source_vertex_offsets == cleaned.submeshes[0].source_vertex_offsets

        result = session.finish(_request(session, "finish_request", 5))
        assert result["free_edit_output_validation"]["status"] == "passed"
        accepted = service.working_mesh(sid, clone=True)
        assert accepted.submeshes[0].bone_indices == cleaned.submeshes[0].bone_indices
        assert accepted.submeshes[0].bone_weights == cleaned.submeshes[0].bone_weights
        assert service.validate_export(sid).ok  # Verified cleanup now also has an exact PAC route.

        reopened = RustMeshAuthoringSession.create(
            SimpleNamespace(mesh_service=service, active_session_id=sid),
            tmp_path / "reopened", process_generation=12)
        result = reopened.finish(_request(reopened, "finish_request", 6))
        assert result["free_edit_output_validation"]["status"] == "passed"
        output = service.export_free_edit_output(sid)
        assert output.vertex_count == 3 and output.face_count == 1
        assert output.exact_archive_writeback is False
        assert service._session(sid).original_data == source
        assert len(service._session(sid).base_mesh.submeshes[0].vertices) == 4
    finally:
        if not session.closed:
            session.cancel()
        if reopened is not None and not reopened.closed:
            reopened.cancel()
        service.close_edit_session(sid, force_without_saving=True)
